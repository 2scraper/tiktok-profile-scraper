"""product_parser.py — this IS the site.

Everything TikTok-shaped that is not one of the handful of named
constants in the engines lives here (CLAUDE.md §1). The generic reading of
TikTok's two structured payloads lives one file over, in
`tiktok_payload.py`, which is byte-identical across the tiktok-* repos and
SHA-pinned by each one's suite.

What this repo reads, and why that is the whole product
======================================================
A TikTok profile page is served to anyone. Measured 2026-09-22 from a
datacentre address (Hetzner, Helsinki, AS24940) with no key, no proxy, no
cookies and no account:

    GET https://www.tiktok.com/@nasa
        curl's own User-Agent      HTTP 200, 369,784 bytes
        a Chrome User-Agent        HTTP 200, 386,985 bytes

Both carry the complete account object. That is the opposite of the
neighbouring route: the video feed the same page loads by XHR
(`/api/post/item_list/`) answers HTTP 200 with a zero-length body to every
client tried, which is why THIS repo stops at the profile and
tiktok-video-scraper exists separately. CLAUDE.md §21: gating is per-ROUTE,
not per-site, and two routes that differ want different docs and different
canaries.

The trap that shapes every count here
=====================================
TikTok publishes each count twice and the two disagree — `stats` is
rounded to three significant figures and rounds both up and down, while
`statsV2` is exact. On @tiktok itself the gap is 43,287 followers. Reading
the obvious field gives a number that looks right, is wrong, and moves in
neither direction consistently. `tiktok_payload.counts()` does the
choosing; every row records which object it read in `stats_source`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from tiktok_payload import (
    BOT_CHALLENGE_MARKERS,
    PayloadError,
    is_empty_success,
    USER_STATUS_OK,
    USER_STATUS_UNAVAILABLE,
    USER_STATUS_UNKNOWN,
    counts,
    decode_page,
    rehydration_scope,
    user_status,
)

logger = logging.getLogger("product_parser")

SOURCE = "tiktok.com"

# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------
#
# Taken from the site's own behaviour rather than guessed. `tiktok.com`
# redirects to `www.tiktok.com`; the regional hosts TikTok publishes for
# its apps (`m.tiktok.com`, `vm.tiktok.com`) are short-link and mobile
# routes that redirect into the same canonical `/@handle` path, so they
# are accepted as INPUT and normalised, never emitted.
CANONICAL_HOST = "www.tiktok.com"
ACCEPTED_HOSTS = ("www.tiktok.com", "tiktok.com", "m.tiktok.com", "vm.tiktok.com")

# Hosts that ARE TikTok and are not this repo's job. Refusing them with
# "is not on a TikTok host" would be false, and CLAUDE.md §5 is explicit
# that a false refusal sends the reader looking for a typo that is not
# there. Named separately because the host check runs before the path
# check, so putting the explanation only in the path branch left it
# unreachable — a dead branch that reads like a feature.
SIBLING_HOSTS = {
    "shop.tiktok.com": "a TikTok Shop page — see tiktok-shop-scraper",
    "seller.tiktok.com": "the TikTok Shop seller centre, which needs an account",
    "ads.tiktok.com": "TikTok's ads and Creative Center, which needs an account",
    "library.tiktok.com": "TikTok's Ad Library, which this family does not read yet",
}

# A handle as TikTok itself allows it: letters, digits, underscore and dot,
# 1-24 characters. Anchored on the URL, which is a contract with search
# engines, rather than on any class in the rendered page (CLAUDE.md §4).
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,24}$")
_PROFILE_PATH_RE = re.compile(r"^/@([A-Za-z0-9._]{1,24})/?$")

# The scope key the main webapp files a profile under.
USER_DETAIL_SCOPE = "webapp.user-detail"


class NotAProfileUrl(ValueError):
    """The URL is a TikTok URL, but not a profile one.

    Refused WITH THE REASON. CLAUDE.md §5: "is not a TikTok site" is false
    for `https://www.tiktok.com/tag/nasa` and sends the reader looking for
    a typo that is not there.
    """


def normalise_handle(raw: str) -> str:
    """'@NASA', 'nasa', a full profile URL -> 'nasa'."""
    s = (raw or "").strip()
    if not s:
        raise NotAProfileUrl("empty handle")
    if "://" in s or s.startswith("www.") or s.startswith("tiktok.com"):
        return handle_from_url(s)
    s = s.lstrip("@")
    if not _HANDLE_RE.match(s):
        raise NotAProfileUrl(
            f"{raw!r} is not a TikTok handle: TikTok allows letters, digits, "
            "underscore and dot, up to 24 characters"
        )
    return s


def handle_from_url(url: str) -> str:
    """Pull the handle out of a profile URL, or say why the URL is not one."""
    s = (url or "").strip()
    if "://" not in s:
        s = "https://" + s
    parts = urlsplit(s)
    host = (parts.netloc or "").lower().split(":")[0]
    if host in SIBLING_HOSTS:
        raise NotAProfileUrl(f"{url!r} is {SIBLING_HOSTS[host]}")
    if host not in ACCEPTED_HOSTS:
        raise NotAProfileUrl(
            f"{url!r} is not on a TikTok host (got {host!r}); "
            f"this scraper reads {', '.join(ACCEPTED_HOSTS)}"
        )
    m = _PROFILE_PATH_RE.match(parts.path or "/")
    if not m:
        # Name what the path IS, so the reader is not sent hunting for a
        # typo in a perfectly good URL.
        path = parts.path or "/"
        if path.startswith("/tag/"):
            kind = "a hashtag feed"
        elif path.startswith("/search"):
            kind = "a search results page"
        elif path.startswith("/shop"):
            # `shop.tiktok.com` never reaches here — SIBLING_HOSTS catches it
            # in the host check above. This branch is for the shop routes
            # served under the main host.
            kind = "a TikTok Shop page — see tiktok-shop-scraper"
        elif "/video/" in path:
            kind = "a single video page — see tiktok-video-scraper"
        elif path in ("/", "/explore", "/foryou"):
            kind = "a TikTok feed page, not an account"
        else:
            kind = "not a profile path"
        raise NotAProfileUrl(
            f"{url!r} is {kind}; this scraper reads profile pages of the "
            "form https://www.tiktok.com/@handle"
        )
    return m.group(1)


def profile_url(handle: str) -> str:
    """The canonical profile URL for a handle."""
    return f"https://{CANONICAL_HOST}/@{normalise_handle(handle)}"


def page_url(url: str, page: int) -> str:
    """There is no page 2 of a profile — and saying so is the point.

    CLAUDE.md §7 wants pagination that never depends solely on selectors,
    and §18 wants "is this listing addressable?" asked per URL before any
    page URL is planned. On a TikTok profile the answer is no, twice over:
    the page states one account, and the video feed that WOULD paginate is
    the refused route this repo does not use. So `--pages` is rejected
    above 1 by the engines rather than quietly fetching the same page N
    times and reporting a complete run of duplicates.
    """
    if page == 1:
        return url
    raise NotAProfileUrl(
        "a TikTok profile has exactly one page; --pages above 1 is refused "
        "rather than silently refetching the same account"
    )


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------
#
# The names TikTok uses, mapped to the names this family's schema uses.
# `heart` and `heartCount` are the same number in every capture measured;
# `heartCount` is the one both objects always carry.
_STAT_KEYS = (
    "followerCount",
    "followingCount",
    "heartCount",
    "videoCount",
    "friendCount",
    "diggCount",
)


def _ts_to_iso(value: Any) -> Optional[str]:
    """A unix second count to an ISO-8601 instant in UTC, or None.

    Zero means "not set" on every one of these fields — an account whose
    nickname has never been changed carries `nickNameModifyTime: 0` — so
    it must not become 1970-01-01. CLAUDE.md §21: a numeric field whose
    absent state is 0 rather than null needs the absence recovered.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if value <= 0:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _clean_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s or None


