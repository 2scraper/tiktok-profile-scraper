# Contributing

Bug reports, site-change reports and pull requests are all welcome. This file
covers the few things specific to a scraper, which are not the usual ones.

## Before you open anything

Run the offline suite. It needs no network, no browser and no API key:

```bash
pip install -r requirements.txt
python3 smoke_test.py
```

It prints its own check count and lists any group it skipped because an engine
library is absent.

**The suite must pass with no engine installed at all.** CI installs only the
core requirements, so any import of `playwright_scraper`, `puppeteer_scraper`
or `selenium_scraper` in a check sits inside `try/except ImportError` with the
skip recorded. If the suite fails on a clean clone, that is itself the bug —
say so.

## Never commit a credential

`.env` and every `.env.*` variant except `.env.example` are in `.gitignore`.
Keep them there.

The engines mask `user:pass@` in their own log lines, but three things are
**not** masked: raw page dumps (`--dump-html`), the Scraper API's `x-debug`
response header, and your shell history. Before pasting output into an issue
or a PR, replace keys, proxy passwords and full `ws://user:pass@host:9222`
endpoints with `***`.

CI fails the build if something credential-shaped is committed. That is a
backstop, not a review.

## Reporting a site change

This repo reads TikTok account statistics from `www.tiktok.com/@handle`, which is served to a bare HTTP client from a datacentre address — no key, no proxy, no account.

The parser reads one structured source and never the rendered DOM:

    `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` → `__DEFAULT_SCOPE__["webapp.user-detail"].userInfo`

So a site change almost always shows up as that source moving or its shape
changing, and the most useful thing a report can carry is the source itself
from a dump — there is an issue template for exactly that.

## What the checks pin, and why

Each of these cost real time when it was found, and the offline suite pins it
so a PR that undoes one fails rather than silently regressing:

- **TikTok publishes every count twice, and the two disagree.** `stats` is rounded to three significant figures and rounds BOTH ways — 95,900,000 where `statsV2` says 95,856,713 on @tiktok. Every row reads `statsV2` and records which object it used in `stats_source`. A PR that reads `stats` will fail a check pinned by value on five real accounts.

- **A handle with no account says "user banned".** TikTok answers a nonexistent handle with HTTP 200, a full app shell and `statusCode: 10221, statusMsg: "user banned"` — the same answer it gives a banned account. The repo reports `user_unavailable` and does not claim to tell the two apart.

- **The refusal next door is an EMPTY SUCCESS.** `/api/post/item_list/` answers HTTP 200 with `content-length: 0` to every client tried, including a correctly signed browser request. It has its own state, `empty_success`, which counts as blocked. Anything that checks `response.ok` would call it a success.

- **A residential proxy is worse than no proxy here.** Measured: 3 of 3 served from a bare datacentre address, 2 of 9 through a residential pool — the rest got TikTok's WAF interstitial (HTTP 200, 1,462 bytes, `Please wait...`). A browser clears it, 3 of 3, which is what `--transport auto` falls back to.

- **The avatar URL changes on every run.** It is signed and re-minted per request, so `avatar_id` — the content hash from the same path — is what `diff_runs.py` tracks. Stripping the signature does not help: the unsigned URL answers 403.

Before adding a challenge marker, count it on a page you **know** was served.
A marker that matches every page is worse than no marker.

## Before a release

```bash
python3 smoke_test.py
python3 .github/ci_checks.py --history-check
```

The second applies the credential rules CI enforces to **every blob that has
ever existed**, not just the working tree. A commit on top cannot reach what a
published tag already holds.

The canary is **not** gated on a secret: the profile route is served to a bare GitHub runner, so it runs a real scrape daily and is expected GREEN. If TikTok ever puts this route behind a challenge, the badge goes red the next morning.

## Pull requests

Add a check for the behaviour you are changing. `smoke_test.py` is a single
file of plain functions; copy the nearest existing check and edit it. Keep the
three engines identical above their driver layer — a check compares their
public surfaces and flag sets in both directions.
