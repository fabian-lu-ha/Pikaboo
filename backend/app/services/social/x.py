"""Public X (Twitter) profile fetcher — best-effort.

X aggressively walls public timelines behind login + Cloudflare in 2026, and the
free API tier is read-rate-limited into uselessness. The two surfaces that still
serve unauthenticated public-profile data without a paid scraping service are:

  1. The legacy embeddable-timeline endpoint that powers Twitter's official
     "embed a timeline on your blog" widget:
         https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>
     It server-renders a Next.js page and inlines the full timeline JSON
     (up to ~100 tweets) inside `<script id="__NEXT_DATA__">`. Unauthenticated,
     no Cloudflare challenge, no per-call cookies needed. This is the cleanest
     source — full text, media, like counts, ISO-able timestamps, permalinks.
     Failure mode: per-IP 429 if hammered.

  2. xcancel.com — the most actively-maintained Nitter fork as of 2026.
     Static HTML, parsable with selectolax. Used as fallback when (1) returns
     429 / empty JSON / shape change.

The first-party x.com path is intentionally NOT attempted as a primary —
headless Chromium hits the login wall on a cold context and gives nothing
useful most of the time. We do keep a thin Playwright "scrape rendered
syndication page" fallback for the rare case where httpx is geo-blocked but
the browser pool's residential-feeling fingerprint isn't.

Strategy order:
  1. httpx GET syndication endpoint, parse __NEXT_DATA__ JSON.
  2. httpx GET xcancel.com/<handle>, parse HTML.
  3. Playwright load syndication endpoint inside browser, parse __NEXT_DATA__.
  4. Return [] with a warning log.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from selectolax.parser import HTMLParser

from app.services.enrichment.browser import get_browser
from app.services.social import Post

log = logging.getLogger(__name__)

PLATFORM = "x"
MAX_POSTS = 5
CAPTION_LIMIT = 500

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 900}
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"\s+type="application/json"[^>]*>(.+?)</script>',
    re.DOTALL,
)
# Things we should never treat as a handle when stripped from the path.
_NON_HANDLES = {
    "i", "home", "explore", "search", "notifications", "messages",
    "compose", "intent", "share", "settings", "tos", "privacy", "about",
    "login", "logout", "signup", "hashtag", "topics", "lists",
    "communities", "bookmarks",
}


# ──────────────────────────────────────────────────────────────────────────────
# URL / handle parsing
# ──────────────────────────────────────────────────────────────────────────────
def _extract_handle(profile_url: str) -> str | None:
    """Pull the handle out of any reasonable X/Twitter URL or bare handle.

    Accepts: `x.com/foo`, `https://twitter.com/foo`, `@foo`, `foo`,
    `https://www.x.com/foo/with_replies`, `mobile.twitter.com/foo`, etc.
    """
    if not profile_url:
        return None
    s = profile_url.strip()
    if not s:
        return None

    # Bare handle ("foo" or "@foo") — no scheme, no slashes, no dots.
    if "/" not in s and "." not in s:
        cand = s.lstrip("@")
        return cand if _HANDLE_RE.match(cand) else None

    if not s.startswith(("http://", "https://")):
        s = "https://" + s

    try:
        parsed = urlparse(s)
    except ValueError:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    first = parts[0].lstrip("@")
    if first.lower() in _NON_HANDLES:
        return None
    return first if _HANDLE_RE.match(first) else None


# ──────────────────────────────────────────────────────────────────────────────
# Common helpers
# ──────────────────────────────────────────────────────────────────────────────
def _truncate(text: str | None) -> str:
    if not text:
        return ""
    text = html_lib.unescape(text).strip()
    if len(text) <= CAPTION_LIMIT:
        return text
    return text[: CAPTION_LIMIT - 1].rstrip() + "…"


def _parse_twitter_date(s: str | None) -> str | None:
    """Convert Twitter's `created_at` string to ISO-8601 UTC."""
    if not s:
        return None
    # Twitter format: "Sat Apr 25 03:34:43 +0000 2026"
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None
    return dt.isoformat().replace("+00:00", "Z")


def _strip_int(s: str | None) -> int | None:
    """Parse '7,438' / '11.2M' / '1.1K' into an int. Returns None on failure."""
    if not s:
        return None
    s = s.strip().replace(",", "")
    if not s:
        return None
    mult = 1
    if s[-1] in ("K", "k"):
        mult, s = 1_000, s[:-1]
    elif s[-1] in ("M", "m"):
        mult, s = 1_000_000, s[:-1]
    elif s[-1] in ("B", "b"):
        mult, s = 1_000_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except (TypeError, ValueError):
        return None


