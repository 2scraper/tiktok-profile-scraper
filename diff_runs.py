#!/usr/bin/env python3
"""
diff_runs.py
-------------
Compares two output files from this project (JSON, as written by
output_writer.save) and reports what changed between them, keyed on `sku`,
which here is the account's permanent numeric id rather than its @handle —
so a renamed account is a change in `username`, not a deletion plus an
arrival.

    python3 diff_runs.py --old accounts.2026-09-01.json \\
                          --new accounts.2026-09-07.json

Typical use is a scheduled re-run kept under a dated filename, diffed against
the previous one:

    python3 playwright_scraper.py --url nasa,zachking --out "accounts_$(date +%F)"
    python3 diff_runs.py --old "$(ls -t accounts_*.json | grep -v meta | sed -n 2p)" \\
                          --new "accounts_$(date +%F).json" --out diff.json

Four buckets, each keyed on sku:

  added          — sku present in --new, absent from --old
  removed        — sku present in --old, absent from --new: the account is
                   gone or unavailable, or this run's --url did not name it
  changed        — sku present in both, with a different count, bio, flag
                   or published setting. See TRACKED_FIELDS.
  source_changed — sku present in both, but one row's counts were read from
                   the exact `statsV2` object and the other's from the
                   rounded `stats` fallback, and they differ on a count.
                   Reported separately because this says something about our
                   own two snapshots rather than about the account — and
                   --fail-on-change deliberately ignores it.

ONE THING TO KNOW BEFORE READING A DIFF OF THIS SITE
----------------------------------------------------
**The counts move on their own.** Nine refetches of one account within an
hour on 2026-09-22 returned 1,785,290 … 1,785,310 followers, all different,
none wrong. So two runs an hour apart legitimately differ on almost every
row, and `--fail-on-change` here means "tell me when a number moved", not
"tell me when something broke".

A row this project's parser could not recover a sku for (None) cannot be
matched across runs at all, so it is counted and reported separately rather
than silently folded into "added"/"removed", which would be wrong on its face.
"""

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Tuple

from output_writer import UNIQUE_BY_SKU_MODES

# What is worth watching on an account, and nothing else.
#
# EVERY NAME HERE MUST EXIST ON THE ROW CLASS, and that is not a style
# rule. This tuple arrived from the repo this one was ported from naming
# 25 fields the row class does not have — so the diff compared nothing and
# reported "0 changed" with exit 0 on a run where a tracked value had
# changed. A monitor that cannot see the thing it monitors is worse than
# no monitor, because it reports success. `smoke_test.py` pins every name
# here against the dataclass.
#
# DELIBERATELY NOT TRACKED, and each is a measurement rather than an
# oversight:
#
#   `follower_count`, `likes_count`, `video_count` ARE tracked, and they
#     are the point of this repo. Note that they MOVE: nine refetches of
#     one account within an hour on 2026-09-22 returned 1,785,290 …
#     1,785,310 followers, all different, none wrong. So a diff of two
#     runs an hour apart legitimately shows a delta on almost every row,
#     and `--fail-on-change` on this repo means "tell me when a number
#     moved", not "tell me when something broke".
#
#   `avatar_url` is NOT tracked, and this is the one that would otherwise
#     ruin every diff. TikTok serves avatars from a SIGNED CDN URL whose
#     signature is re-minted per request, so the column differs between two
#     runs taken seconds apart, on every row, while the picture is
#     identical. `avatar_id` — the stable content hash out of the same URL
#     — is tracked instead, and it changes when the account actually
#     changes its picture. CLAUDE.md §24 records a float32 round-trip
#     making two modes disagree on every row; this is the same defect
#     wearing a signature.
#
#   `avatar_expires_at` is not tracked for the same reason: it is a
#     property of the link, not of the account.
#
#   `sec_uid` is not tracked. It is an opaque token TikTok re-issues, and
#     a change in it says nothing a consumer can act on.
#
#   `user_id` is not tracked because it IS the join key (`sku`): a change
#     in it would mean the join was wrong rather than that anything
#     happened.
#
#   `position` and `page` — an artefact of the order --url named handles,
#     not a property of the account.
#
#   `scraped_at` and `stats_source` — the latter drives `source_changed`
#     instead, so a run that read `statsV2` and one that fell back to the
#     rounded `stats` do not report every count as having changed.

TRACKED_FIELDS = (
    # the counts this repo exists for
    "follower_count",
    "following_count",
    "likes_count",
    "video_count",
    "friend_count",
    "digg_count",
    "likes_per_video",
    # what the account says about itself. A bio edit and a new bio link
    # are the two most actionable changes on a creator account.
    "title",
    "username",
    "bio",
    "bio_link",
    "avatar_id",
    "language",
    # what kind of account it is. `is_seller` flipping is a TikTok Shop
    # seller appearing — the single column linking this repo to
    # tiktok-shop-scraper.
    "verified",
    "private_account",
    "is_organization",
    "is_seller",
    "commerce_user",
    "secret",
    # the settings an account publishes. A creator closing comments or
    # duets is an editorial act and shows up here.
    "comment_setting",
    "duet_setting",
    "stitch_setting",
    "download_setting",
    "following_visibility",
    "open_favorite",
    "show_playlist_tab",
    # the site's own verdict on the account
    "status",
    "status_code",
)

