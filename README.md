# tiktok-profile-scraper

Extract public statistics from TikTok accounts — follower, following, like
and video counts, the bio and its link, verification and TikTok Shop seller
flags, account creation date, and the settings a creator publishes.

Playwright, Selenium or Puppeteer, or no browser at all. Captcha solving,
proxies and fingerprints are wired in and, on this route, unnecessary — see
below, with the measurement.

---

## You do not need a key, a proxy, or an account

A TikTok profile page is server-rendered and served to anyone. Measured
**2026-09-22** from a bare datacentre address (Hetzner, Helsinki,
AS24940), with no credentials of any kind:

| request | result |
|---|---|
| `curl https://www.tiktok.com/@nasa` (curl's own User-Agent) | HTTP 200, 369,784 bytes, complete account object |
| the same with a Chrome User-Agent | HTTP 200, 386,985 bytes, complete account object |
| headless Chromium | HTTP 200, account rendered |
| headful Chromium | HTTP 200, account rendered |

Note which way round that is. A sibling repo in this family
(`rakuten-scraper`) found a site where curl claiming to be Chrome was
**refused** while curl claiming to be curl was served — the gate being the
client rather than the address. TikTok's profile route does neither.

So the default transport here is plain HTTPS and a browser is a fallback,
not the engine. Measured on the same machine, three accounts, end to end,
median of three runs:

```
--transport http      1.54 s
--transport browser   3.38 s      identical rows
```

The browser costs 2.2x and buys nothing on this route. It is what
`--transport auto` falls back to the moment the site actually challenges,
because an HTTP client has nowhere to put a solved token and no DOM to find
a widget in.

**What the paid products buy here**, stated plainly because the honest
answer is "not much on this route": volume from many addresses, a specific
exit country, and no browser infrastructure of your own. Not access. If you
are reading fewer than a few thousand accounts from one address, you need
none of it.

### A residential proxy is worse than no proxy here

This is the opposite of what this family's other repos would lead you to
expect, so it is stated with the numbers. Measured 2026-09-22,
`GET /@nasa` with a plain HTTP client:

| exit | served |
|---|---|
| this bare datacentre address (Hetzner, Helsinki) | **3 of 3** |
| a residential pool, nine different exits | **2 of 9** |

The seven that were not served answered HTTP 200 with 1,462 bytes whose
visible text is `Please wait...` — TikTok's **WAF** interstitial
(`SlardarWAF`, a `_wafchallengeid` element, a `waf-aiso/*.js` script). It
is a JavaScript challenge, not a captcha: there is no widget and nothing
for a solver to solve.

**A browser clears it.** Driving Chromium through the very exits that had
just refused a plain HTTP client: **3 of 3 served, 0 still challenged.**

So on this site `--transport auto` is load-bearing rather than insurance.
The run recognises the interstitial as its own state (`waf_challenge`),
counts it as blocked, and starts a browser — which is the measured
remedy. If you are running without a proxy from a clean address, you will
probably never see it.

---

## Quick start

```bash
git clone https://github.com/2scraper/tiktok-profile-scraper
cd tiktok-profile-scraper
python3 -m venv venv
./venv/bin/pip install -r requirements.txt -r requirements-playwright.txt
./venv/bin/python playwright_scraper.py --url nasa
```

That is the whole setup. No key, no `.env`, no browser download — the
default transport needs none of them. Install a browser only if you want
`--transport browser`:

```bash
./venv/bin/python -m playwright install chromium
```

More accounts, in one run, in parallel:

```bash
./venv/bin/python playwright_scraper.py \
    --url nasa,khaby.lame,zachking,tiktok --concurrency 4 --format both
```

`--url` takes a handle, an `@handle`, or a full profile URL, and a
comma-separated list of any mixture of them.

---

## The trap that shapes every number in the output

**TikTok publishes each count twice, and the two disagree.** Every profile
page carries a `stats` object and a `statsV2` object. Measured 2026-09-22
across eighteen accounts:

| account | `stats.followerCount` | `statsV2.followerCount` | error |
|---|---:|---:|---:|
| @tiktok | 95,900,000 | 95,856,713 | +43,287 |
| @khaby.lame | 163,000,000 | 162,986,107 | +13,893 |
| @nasa | 1,800,000 | 1,785,290 | +14,710 |
| @charlidamelio | 160,200,000 | 160,206,612 | -6,612 |
| @zachking | 86,900,000 | 86,900,407 | -407 |
| a small account | 429,700 | 429,675 | +25 |

`stats` is rounded to three significant figures and **rounds both up and
down**, so a consumer cannot correct for it and cannot even tell which
direction to distrust. `statsV2` is exact, and is what every row here
carries. The `stats_source` column records which object each row was read
from, and the run's sidecar counts them, so a run of rounded numbers is
visible rather than something you have to notice column by column.

Reading the obvious field gives a number that looks right and is wrong.
That is the single most valuable thing this repo knows.

### The counts move

Nine refetches of one account within an hour on 2026-09-22 returned
1,785,290 ... 1,785,310 followers — all different, none wrong. Two runs of
this scraper an hour apart will differ on almost every row. `diff_runs.py`
reports those as changes because they are changes; the canary asserts a
floor and a range, never an equality.

---

## What you get

41 columns per account. The full list is in `sample_output.csv`, cut from a
real run. The ones worth naming:

| column | note |
|---|---|
| `sku`, `user_id` | the **permanent numeric** account id — the join key |
| `username` | the @handle, which the account can change |
| `sec_uid` | TikTok's own per-account token, so a row is directly usable as an input to further work |
| `follower_count`, `following_count`, `likes_count`, `video_count` | exact, from `statsV2` |
| `friend_count` | accounts that follow this one and are followed back |
| `digg_count` | likes this account has **given**. 0 means "none **or** hidden" — read `open_favorite` beside it |
| `likes_per_video` | arithmetic on two numbers the site published, null when the account has no videos |
| `stats_source` | `statsV2` / `stats` / `absent` |
| `bio`, `bio_link` | `bio_link` was set on 9 of 12 large accounts measured |
| `avatar_url`, `avatar_id`, `avatar_expires_at` | see below |
| `is_seller`, `commerce_user` | TikTok Shop seller — the link to `tiktok-shop-scraper` |
| `verified`, `private_account`, `is_organization`, `secret` | |
| `created_at`, `nickname_modified_at` | ISO-8601 UTC; TikTok's 0 for "never" is null, not 1970 |
| `comment_setting`, `duet_setting`, `stitch_setting`, `download_setting`, `following_visibility`, `open_favorite`, `show_playlist_tab` | TikTok's own small integers, passed through unchanged rather than mapped to words this repo would have to invent |

### Three traps that look like bugs

**The avatar URL changes on every run.** It is a signed CDN URL and the
signature is re-minted per request. Measured: the signed form answers HTTP
200 with a 77 KB JPEG and expires 47.7 hours out; the same URL with the
query string stripped answers **HTTP 403**, so it cannot be normalised
away. `avatar_id` — the stable content hash from the same URL — is what
changes when the account actually changes its picture, and it is what
`diff_runs.py` tracks. `avatar_expires_at` tells you when the link dies.

**`--locale` does not translate anything.** Measured 2026-09-22:
`?lang=ja` and `?lang=ar` return a localised page **chrome** and
byte-identical data — same nickname, same bio, same id, same counts.
Creator-authored text is creator-authored in whatever language they wrote
it. The flag is there because the family's CLI contract has it, and because
the page's own furniture does change.

**A handle with no account gives TikTok's word "user banned".** TikTok
answers a nonexistent handle with HTTP 200, a full 370 KB app shell, and
`statusCode: 10221`, `statusMsg: "user banned"`, `userInfo: null` — the
same answer it gives for an account that really was banned. **This repo
does not claim to tell the two apart**, because TikTok does not. The run
reports it in the sidecar's `handles_unavailable`, exits 4 if nothing else
was found, and never reports it as a block.

---

## Where this repo stops, and why there are three

TikTok's gating is **per-route, not per-site**. "TikTok is gated" is true
and useless. Measured 2026-09-22:

| route | what happens |
|---|---|
| `/@handle` — this repo | served to everything tried |
| `/@handle/video/{id}` | served to plain curl, ~392 KB, full item |
| `/embed/@handle` | served to plain curl, ~294 KB, 11 most recent videos |
| `/api/post/item_list/` (the profile's video grid) | **HTTP 200, `content-length: 0`** |
| `shop.tiktok.com/**` | a slide-puzzle captcha |

The video-feed refusal is worth stating precisely, because it is the shape
that fools a client. Asked with a correctly signed request generated by
TikTok's own front end — msToken, X-Gnarly, X-Dynosaur, device_id all
present — over headless Chromium, headful Chromium, a Windows user agent,
after accepting the EU cookie consent, and through a residential exit in
Peru, it answered HTTP 200 with a zero-length JSON body **every time**.
Zero video links reached the DOM in any variant.

A client that checks `response.ok` calls that a success and reports an
account with no videos. This repo gives it its own state (`empty_success`),
counts it as blocked, and exits 3.

So:

* **`tiktok-profile-scraper`** (this one) — accounts. No credentials.
* **`tiktok-video-scraper`** — videos and their descriptions, from the
  embed route and the video pages, which are open.
* **`tiktok-shop-scraper`** — shop products, behind a captcha, where a
  2Captcha key is load-bearing rather than optional.

---

## Engines, and what each one costs you

All four paths produce identical rows. Verified on 2026-09-22: two accounts
fetched by each of the three engines, compared column by column — the only
differences were the live counters and the re-minted avatar signature.

```bash
./venv/bin/python playwright_scraper.py --url nasa      # primary
./venv/bin/python selenium_scraper.py   --url nasa
./venv/bin/python puppeteer_scraper.py  --url nasa
./venv/bin/python scraper_api_client.py --url nasa      # 2Captcha Scraper API
```

**Install exactly one engine.** The three declare mutually unsatisfiable
pins (`pyee` <12 vs >=13 for playwright/pyppeteer; `urllib3` <2.0 vs >=2.6
for pyppeteer/selenium). They do run side by side in practice, but
`pip check` reports the conflict and pip may resolve it by downgrading
something you wanted. Use a virtualenv per engine.

Two engine limits worth knowing before you hit them:

* **Selenium cannot use an authenticated remote CDP endpoint.** Playwright
  and Puppeteer take a full `ws://user:pass@host:port`; chromedriver's
  `debuggerAddress` takes a bare `host:port` with nowhere to put a
  password.
* **Selenium's `--proxy-server` cannot authenticate at all.** Credentials
  are stripped and a warning is printed rather than letting you believe a
  `user:pass` URL is doing something.

---

## Exit codes

| code | meaning |
|---|---|
| 0 | ok |
| 1 | crash |
| 2 | bad usage |
| 3 | blocked |
| 4 | zero accounts — including "TikTok returned no account for every handle asked" |
| 5 | the content was never obtained (a navigation timeout, a dead proxy, a remote API error) |
| 6 | partial — some accounts fetched, some failed |

**A run that finds nothing writes nothing.** Last night's good output is
never replaced with `[]`. `--allow-empty` is the opt-out.

Every run writes `<out>.meta.json` beside its output, recording the status,
the stop reason, **which** accounts failed by number, and
`handles_unavailable` and `stats_sources`.

---

## Configuration

Credentials live in `.env` beside the scripts, never on a command line — a
secret in `argv` is readable by anything that can run `ps`.

```bash
cp .env.example .env
python3 env_config.py      # prints what was picked up, WITHOUT printing secrets
```

Precedence, highest first: **an explicit flag -> an exported environment
variable -> `.env` -> the default.** A value still carrying a
`{placeholder}` is treated as unset, so a copied example is never sent to
an API as if it were a key.

Variables: `TWOCAPTCHA_KEY`, `TIKTOK_CDP_ENDPOINT`, `TIKTOK_PROXY`,
`TIKTOK_URL`.

---

## The daily canary

`.github/workflows/canary.yml` runs a real scrape against live TikTok every
morning **from a bare GitHub runner with no secrets**, and is expected to be
green.

That is not a convenience. The central claim of this README is "you need no
key, no proxy and no account", and an ungated scheduled canary is that
sentence under test every morning. If TikTok ever puts the profile route
behind a challenge, the badge goes red the next day and the claim is
retested without anyone having to remember to.

---

## Contributing, and what the checks are for

```bash
python3 smoke_test.py       # the offline suite — no network, no browser needed
python3 -m pytest           # the same checks, through pytest
```

The suite is one file of plain functions with fixtures cut from real
captures. It passes with no engine library installed at all, and CI fails
if an engine group reports an *unexpected* skip — "skipped, engine absent"
reads identically to a real import error.

It also holds the fixture CLAUDE.md asks every repo in this family to
hold: the material the 2Captcha Scraping Browser's auto-solve extension
injects into every page it loads. Measured 2026-09-22 on a real
`--cdp-endpoint` fetch of a page TikTok served — 16 `chrome-extension://`
tags, 4 `hunter.js`, and `cf-turnstile` once. That last one is the trap:
carried as a marker, it reports a blocked run on a perfectly good page
over a paid connection. This repo does not carry it, and the check
splices the injection into every served fixture to keep that true rather
than accidental.

---

## Licence

MIT. See `LICENSE`.

Captcha solving, the Scraping Browser API, proxies and fingerprints are
four separately-billed [2Captcha](https://2captcha.com) products behind one
key. This repo needs none of them for its own route, and says so above with
the measurement.