def _tweet_url(handle: str, tweet_id: str) -> str:
    return f"https://x.com/{handle}/status/{tweet_id}"


# ──────────────────────────────────────────────────────────────────────────────
# Strategy 1 + 3: syndication.twitter.com __NEXT_DATA__
# ──────────────────────────────────────────────────────────────────────────────
def _syndication_url(handle: str) -> str:
    # `dnt=true` lowers tracking/personalization weight, `suppress_response_codes=true`
    # asks the upstream not to swap a 429 into an HTML error page (it returns
    # 200 with an error JSON instead — easier to detect).
    return (
        "https://syndication.twitter.com/srv/timeline-profile/"
        f"screen-name/{handle}"
        "?dnt=true&suppress_response_codes=true"
    )


def _parse_syndication_html(html: str, handle: str) -> list[Post]:
    """Extract tweets from a syndication-profile page's __NEXT_DATA__."""
    if not html:
        return []
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    timeline = (
        ((blob or {}).get("props") or {})
        .get("pageProps", {})
        .get("timeline")
    )
    if not isinstance(timeline, dict):
        return []
    entries = timeline.get("entries") or []
    if not isinstance(entries, list) or not entries:
        return []

    # Twitter Snowflake IDs encode time → numeric desc gives true chronological
    # order even when the timeline pins a tweet to position 0.
    def _id_key(e: Any) -> int:
        try:
            t = (e or {}).get("content", {}).get("tweet", {}) or {}
            return int(t.get("id_str") or 0)
        except (TypeError, ValueError):
            return 0

    ordered = sorted(entries, key=_id_key, reverse=True)

    posts: list[Post] = []
    seen: set[str] = set()
    for entry in ordered:
        tweet = ((entry or {}).get("content") or {}).get("tweet") or {}
        if not isinstance(tweet, dict):
            continue
        tid = tweet.get("id_str") or str(tweet.get("id") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)

        # Owner's screen_name beats the URL handle in case casing differs.
        screen = (tweet.get("user") or {}).get("screen_name") or handle

        media_urls: list[str] = []
        ext = tweet.get("extended_entities") or {}
        for m_ in ext.get("media") or []:
            if not isinstance(m_, dict):
                continue
            url = m_.get("media_url_https") or m_.get("media_url")
            if isinstance(url, str) and url.startswith("http"):
                media_urls.append(url)

        likes = tweet.get("favorite_count")
        if not isinstance(likes, int):
            likes = None

        posts.append(
            Post(
                platform=PLATFORM,
                caption=_truncate(tweet.get("full_text") or tweet.get("text")),
                media_urls=media_urls,
                posted_at=_parse_twitter_date(tweet.get("created_at")),
                url=_tweet_url(screen, tid),
                likes=likes,
            )
        )
        if len(posts) >= MAX_POSTS:
            break
    return posts