def _bool(value: Any) -> Optional[bool]:
    """TikTok spells booleans three ways: true, 1, and "1"."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return value.strip() == "1"
    return None


def _first_bio_link(user: Dict[str, Any]) -> Optional[str]:
    link = user.get("bioLink")
    if isinstance(link, dict):
        return _clean_text(link.get("link"))
    if isinstance(link, str):
        return _clean_text(link)
    return None


# The avatar CDN path carries a stable content id between the last "/" and
# the "~" that introduces TikTok's image transform. Anchored on THAT
# STRUCTURE — the separator the CDN itself uses — rather than on a fixed
# path prefix (the bucket name varies: `tos-maliva-avt-0068` on some
# accounts, `tos-alisg-avt-0068` on others) and rather than on a character
# class.
#
# The character class is the part that was wrong first, and the canary is
# what caught it. Twelve accounts in a row carried a bare 32-hex id, so a
# `[0-9a-f]{16,64}` pattern looked correct and was measured correct. The
# thirteenth — @zachking — carries `smgf5f369c884044a8df770614bbfd64717`,
# with a three-letter prefix, and produced a null `avatar_id` while every
# other column looked healthy. CLAUDE.md §4's rule again: anchor on the
# site's own structural contract, never on the shape today's sample
# happens to have.
_AVATAR_ID_RE = re.compile(r"/([^/?#]+)~tplv")


def _avatar_parts(url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(stable id, expiry as ISO) for a signed avatar URL."""
    if not url:
        return None, None
    m = _AVATAR_ID_RE.search(url)
    avatar_id = m.group(1) if m else None
    expires = None
    try:
        q = parse_qs(urlsplit(url).query)
        raw = (q.get("x-expires") or [None])[0]
        if raw and raw.isdigit():
            expires = _ts_to_iso(int(raw))
    except ValueError:
        expires = None
    return avatar_id, expires