# The column that says which source a row was read from, and the tracked
# columns only ONE value of it can be trusted on. There is one route and
# one payload here, but that payload publishes every count twice: exactly
# in `statsV2` and rounded to three significant figures in `stats`, which
# the parser falls back to only when `statsV2` is absent. A count diffed
# across the two is rounding, so it goes to `source_changed` — which is
# what output_writer.py and the README say happens, and what an empty
# tuple here silently did not do.
SOURCE_COLUMN = "stats_source"
SOURCE_ONLY_FIELDS = (
    "follower_count",
    "following_count",
    "likes_count",
    "video_count",
    "friend_count",
    "digg_count",
    "likes_per_video",
)


def _load(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _by_sku(products: List[dict]) -> Tuple[Dict[str, dict], int]:
    indexed = {}
    unmatchable = 0
    for p in products:
        sku = p.get("sku")
        if sku is None:
            unmatchable += 1
            continue
        # A run's own output can already hold a duplicate sku (two rows in the
        # same category, or a rerun of dedupe_by_sku's job on older output
        # written before it existed) — keep the first and count the rest as
        # unmatchable rather than letting one clobber the other silently.
        if sku in indexed:
            unmatchable += 1
            continue
        indexed[sku] = p
    return indexed, unmatchable


def diff_products(old: List[dict], new: List[dict]) -> dict:
    old_by_sku, old_unmatchable = _by_sku(old)
    new_by_sku, new_unmatchable = _by_sku(new)

    added = [new_by_sku[sku] for sku in new_by_sku.keys() - old_by_sku.keys()]
    removed = [old_by_sku[sku] for sku in old_by_sku.keys() - new_by_sku.keys()]

    changed, source_changed = [], []
    for sku in old_by_sku.keys() & new_by_sku.keys():
        before, after = old_by_sku[sku], new_by_sku[sku]
        field_changes = {
            field: {"old": before.get(field), "new": after.get(field)}
            for field in TRACKED_FIELDS
            if before.get(field) != after.get(field)
        }
        if not field_changes:
            continue

        # A row whose SOURCE_COLUMN differs between runs is not comparable
        # on SOURCE_ONLY_FIELDS: a count read from the rounded `stats` object differs from the exact `statsV2` figure by rounding alone, so the difference would read as a change and none of it would be about the account. Reporting it as a change would be a
        # false alarm about the site; the other columns still compare fine.
        sources = ((before.get(SOURCE_COLUMN), after.get(SOURCE_COLUMN))
                   if SOURCE_COLUMN else (None, None))
        if sources[0] != sources[1] and any(f in field_changes
                                            for f in SOURCE_ONLY_FIELDS):
            source_part = {f: v for f, v in field_changes.items()
                           if f in SOURCE_ONLY_FIELDS}
            other_part = {f: v for f, v in field_changes.items()
                          if f not in SOURCE_ONLY_FIELDS}
            source_changed.append({
                "sku": sku, "title": after.get("title"),
                SOURCE_COLUMN: {"old": sources[0], "new": sources[1]},
                "changes": source_part,
            })
            field_changes = other_part
            if not field_changes:
                continue

        changed.append({"sku": sku, "title": after.get("title"),
                        "changes": field_changes})

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "source_changed": source_changed,
        "unmatchable_old": old_unmatchable,
        "unmatchable_new": new_unmatchable,
    }


def _describe(p: dict) -> str:
    """The one or two columns that make an added/removed line readable."""
    return f"@{p.get('username') or '?'}  {p.get('follower_count')} followers"


def _print_summary(result: dict) -> None:
    print(f"[+] {len(result['added'])} added, {len(result['removed'])} removed, "
          f"{len(result['changed'])} changed, "
          f"{len(result['source_changed'])} not comparable across run kinds.")
    for p in result["added"]:
        print(f"  + {p.get('sku')}  {p.get('title')}  {_describe(p)}")
    for p in result["removed"]:
        print(f"  - {p.get('sku')}  {p.get('title')}  {_describe(p)}")
    for c in result["changed"]:
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}"
                           for f, v in c["changes"].items())
        print(f"  ~ {c['sku']}  {c['title']}  {deltas}")
    for c in result["source_changed"]:
        src = c[SOURCE_COLUMN]
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}"
                           for f, v in c["changes"].items())
        print(f"  ? {c['sku']}  {c['title']}  {deltas}  "
              f"[{SOURCE_COLUMN} {src['old']!r} -> {src['new']!r}: "
              f"one side read the rounded `stats` fallback, so this is rounding, not a change in the account]")
    unmatchable = result["unmatchable_old"] + result["unmatchable_new"]
    if unmatchable:
        print(f"[!] {unmatchable} row(s) across both files had no sku or a "
              f"duplicate sku, and could not be matched across runs.")