async def _fetch_syndication_httpx(handle: str) -> list[Post]:
    """Strategy 1: bare httpx GET — the cheap, fast happy path."""
    url = _syndication_url(handle)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            headers={
                "user-agent": _USER_AGENT,
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
    except (httpx.HTTPError, OSError) as e:
        log.warning("x syndication httpx GET %s failed: %s", handle, e)
        return []

    if resp.status_code != 200:
        log.warning("x syndication httpx %s -> HTTP %s", handle, resp.status_code)
        return []
    return _parse_syndication_html(resp.text, handle)


async def _fetch_syndication_playwright(handle: str) -> list[Post]:
    """Strategy 3: same endpoint but inside the browser pool.

    Useful when our outbound IP is being 429'd but the browser pool's TLS
    fingerprint / cookie jar is fresher.
    """
    try:
        browser = get_browser()
    except RuntimeError as e:
        log.warning("x syndication playwright: browser unavailable: %s", e)
        return []

    context = None
    try:
        context = await browser.new_context(
            viewport=_VIEWPORT,
            user_agent=_USER_AGENT,
            locale="en-US",
        )
        url = _syndication_url(handle)
        try:
            resp = await context.request.get(url, timeout=15_000)
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            log.warning("x syndication playwright %s failed: %s", handle, e)
            return []
        if resp.status != 200:
            log.warning("x syndication playwright %s -> HTTP %s", handle, resp.status)
            return []
        try:
            body = await resp.text()
        except (PlaywrightError, PlaywrightTimeoutError):
            return []
        return _parse_syndication_html(body, handle)
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Strategy 2: xcancel.com (Nitter fork) HTML
# ──────────────────────────────────────────────────────────────────────────────
_XCANCEL_DATE_RE = re.compile(
    r"^([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s*·\s*(\d{1,2}:\d{2})\s*([AP]M)\s*UTC$"
)
_PERMALINK_RE = re.compile(r"^/([A-Za-z0-9_]+)/status/(\d+)")


def _xcancel_parse_date(title: str | None) -> str | None:
    """Parse Nitter's tweet-date `title` attribute → ISO-8601 UTC."""
    if not title:
        return None
    m = _XCANCEL_DATE_RE.match(title.strip())
    if not m:
        return None
    date_part, time_part, ampm = m.groups()
    try:
        dt = datetime.strptime(
            f"{date_part} {time_part} {ampm}", "%b %d, %Y %I:%M %p"
        )
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_xcancel_html(html: str, handle: str) -> list[Post]:
    if not html:
        return []
    try:
        dom = HTMLParser(html)
    except Exception:
        return []

    posts: list[Post] = []
    seen: set[str] = set()
    for item in dom.css("div.timeline-item"):
        # Permalink — first <a class="tweet-link"> carries /<user>/status/<id>.
        link = item.css_first("a.tweet-link")
        href = link.attributes.get("href", "") if link else ""
        m = _PERMALINK_RE.match(href or "")
        if not m:
            continue
        screen, tid = m.group(1), m.group(2)
        if tid in seen:
            continue
        seen.add(tid)

        # Caption.
        body = item.css_first("div.tweet-content")
        caption = body.text(separator="\n") if body else ""

        # Date — title attr on <a> inside <span class="tweet-date">.
        date_node = item.css_first("span.tweet-date a")
        posted_at = _xcancel_parse_date(
            date_node.attributes.get("title") if date_node else None
        )

        # Media — gallery images, video posters, attachment images.
        media_urls: list[str] = []
        for sel, attr in (
            ("div.attachments img", "src"),
            ("div.attachments video", "poster"),
            ("div.gallery-row img", "src"),
        ):
            for n in item.css(sel):
                u = n.attributes.get(attr)
                if isinstance(u, str) and u.startswith("http") and u not in media_urls:
                    media_urls.append(u)

        # Stats — 4 spans in `.tweet-stats`: comment, retweet, heart, views.
        likes: int | None = None
        for stat in item.css("span.tweet-stat"):
            txt = stat.text(separator=" ").strip()
            ic = stat.css_first("span.icon-heart")
            if ic is not None:
                # Strip whitespace + the icon text content; what remains is the count.
                likes = _strip_int(txt)
                break

        posts.append(
            Post(
                platform=PLATFORM,
                caption=_truncate(caption),
                media_urls=media_urls,
                posted_at=posted_at,
                url=_tweet_url(screen or handle, tid),
                likes=likes,
            )
        )
        if len(posts) >= MAX_POSTS:
            break
    return posts


async def _fetch_xcancel(handle: str) -> list[Post]:
    """Strategy 2: xcancel.com static HTML."""
    url = f"https://xcancel.com/{handle}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=True,
            headers={
                "user-agent": _USER_AGENT,
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
    except (httpx.HTTPError, OSError) as e:
        log.warning("x xcancel GET %s failed: %s", handle, e)
        return []

    if resp.status_code != 200:
        log.warning("x xcancel %s -> HTTP %s", handle, resp.status_code)
        return []

    text = resp.text
    # xcancel returns a "Browser verification" interstitial occasionally.
    lowered = text[:4000].lower() if text else ""
    if ("browser verification" in lowered) or (
        "cloudflare" in lowered and "challenge" in lowered
    ):
        log.warning("x xcancel %s: anti-bot interstitial", handle)
        return []
    return _parse_xcancel_html(text, handle)


# ──────────────────────────────────────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────────────────────────────────────
async def fetch(profile_url: str) -> list[Post]:
    """Fetch up to 5 most recent public posts for an X (Twitter) profile.

    Best-effort: returns [] on any failure. Never raises.
    """
    handle = _extract_handle(profile_url)
    if not handle:
        log.warning("x fetch: could not extract handle from %r", profile_url)
        return []

    try:
        # 1. Cheap, fast: bare httpx hit on the syndication endpoint.
        posts = await _fetch_syndication_httpx(handle)
        if posts:
            return posts[:MAX_POSTS]

        # 2. Fallback: xcancel.com Nitter mirror.
        posts = await _fetch_xcancel(handle)
        if posts:
            return posts[:MAX_POSTS]

        # 3. Last resort: re-try syndication via the browser pool's egress.
        posts = await _fetch_syndication_playwright(handle)
        if posts:
            return posts[:MAX_POSTS]

        log.warning("x fetch: no posts extractable for @%s", handle)
        return []
    except Exception as e:  # final safety net — best-effort means never raise.
        log.warning("x fetch failed for %s: %s", profile_url, e)
        return []