def parse_profile(html: Any, url: str, scraped_at: str,
                  row_cls: Any) -> Tuple[List[Any], Dict[str, Any]]:
    """One profile page to (rows, diagnostics).

    Returns AT MOST one row, and zero rows when the site says the account
    is unavailable — with `status` in the diagnostics saying which, so an
    engine can tell "this handle has no account" from "this parser broke".
    CLAUDE.md §20: a page that was served and parses to nothing is
    reported as its own thing, never as an empty result.
    """
    scope = rehydration_scope(html)
    detail = scope.get(USER_DETAIL_SCOPE)
    diag: Dict[str, Any] = {"scope_present": detail is not None}

    if detail is None:
        # The page rendered, the payload is there, and the scope this repo
        # reads is absent. That is a page kind this parser does not handle
        # — a tag feed, a search page — not an empty account.
        diag["status"] = USER_STATUS_UNKNOWN
        diag["scopes"] = sorted(k for k in scope if "i18n" not in k)
        raise PayloadError(
            f"page carried no {USER_DETAIL_SCOPE!r} scope; it is not a profile "
            f"page (scopes present: {diag['scopes']})"
        )

    status, code, msg = user_status(detail)
    diag.update({"status": status, "status_code": code, "status_msg": msg})
    if status != USER_STATUS_OK:
        return [], diag

    info = detail["userInfo"]
    user = info.get("user") or {}
    values, stats_source = counts(info, _STAT_KEYS)
    diag["stats_source"] = stats_source

    handle = _clean_text(user.get("uniqueId"))
    followers = values.get("followerCount")
    videos = values.get("videoCount")
    hearts = values.get("heartCount")

    # Arithmetic on two numbers the site published, not a score of our own
    # invention. Null rather than zero when the denominator is zero, because
    # "no videos" is not "zero likes per video".
    likes_per_video = None
    if hearts is not None and videos:
        likes_per_video = round(hearts / videos, 2)

    avatar_url = _clean_text(user.get("avatarLarger") or user.get("avatarMedium"))
    avatar_id, avatar_expires = _avatar_parts(avatar_url)

    profile_tab = user.get("profileTab") or {}
    commerce = user.get("commerceUserInfo") or {}

    row = row_cls(
        source=SOURCE,
        scraped_at=scraped_at,
        url=profile_url(handle) if handle else url,
        sku=_clean_text(user.get("id")),
        title=_clean_text(user.get("nickname")),

        username=handle,
        user_id=_clean_text(user.get("id")),
        sec_uid=_clean_text(user.get("secUid")),

        follower_count=followers,
        following_count=values.get("followingCount"),
        likes_count=hearts,
        video_count=videos,
        friend_count=values.get("friendCount"),
        digg_count=values.get("diggCount"),
        likes_per_video=likes_per_video,
        stats_source=stats_source,

        verified=_bool(user.get("verified")),
        private_account=_bool(user.get("privateAccount")),
        is_organization=_bool(user.get("isOrganization")),
        is_seller=_bool(user.get("ttSeller")),
        commerce_user=_bool(commerce.get("commerceUser")),
        secret=_bool(user.get("secret")),

        bio=_clean_text(user.get("signature")),
        bio_link=_first_bio_link(user),
        avatar_url=avatar_url,
        avatar_id=avatar_id,
        avatar_expires_at=avatar_expires,
        language=_clean_text(user.get("language")),

        created_at=_ts_to_iso(user.get("createTime")),
        nickname_modified_at=_ts_to_iso(user.get("nickNameModifyTime")),

        comment_setting=user.get("commentSetting"),
        duet_setting=user.get("duetSetting"),
        stitch_setting=user.get("stitchSetting"),
        download_setting=user.get("downloadSetting"),
        following_visibility=user.get("followingVisibility"),
        open_favorite=_bool(user.get("openFavorite")),
        show_playlist_tab=_bool(profile_tab.get("showPlayListTab")),

        status=status,
        status_code=code,
        page=1,
        position=1,
    )
    return [row], diag


