#!/usr/bin/env python3
"""make_fixtures.py — build `fixtures_generated.json` from real captures.

Why fixtures are TRIMMED rather than whole pages
================================================
A TikTok profile page is ~370 KB, and almost all of it is the app shell:
translation tables, A/B assignments, and the session material the page was
fetched with. Counted on the captures this repo was built from:

    csrf token            1 occurrence per page
    odinId                1
    x-signature (CDN)     3
    ttwid (embed pages)   1

None of it is a credential and all of it was anonymous and is expired. It
still does not belong in a public repo, and CLAUDE.md §10 is explicit that
the checks need the STRUCTURE of a thing, not the session that fetched it.

Every one of those lives OUTSIDE `__DEFAULT_SCOPE__["webapp.user-detail"]`,
which is the only scope this repo's parser reads. So trimming to that scope
is not a scrubbing step bolted on afterwards — it removes the session
material as a side effect of keeping only what is under test, which is the
version of this that cannot rot.

What IS kept, deliberately
==========================
The avatar's signed CDN URL, complete. `product_parser._avatar_parts()`
reads two things out of it — the stable 32-hex content hash and the
`x-expires` stamp — and a fixture with those removed would test neither.
The signature is left intact because a redacted one would not exercise the
`parse_qs` path either.

That 32-hex hash is the one exemption this repo's credential scan carries,
and it is scoped to a tiktokcdn URL rather than granted to the file
(CLAUDE.md §24: before adding an exemption, check whether the value is
needed at all — here it is, because a column reads it).

Verify a trimmed fixture parses identically to its untrimmed original
=====================================================================
`--verify` re-parses both and compares the rows field by field. CLAUDE.md
§15 asks for this before committing any trimmed fixture, and it is one
command rather than a promise.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from dataclasses import asdict
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from output_writer import Profile                       # noqa: E402
from product_parser import USER_DETAIL_SCOPE, parse_profile  # noqa: E402
from tiktok_payload import PayloadError, rehydration_scope    # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fixtures_generated.json")

# The captures these fixtures are cut from. Each one is here for a reason
# no other capture covers — CLAUDE.md §15's "one dump teaches you one
# locale", applied to account SHAPES as well as languages.
WANTED = {
    # A mid-sized verified organisation. The baseline.
    "prof_browser.html": ("nasa", "a verified organisation, ~1.8M followers"),
    # The largest account measured: nine-figure followers and ten-figure
    # likes, which is where an int that should have been a string breaks.
    "prof_khaby.html": ("khaby_lame", "163M followers, 2.68B likes"),
    # The account whose rounded and exact figures differ by only 407 —
    # the case a test written against @nasa's 14,710 would pass by luck.
    "prof_zach.html": ("zachking", "stats and statsV2 differ by 407"),
    # TikTok's own account, and the widest rounding gap measured: 43,287.
    "prof_tiktok.html": ("tiktok", "the widest stats/statsV2 gap, 43,287"),
    # A small account. Guards against a parser that only ever sees
    # abbreviated magnitudes.
    "prof_tiny.html": ("small_account", "429,675 followers, 6 videos"),
    # A handle with no account behind it. TikTok answers HTTP 200, 370 KB,
    # statusCode 10221, "user banned", userInfo null.
    "prof_404.html": ("unavailable", "statusCode 10221, no userInfo"),
    # A non-Latin locale, to pin that ?lang= moves the chrome and not the
    # data.
    "prof_nasa_ja.html": ("nasa_ja", "?lang=ja — same data, localised chrome"),
}


def trim(html: str) -> Dict[str, Any]:
    """A whole page down to the one scope the parser reads."""
    scope = rehydration_scope(html)
    detail = scope.get(USER_DETAIL_SCOPE)
    if detail is None:
        raise PayloadError(f"capture carries no {USER_DETAIL_SCOPE!r}")
    return {"__DEFAULT_SCOPE__": {USER_DETAIL_SCOPE: detail}}


def as_page(payload: Dict[str, Any]) -> str:
    """A trimmed scope back into the minimal page the parser accepts.

    Kept deliberately small, and NOT dressed up to look like a real page:
    a fixture that mimicked the shell would invite someone to test asset
    counting against it, and asset counting is exactly what a trimmed
    fixture cannot honestly exercise.
    """
    return ('<!DOCTYPE html><html><head><script id='
            '"__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            + json.dumps(payload, ensure_ascii=False)
            + "</script></head><body></body></html>")


def build(capture_dir: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"_readme": (
        "Generated by make_fixtures.py from real captures. Each entry is the "
        "`webapp.user-detail` scope of one real TikTok profile page, trimmed "
        "from a ~370 KB capture. Session material (csrf, odinId, ttwid) lives "
        "outside this scope and is therefore absent rather than redacted. Run "
        "`python3 make_fixtures.py --verify` to re-check that a trimmed "
        "fixture parses identically to its untrimmed original."
    ), "profiles": {}}
    missing = []
    for filename, (name, why) in WANTED.items():
        path = os.path.join(capture_dir, filename)
        if not os.path.exists(path):
            missing.append(filename)
            continue
        html = open(path, encoding="utf-8", errors="replace").read()
        out["profiles"][name] = {"why": why, "payload": trim(html)}
    if missing:
        print(f"[!] {len(missing)} capture(s) not found: {missing}",
              file=sys.stderr)
    return out


def verify(capture_dir: str) -> int:
    """Trimmed vs untrimmed, field by field. Exit 1 on any difference."""
    data = json.load(open(OUT, encoding="utf-8"))
    bad = 0
    for filename, (name, _why) in WANTED.items():
        path = os.path.join(capture_dir, filename)
        entry = data["profiles"].get(name)
        if entry is None or not os.path.exists(path):
            print(f"  {name:16} SKIP (no capture or no fixture)")
            continue
        original = open(path, encoding="utf-8", errors="replace").read()
        trimmed = as_page(entry["payload"])
        url = "https://www.tiktok.com/@x"
        rows_o, diag_o = parse_profile(original, url, "T", Profile)
        rows_t, diag_t = parse_profile(trimmed, url, "T", Profile)
        same = ([asdict(r) for r in rows_o] == [asdict(r) for r in rows_t]
                and diag_o.get("status") == diag_t.get("status"))
        print(f"  {name:16} {'OK' if same else 'DIFFERS'}  "
              f"({len(rows_o)} row(s), status {diag_o.get('status')})")
        if not same:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--captures", default="/home/petr/2scraper/captures/tiktok",
                   help="Directory holding the raw page captures. Not in the "
                        "repo: captures are large and are not committed.")
    p.add_argument("--verify", action="store_true",
                   help="Re-parse each fixture against its untrimmed original "
                        "and compare, rather than rebuilding.")
    args = p.parse_args()
    if args.verify:
        sys.exit(verify(args.captures))
    data = build(args.captures)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
    size = os.path.getsize(OUT)
    print(f"[+] {len(data['profiles'])} fixture(s) -> {OUT} ({size:,} bytes)")
