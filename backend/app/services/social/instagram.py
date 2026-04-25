"""Instagram public-profile fetcher.

Best-effort: Instagram aggressively walls public data behind login prompts and
rotates its embedded data shapes every few weeks, so this module tries several
strategies and returns whatever it can reach. On any failure (anti-bot wall,
empty data, JSON shape change) it returns an empty list and logs a warning.

Strategies, in order:
  1. Hit `/api/v1/users/web_profile_info/?username=<handle>` from inside a
     Playwright browser context (so we inherit a real fingerprint + the
     `_ig_did` / `csrftoken` cookies the page sets) with the public web
     `x-ig-app-id: 936619743392459` header. Returns the cleanest JSON when it
     works; usually the first thing IG shuts down for a given IP.
  2. Render the profile page, sniff every `<script type="application/json">`
     and `<script type="application/ld+json">` blob for the
     `edge_owner_to_timeline_media` / `xdt_api__v1__feed__user_timeline`
     payloads that ship inline.
  3. DOM fallback: walk anchors matching `/p/<shortcode>/` and `/reel/<sc>/`
     and grab the thumbnail `<img src>` + alt text.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.enrichment.browser import get_browser
from app.services.social import Post

log = logging.getLogger(__name__)

PLATFORM = "instagram"
MAX_POSTS = 5
CAPTION_LIMIT = 500

_IG_APP_ID = "936619743392459"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 900}

# Anchor pattern for post URLs in the profile grid.
_POST_HREF_RE = re.compile(r"^/(p|reel|tv)/([A-Za-z0-9_-]+)/?")
_SHORTCODE_RE = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def _extract_handle(profile_url: str) -> str | None:
    if not profile_url:
        return None
    s = profile_url.strip().lstrip("@")
    if not s:
        return None

    # Bare handle.
    if "/" not in s and "." not in s:
        return s or None

    if not s.startswith(("http://", "https://")):
        s = "https://" + s

    try:
        parsed = urlparse(s)
    except ValueError:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    # `/explore/`, `/reel/`, `/p/` etc. are not handles.
    skip = {"explore", "reel", "reels", "p", "tv", "stories", "accounts", "direct"}
    first = parts[0].lstrip("@")
    if first.lower() in skip:
        return None
    return first or None


def _truncate_caption(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= CAPTION_LIMIT:
        return text
    return text[: CAPTION_LIMIT - 1].rstrip() + "…"


def _iso_from_epoch(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    # Mirror datetime.utcfromtimestamp without importing it to keep the file lean.
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _post_url(shortcode: str, kind: str = "p") -> str:
    return f"https://www.instagram.com/{kind}/{shortcode}/"


def _node_to_post(node: dict[str, Any]) -> Post | None:
    """Convert a single timeline media node (web_profile_info shape) into Post."""
    shortcode = node.get("shortcode") or node.get("code")
    if not shortcode:
        return None

    # Caption — sits at edge_media_to_caption.edges[0].node.text.
    caption = ""
    cap_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    if cap_edges:
        caption = (cap_edges[0].get("node") or {}).get("text") or ""
    if not caption:
        caption = node.get("accessibility_caption") or ""

    # Media URLs — display_url is the primary; carousel posts have edge_sidecar_to_children.
    media_urls: list[str] = []
    display = node.get("display_url")
    if display:
        media_urls.append(display)
    sidecar_edges = (node.get("edge_sidecar_to_children") or {}).get("edges") or []
    for e in sidecar_edges:
        n = e.get("node") or {}
        u = n.get("display_url")
        if u and u not in media_urls:
            media_urls.append(u)
    if not media_urls and node.get("thumbnail_src"):
        media_urls.append(node["thumbnail_src"])

    # Likes — `edge_liked_by.count` for full responses, `edge_media_preview_like.count` for previews.
    likes = None
    for key in ("edge_liked_by", "edge_media_preview_like"):
        v = node.get(key)
        if isinstance(v, dict) and isinstance(v.get("count"), int):
            likes = v["count"]
            break

    posted_at = _iso_from_epoch(node.get("taken_at_timestamp") or node.get("taken_at"))

    is_video = bool(node.get("is_video"))
    kind = "reel" if is_video and (node.get("product_type") in ("clips", "igtv")) else "p"

    return Post(
        platform=PLATFORM,
        caption=_truncate_caption(caption),
        media_urls=media_urls,
        posted_at=posted_at,
        url=_post_url(shortcode, kind=kind),
        likes=likes,
    )


def _walk_for_timeline(obj: Any) -> list[dict[str, Any]]:
    """Walk an arbitrary nested dict/list looking for a timeline-media edges array.

    Instagram has shipped this payload under several keys over the years:
      - `edge_owner_to_timeline_media.edges` (legacy GraphQL / web_profile_info)
      - `xdt_api__v1__feed__user_timeline_graphql_connection.edges` (2024+ PolarisFeedPage)
    Both wrap a list of `{"node": {...}}`; we collect the first such list we find.
    """
    if isinstance(obj, dict):
        for key in (
            "edge_owner_to_timeline_media",
            "xdt_api__v1__feed__user_timeline_graphql_connection",
            "user_timeline_graphql_connection",
        ):
            v = obj.get(key)
            if isinstance(v, dict):
                edges = v.get("edges")
                if isinstance(edges, list) and edges:
                    nodes = [e.get("node") for e in edges if isinstance(e, dict)]
                    nodes = [n for n in nodes if isinstance(n, dict)]
                    if nodes:
                        return nodes
        for v in obj.values():
            found = _walk_for_timeline(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _walk_for_timeline(v)
            if found:
                return found
    return []


async def _try_web_profile_info(context, handle: str) -> list[Post]:
    """Strategy 1: hit the web_profile_info JSON endpoint from the browser context."""
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}"
    try:
        # `request` rides on the browser context's cookies + TLS fingerprint.
        resp = await context.request.get(
            url,
            headers={
                "x-ig-app-id": _IG_APP_ID,
                "accept": "*/*",
                "x-requested-with": "XMLHttpRequest",
                "sec-fetch-site": "same-origin",
                "referer": f"https://www.instagram.com/{handle}/",
            },
            timeout=12_000,
        )
    except (PlaywrightError, PlaywrightTimeoutError) as e:
        log.warning("instagram web_profile_info request failed for %s: %s", handle, e)
        return []

    if resp.status != 200:
        log.warning(
            "instagram web_profile_info %s -> HTTP %s", handle, resp.status
        )
        return []

    try:
        data = await resp.json()
    except Exception as e:
        log.warning("instagram web_profile_info %s: bad json: %s", handle, e)
        return []

    nodes = _walk_for_timeline(data)
    posts: list[Post] = []
    for n in nodes[:MAX_POSTS]:
        p = _node_to_post(n)
        if p:
            posts.append(p)
    return posts


async def _try_inline_json(page) -> list[Post]:
    """Strategy 2: scan the rendered HTML for embedded JSON payloads."""
    try:
        scripts = await page.eval_on_selector_all(
            "script[type='application/json'], script[type='application/ld+json']",
            "els => els.map(e => e.textContent || '')",
        )
    except (PlaywrightError, PlaywrightTimeoutError):
        return []

    for raw in scripts:
        if not raw or "edge_owner_to_timeline_media" not in raw and "xdt_api__v1__feed__user_timeline" not in raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes = _walk_for_timeline(data)
        if nodes:
            posts: list[Post] = []
            for n in nodes[:MAX_POSTS]:
                p = _node_to_post(n)
                if p:
                    posts.append(p)
            if posts:
                return posts
    return []


async def _try_dom_grid(page) -> list[Post]:
    """Strategy 3: walk the post-grid anchors as a last resort.

    Captions are not available without an extra request per post; we fall back
    to the thumbnail's alt text (which Instagram autogenerates and includes the
    caption snippet on most posts).
    """
    try:
        anchors = await page.eval_on_selector_all(
            "a[href*='/p/'], a[href*='/reel/'], a[href*='/tv/']",
            """els => els.map(a => {
                const img = a.querySelector('img');
                return {
                    href: a.getAttribute('href') || '',
                    src: img ? (img.getAttribute('src') || '') : '',
                    alt: img ? (img.getAttribute('alt') || '') : '',
                };
            })""",
        )
    except (PlaywrightError, PlaywrightTimeoutError):
        return []

    seen: set[str] = set()
    posts: list[Post] = []
    for a in anchors:
        href = a.get("href") or ""
        m = _POST_HREF_RE.match(href)
        if not m:
            continue
        kind, shortcode = m.group(1), m.group(2)
        if shortcode in seen:
            continue
        seen.add(shortcode)
        media = [a["src"]] if a.get("src") else []
        posts.append(
            Post(
                platform=PLATFORM,
                caption=_truncate_caption(a.get("alt") or ""),
                media_urls=media,
                posted_at=None,
                url=_post_url(shortcode, kind=kind),
                likes=None,
            )
        )
        if len(posts) >= MAX_POSTS:
            break
    return posts


def _looks_like_login_wall(html: str) -> bool:
    if not html:
        return True
    lowered = html.lower()
    # Heuristics: very short HTML, or login-only markers without the profile JSON keys.
    if len(lowered) < 2_000:
        return True
    return (
        "login" in lowered
        and "edge_owner_to_timeline_media" not in lowered
        and "xdt_api__v1__feed__user_timeline" not in lowered
        and 'href="/p/' not in lowered
        and 'href="/reel/' not in lowered
    )


async def fetch(profile_url: str) -> list[Post]:
    handle = _extract_handle(profile_url)
    if not handle:
        log.warning("instagram fetch: could not extract handle from %r", profile_url)
        return []

    try:
        browser = get_browser()
    except RuntimeError as e:
        log.warning("instagram fetch: browser pool not available: %s", e)
        return []

    context = None
    try:
        context = await browser.new_context(
            viewport=_VIEWPORT,
            user_agent=_USER_AGENT,
            locale="en-US",
            extra_http_headers={
                "accept-language": "en-US,en;q=0.9",
            },
        )
        page = await context.new_page()

        profile_url_full = f"https://www.instagram.com/{handle}/"
        try:
            await page.goto(profile_url_full, wait_until="domcontentloaded", timeout=20_000)
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            log.warning("instagram goto %s failed: %s", profile_url_full, e)
            return []

        # Let post grid lazy-load; absorb any pop-ups silently.
        try:
            await page.wait_for_load_state("networkidle", timeout=8_000)
        except PlaywrightTimeoutError:
            pass

        # Strategy 1 — JSON endpoint, cookies set by the page above.
        posts = await _try_web_profile_info(context, handle)
        if posts:
            return posts[:MAX_POSTS]

        # Strategy 2 — inline JSON payload in the rendered page.
        posts = await _try_inline_json(page)
        if posts:
            return posts[:MAX_POSTS]

        # Strategy 3 — DOM grid scrape.
        try:
            html = await page.content()
        except (PlaywrightError, PlaywrightTimeoutError):
            html = ""
        if _looks_like_login_wall(html):
            log.warning("instagram fetch: login/anti-bot wall for %s", handle)
            return []

        posts = await _try_dom_grid(page)
        if posts:
            return posts[:MAX_POSTS]

        log.warning("instagram fetch: no posts extractable for %s", handle)
        return []
    except Exception as e:  # final safety net — best-effort means never raise.
        log.warning("instagram fetch failed for %s: %s", profile_url, e)
        return []
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