def _run_status(path: str) -> Tuple[Optional[str], Optional[dict]]:
    """Read the `<out>.meta.json` sidecar beside a run's JSON output.

    Returns (status, meta), or (None, None) when there is no sidecar — which
    is the normal case for output written before run metadata existed, or by
    `scraper_api_client.py` (single fetch, no pagination to cut short).
    """
    meta_path = re.sub(r"\.json$", "", path) + ".meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None
    return meta.get("status"), meta


def _check_comparable(args) -> bool:
    """Refuse an assortment diff between runs that are not both complete.

    This is the failure mode the sidecar exists for: a run cut short on page
    3 of 10 is missing every product on pages 4-10, and diffing it against
    yesterday's full run reports all of them as `removed` — reading as "these
    products were delisted" when in fact they were simply never fetched.
    The rows both runs DID see are still comparable, which is why
    this is a refusal with a --force escape hatch rather than a hard error.
    """
    problems = []
    modes = {}
    for label, path in (("--old", args.old), ("--new", args.new)):
        status, meta = _run_status(path)
        if status is None:
            continue  # no sidecar: nothing to check, see _run_status
        mode = (meta or {}).get("mode")
        if mode:
            modes[label] = mode
        if mode and mode not in UNIQUE_BY_SKU_MODES:
            # This tool's whole premise is one row per `sku`, diffed on
            # TRACKED_FIELDS. A mode that produces many rows per sku would
            # give a diff whose every line is an artefact of two rows
            # sharing an id, so it is refused outright rather than answered.
            # Every mode this repo has qualifies; the check is here so that
            # adding one that does not is caught rather than discovered.
            problems.append(
                f"{label} ({path}) is a {mode!r} run, which is not one row "
                f"per sku. This tool diffs one row per sku, so there "
                f"is nothing here it can compare.")
        if status != "complete":
            problems.append(
                f"{label} ({path}) was a {status!r} run — stopped after "
                f"{meta.get('pages_completed')} of {meta.get('pages_requested')} "
                f"page(s), reason {meta.get('stop_reason')!r}")
    if len(set(modes.values())) > 1:
        problems.append(
            f"the two runs are different modes ({modes}). Rows from "
            f"different modes carry different columns, so "
            f"`added`/`removed` would describe the mode change rather "
            f"than the site.")

    # A SORT GUARD, family core. Where rows carry a `sort` column, two runs
    # under different orderings are different SAMPLES of a capped listing,
    # and diffing them reports the sampling as though the site had
    # changed. No tiktok-* row carries one today, so this guard is inert
    # here — kept rather than deleted so a route that gains an ordering is
    # guarded from its first run.
    #
    # `sort` is therefore a column rather than a sidecar field, so this
    # guard reads what is actually in the rows rather than trusting
    # metadata that a hand-edited file could contradict.
    sorts = {}
    for label, path in (("--old", args.old), ("--new", args.new)):
        rows, meta = _load(path), (_run_status(path)[1] or {})
        seen = {r.get("sort") for r in rows if isinstance(r, dict)}
        seen.discard(None)
        sorts[label] = (seen.pop() if len(seen) == 1
                        else meta.get("sort") or "?")
    if len(set(sorts.values())) > 1 and "?" not in sorts.values():
        problems.append(
            f"the two runs used different orderings ({sorts}). A run "
            f"that stops after N pages holds a different SET of rows under "
            f"each, so the diff would report the sampling "
            f"rather than the site.")

    if not problems:
        return True

    # A generic headline, because the reasons below are not only about
    # completeness: a mode mismatch and an ordering mismatch are refused too, and a
    # message naming the wrong reason sends the reader looking in the wrong
    # place.
    print("[!] Refusing to diff these two runs:")
    for line in problems:
        print(f"      {line}")
    print("    Re-run the incomplete side, or pass --force to compare anyway "
          "(added/removed will include rows that were simply never "
          "fetched).")
    return False


def parse_args():
    p = argparse.ArgumentParser(
        description="Diff two tiktok-profile-scraper JSON outputs by sku.")
    p.add_argument("--old", required=True, help="Earlier run's JSON output.")
    p.add_argument("--new", required=True, help="Later run's JSON output.")
    p.add_argument("--out", default=None,
                   help="Write the full diff as JSON to this path too.")
    p.add_argument("--fail-on-change", action="store_true",
                   help="Exit 1 if anything was added, removed or changed — "
                        "for a cron job that should only notify on a real diff.")
    p.add_argument("--force", action="store_true",
                   help="Diff even when a run's .meta.json says it was partial "
                        "or failed. Products never fetched by the short run will "
                        "appear as added/removed.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.force and not _check_comparable(args):
        return 2

    try:
        old = _load(args.old)
        new = _load(args.new)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Could not read one of the input files: {e}")
        return 2

    result = diff_products(old, new)
    _print_summary(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[+] Full diff written to {args.out}")

    # `source_changed` is not a reason to fail: it means one row's counts
    # came from the exact `statsV2` object and the other's from the rounded
    # `stats` fallback. That says something about our own two snapshots
    # rather than about the account, and alerting on it would train whoever
    # reads the alert to ignore it.
    if args.fail_on_change and (result["added"] or result["removed"] or result["changed"]):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