# ---------------------------------------------------------------------------
# Refusal detection
# ---------------------------------------------------------------------------
#
# Positive-asset detection, the trick CLAUDE.md §8 records from another
# site and §18 proves against a case it was not designed for (Chromium's
# own network-error page, which carries the site's hostname in its title
# and no vendor marker at all).
#
# Counted 2026-09-22 across every capture in this repo: a page TikTok
# actually serves references its own static host at least twice; the shop
# challenge page references it zero times. The threshold is 2 rather than
# 1 because §17's classification-order trap is exactly this — a minimal
# real page with one reference must not read as blocked.
SITE_ASSET_MARKERS = ("ttwstatic.com", "tiktokcdn.com", "tiktokcdn-eu.com")
MIN_ASSET_REFERENCES = 2


def asset_reference_count(html: Any) -> int:
    text = decode_page(html)
    return sum(text.count(m) for m in SITE_ASSET_MARKERS)


def challenge_markers_present(html: Any) -> List[str]:
    """Which challenge markers a page carries, in the order they are listed.

    Returns a LIST rather than a bool so a caller can say which marker
    fired, which is the difference between a log a reader can act on and
    one that says "blocked".
    """
    text = decode_page(html)
    return [m for m in BOT_CHALLENGE_MARKERS if m in text]


# ---------------------------------------------------------------------------
# Page states
# ---------------------------------------------------------------------------

STATE_CONTENT = "content"
# The account does not exist, or is banned. TikTok gives one answer for
# both and this repo does not claim to tell them apart.
STATE_USER_UNAVAILABLE = "user_unavailable"
# TikTok's zero-byte HTTP 200. Its own kind, because it is a REFUSAL that
# carries no status, no body and no marker — and because calling it
# "empty" would make a refused run report an account with no data.
STATE_EMPTY_SUCCESS = "empty_success"
STATE_CHALLENGE = "challenge"
STATE_ERROR = "error"
# A page the site plainly served, with the scope this repo reads on it,
# that parsed to zero rows. OUR bug, and it gets its own name so it cannot
# be reported as "no such account" — which would send the reader to check
# the handle instead of the parser (CLAUDE.md §20).
STATE_PARSE_ERROR = "parse_error"
STATE_UNKNOWN = "unknown"


def detect_page_state(html: Any, status: Optional[int] = None,
                      url: str = "") -> str:
    """Name what TikTok answered with.

    The argument ORDER is the contract: every caller writes
    `detect_page_state(html, status, url)`. CLAUDE.md §17 records a repo
    whose engines called a classifier with `status` in the wrong place and
    crashed on their FIRST fetch, invisible to import, `--help` and four
    hundred green assertions. `smoke_test.py` binds every call site against
    this signature for exactly that reason.

    The ORDER OF THE CHECKS is also deliberate, and CLAUDE.md §17's
    classification-order trap is the reason: signals are ordered by how
    much they PROVE, not by how cheap they are. An unambiguous positive —
    the site's own payload, saying in its own field what it did — outranks
    any threshold.
    """
    # 1. The zero-byte 200. Nothing else can be concluded from a body that
    #    is not there, and it must be checked before anything that tries to
    #    parse.
    if is_empty_success(status, html):
        return STATE_EMPTY_SUCCESS

    text = decode_page(html)

    # 2. A status the site gave us. A refusal that states itself is worth
    #    more than any inference from the body.
    if status is not None and status >= 400:
        return STATE_ERROR

    # 3. The challenge widget's own markers. Specific to the widget, and
    #    measured zero on every served capture in this repo.
    if challenge_markers_present(text):
        return STATE_CHALLENGE

    # 4. The payload's own verdict — the strongest signal available,
    #    because it is TikTok stating the outcome rather than us guessing
    #    from markup.
    try:
        scope = rehydration_scope(text)
    except PayloadError:
        scope = None

    if scope is not None:
        detail = scope.get(USER_DETAIL_SCOPE)
        if detail is not None:
            status_name, _, _ = user_status(detail)
            if status_name == USER_STATUS_OK:
                return STATE_CONTENT
            if status_name == USER_STATUS_UNAVAILABLE:
                return STATE_USER_UNAVAILABLE
        # A rehydration payload with no user-detail scope is a TikTok page
        # of some other kind. Not a refusal and not an account.
        return STATE_UNKNOWN

    # 5. Only now, the threshold. A page with no payload that is
    #    nevertheless built out of TikTok's own assets is a TikTok page
    #    this parser did not understand; one that is not, is somebody
    #    else's page — a proxy's error, Chromium's own network-error page
    #    (which carries the site's hostname in its title and would fool a
    #    title check), an upstream gateway.
    if asset_reference_count(text) >= MIN_ASSET_REFERENCES:
        return STATE_PARSE_ERROR
    return STATE_UNKNOWN
