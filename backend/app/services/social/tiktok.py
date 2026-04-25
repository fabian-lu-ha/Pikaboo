"""Public TikTok profile scraper — best-effort.

Strategy (2026):
1. Render `tiktok.com/@<handle>` with Playwright (the existing pool).
2. While the page loads, listen for `/api/post/item_list/` XHR responses —
   that's the canonical source of the user's video feed.
3. In parallel, parse the `__UNIVERSAL_DATA_FOR_REHYDRATION__` script tag.
   Two useful payloads can live there:
     - `__DEFAULT_SCOPE__["webapp.user-detail"]["userInfo"]` — profile + secUid
     - `__DEFAULT_SCOPE__["webapp.user-post"]["itemList"]`   — first-page items
       (key name varies; we walk the tree to find any list of post-shaped dicts)
4. Map the first 5 items to `Post`. On any failure, return [] and log a warning.

Note on TikTok's anti-bot: pages frequently redirect to a captcha / login wall
for headless Chromium. We use a realistic UA + viewport. If the wall hits, we
just return [] — no third-party paid bypass services per project constraints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

from app.services.enrichment.browser import get_browser
from app.services.social import Post

log = logging.getLogger(__name__)

_PLATFORM = "tiktok"
_MAX_POSTS = 5
_CAPTION_LIMIT = 500
_NAV_TIMEOUT_MS = 20000
_SETTLE_MS = 2500
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]{1,40}$")
_REHYDRATION_RE = re.compile(
    r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_handle(profile_url: str) -> str | None:
    """Pull the @handle out of any reasonable TikTok URL or bare handle."""
    if not profile_url:
        return None
    s = profile_url.strip()
    if not s:
        return None

    # Bare handle ("username" or "@username")
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

    first = parts[0]
    cand = first.lstrip("@")
    return cand if _HANDLE_RE.match(cand) else None


def _walk_for_item_list(node: Any, depth: int = 0) -> list[dict] | None:
    """Walk a JSON tree looking for a list of post-shaped dicts.

    TikTok's rehydration JSON has shifted keys multiple times
    (`webapp.user-post`, `ItemList.user-post.list`, `webapp.user-post-detail-list`,
    plain `itemList`, etc). Rather than hard-code one path, we recursively
    look for any key called `itemList` (or the older `items`) whose value
    is a list of dicts that look like TikTok video items (have `id` + `desc`
    or `video`).
    """
    if depth > 8:
        return None
    if isinstance(node, dict):
        for key in ("itemList", "items"):
            cand = node.get(key)
            if (
                isinstance(cand, list)
                and cand
                and isinstance(cand[0], dict)
                and ("desc" in cand[0] or "video" in cand[0] or "id" in cand[0])
            ):
                return cand
        for v in node.values():
            found = _walk_for_item_list(v, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _walk_for_item_list(v, depth + 1)
            if found:
                return found
    return None


def _parse_rehydration(html: str) -> list[dict]:
    """Extract item list from the `__UNIVERSAL_DATA_FOR_REHYDRATION__` script."""
    m = _REHYDRATION_RE.search(html or "")
    if not m:
        return []
    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError:
        # selectolax can recover from malformed surrounding HTML where the
        # regex chokes; try DOM parse as a backup.
        try:
            dom = HTMLParser(html)
            node = dom.css_first("script#__UNIVERSAL_DATA_FOR_REHYDRATION__")
            if not node:
                return []
            blob = json.loads(node.text() or "")
        except Exception:
            return []
    scope = (blob or {}).get("__DEFAULT_SCOPE__") or {}
    items = _walk_for_item_list(scope) or []
    return items


def _to_iso(create_time: Any) -> str | None:
    """TikTok createTime is unix seconds. Return ISO-8601 UTC."""
    if create_time is None:
        return None
    try:
        ts = int(create_time)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _video_url(handle: str, item: dict) -> str | None:
    vid = item.get("id") or item.get("itemId")
    if not vid:
        return None
    return f"https://www.tiktok.com/@{handle}/video/{vid}"


def _cover(item: dict) -> str | None:
    video = item.get("video") or {}
    if not isinstance(video, dict):
        return None
    for key in ("cover", "originCover", "dynamicCover"):
        url = video.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _likes(item: dict) -> int | None:
    stats = item.get("stats") or item.get("statsV2") or {}
    if not isinstance(stats, dict):
        return None
    val = stats.get("diggCount")
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return None


def _to_post(handle: str, item: dict) -> Post | None:
    if not isinstance(item, dict):
        return None
    url = _video_url(handle, item)
    if not url:
        return None
    desc = item.get("desc") or ""
    if not isinstance(desc, str):
        desc = str(desc)
    caption = desc[:_CAPTION_LIMIT]
    cover = _cover(item)
    return Post(
        platform=_PLATFORM,
        caption=caption,
        media_urls=[cover] if cover else [],
        posted_at=_to_iso(item.get("createTime")),
        url=url,
        likes=_likes(item),
    )


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        vid = str(it.get("id") or it.get("itemId") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(it)
    return out


def _sort_recent(items: list[dict]) -> list[dict]:
    def key(it: dict) -> int:
        try:
            return int(it.get("createTime") or 0)
        except (TypeError, ValueError):
            return 0
    return sorted(items, key=key, reverse=True)


async def fetch(profile_url: str) -> list[Post]:
    """Fetch up to 5 most recent public videos for a TikTok profile.

    Best-effort: returns [] on any failure. Never raises.
    """
    handle = _extract_handle(profile_url)
    if not handle:
        log.warning("tiktok fetch: could not extract handle from %r", profile_url)
        return []

    target = f"https://www.tiktok.com/@{handle}"

    try:
        browser = get_browser()
    except Exception as e:
        log.warning("tiktok fetch: browser unavailable: %s", e)
        return []

    ctx = None
    try:
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=_USER_AGENT,
            locale="en-US",
        )
        page = await ctx.new_page()

        # Capture /api/post/item_list/ responses fired by the page.
        xhr_items: list[dict] = []

        async def _on_response(resp) -> None:
            try:
                if "/api/post/item_list" not in resp.url:
                    return
                if resp.status != 200:
                    return
                body = await resp.json()
            except Exception:
                return
            items = (body or {}).get("itemList")
            if isinstance(items, list):
                xhr_items.extend(i for i in items if isinstance(i, dict))

        page.on("response", lambda r: asyncio.create_task(_on_response(r)))

        try:
            await page.goto(
                target, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS
            )
        except Exception as e:
            log.warning("tiktok fetch: goto %s failed: %s", target, e)
            return []

        # Let XHR fire and the rehydration script fully serialize.
        try:
            await page.wait_for_selector(
                "script#__UNIVERSAL_DATA_FOR_REHYDRATION__",
                timeout=8000,
                state="attached",
            )
        except Exception:
            # Captcha / login wall / region block — fall through; we'll
            # still try whatever HTML we have.
            pass

        await page.wait_for_timeout(_SETTLE_MS)

        try:
            html = await page.content()
        except Exception:
            html = ""

        # Combine sources: XHR (canonical) + rehydration (fallback for first page).
        rehydration_items = _parse_rehydration(html)
        combined = _dedupe(xhr_items + rehydration_items)

        if not combined:
            log.warning(
                "tiktok fetch: no items found for @%s "
                "(likely captcha/login wall or empty profile)",
                handle,
            )
            return []

        recent = _sort_recent(combined)[:_MAX_POSTS]
        posts = [p for it in recent if (p := _to_post(handle, it)) is not None]
        return posts

    except Exception as e:
        log.warning("tiktok fetch failed for %s: %s", profile_url, e)
        return []
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass
