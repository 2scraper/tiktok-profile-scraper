# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) as
closely as a CLI toolkit can. A patch release means **fixes** — it does not
promise that every flag's default is frozen, and where a default does change
in one, the note leads with it.

## [Unreleased]

### Fixed

> **`source_changed` never fired.** `diff_runs.py`'s source-split tuple was
> empty, so a count read from the rounded `stats` fallback diffed against
> an exact `statsV2` count was reported as the account having changed —
> the opposite of what `output_writer.py` and the README say. The count
> columns now go to `source_changed` when `stats_source` differs, and
> `smoke_test.py` checks it.

- **Donor prose removed from the shared core.** `output_writer.py`,
  `diff_runs.py`, the engines, `page_flow.py`, `smoke_test.py`,
  `.github/ci_checks.py` and the `Dockerfile` carried text from the repos
  this core was copied from — YouTube comment threads, `--sort top`,
  reply threads, job listings, "the business", `--mode comments --out
  software-engineer` — describing those sites as if they were this one.
  Rewritten from this repo's own README, code and fixtures, or deleted
  where there was no measured equivalent. Explicit sibling provenance
  ("measured on tiktok-profile-scraper's route", "a sibling repo
  (youtube-scraper) had…") is kept and now says whose it is.
- `diff_runs.py`'s summary printed `@ company_name` and "pay not stated"
  for every added or removed row; it now prints the handle and the
  follower count.
- The engines' `_prime_session` docstring no longer describes the YouTube
  repo this core came from.

- `captcha_solver.py`'s docstring pointed at a "No DataDome solver" section
  that does not exist in this repo (it came with the copied core). Removed.

## [0.1.1] — 2026-09-23

> **Correction to v0.1.0.** Its `captcha_solver.py` docstring described a
> 2Captcha captcha-solving method for TikTok as available. That method is
> deprecated, and the text no longer offers it. The challenge policy for
> TikTok's slide puzzle now says `solve: False`, which matches what the
> code does: no solver for it is implemented.

## [0.1.0] — 2026-09-22

First release. Reads a TikTok account's public statistics from the profile
page TikTok server-renders to anyone.

### The measurement this release exists to get right

TikTok publishes every account statistic **twice**, and the two objects
disagree. Measured across eighteen accounts on 2026-09-22:

| account | `stats.followerCount` | `statsV2.followerCount` | error |
|---|---:|---:|---:|
| @tiktok | 95,900,000 | 95,856,713 | +43,287 |
| @khaby.lame | 163,000,000 | 162,986,107 | +13,893 |
| @nasa | 1,800,000 | 1,785,290 | +14,710 |
| @charlidamelio | 160,200,000 | 160,206,612 | -6,612 |
| @zachking | 86,900,000 | 86,900,407 | -407 |

`stats` is rounded to three significant figures and rounds **both** ways, so
it cannot be corrected for. Every row here is read from `statsV2` and records
which object it came from in `stats_source`.

### Added

- `--mode profile`, over four interchangeable paths: Playwright, Selenium,
  Puppeteer, and the 2Captcha Scraper API. Verified to produce identical rows.
- `--transport auto|http|browser`. The default is plain HTTPS, because the
  page is server-rendered: measured 1.54 s against 3.38 s for three accounts
  end to end, for identical rows. The browser is the fallback for a challenge.
- `--url` takes a comma-separated list of handles, `@handles` or profile URLs,
  and `--concurrency` is genuinely usable because every account has its own
  address.
- 41 columns, including `avatar_id` and `avatar_expires_at` — TikTok serves
  avatars from a signed CDN URL whose signature is re-minted per request, so
  without a stable id every account would read as changed on every run.
  (Measured: the signed URL answers 200 with a 77 KB JPEG and expires 47.7 h
  out; with the query string stripped it answers 403.)
- `is_seller` / `commerce_user`, which is the link to `tiktok-shop-scraper`.

### Deliberately not here

- **Videos.** The profile page's own video grid is loaded by an XHR that
  answers `HTTP 200` with `content-length: 0` to every client tried —
  headless and headful Chromium, a Windows user agent, after accepting the EU
  cookie consent, and through a residential exit in Peru — with a correctly
  signed request. That refusal has its own run state (`empty_success`) and
  exits 3 rather than reporting an account with no videos. The open routes
  for video data are `/embed/@handle` and `/@handle/video/{id}`, and they are
  `tiktok-video-scraper`'s.
- **A distinction between a banned account and a handle that never existed.**
  TikTok answers both with `statusCode: 10221` and the message
  `"user banned"`. This repo reports the state and does not claim to tell
  them apart.
- **`username_modified_at`.** TikTok publishes `uniqueIdModifyTime` on every
  account and reported 0 — "never" — on all eighteen measured, so the column
  was removed rather than shipped null on every row. The measurement is recorded in
  `output_writer.py` so it can be added back with a better one.

### Known limitations

- The challenge-marker set is **not** verified against a page fetched over
  `--cdp-endpoint`. The 2Captcha Scraping Browser injects its own captcha
  hunters into every page it loads, and every profile available while this
  repo was built had expired (`401 deny_no_user`). The offline suite records
  this as a SKIP rather than passing silently.
- `--locale` changes the page's chrome and not its data: `?lang=ja` and
  `?lang=ar` returned byte-identical nickname, bio, id and counts.
