import logging
import re
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services.social import Post

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3"

_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,}$")


def _extract_handle(profile_url: str) -> str | None:
    if not profile_url:
        return None
    s = profile_url.strip()
    if not s:
        return None

    if "/" not in s and "." not in s:
        return s.lstrip("@") or None

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
    if first.startswith("@"):
        return first
    if first in ("c", "user", "channel") and len(parts) >= 2:
        if first == "channel":
            return parts[1]
        return parts[1]
    if first.startswith("UC") and _CHANNEL_ID_RE.match(first):
        return first
    return first.lstrip("@") or None


async def _resolve_channel_id(
    client: httpx.AsyncClient, key: str, handle_or_id: str
) -> str | None:
    if _CHANNEL_ID_RE.match(handle_or_id):
        return handle_or_id

    handle = handle_or_id.lstrip("@")
    handle_with_at = "@" + handle

    r = await client.get(
        f"{API}/channels",
        params={"part": "id", "forHandle": handle_with_at, "key": key},
    )
    if r.status_code == 200:
        items = r.json().get("items") or []
        if items:
            return items[0].get("id")
    elif r.status_code in (401, 403):
        log.warning("youtube channels.list forHandle %s -> %s: %s", handle_with_at, r.status_code, r.text[:200])
        return None

    r = await client.get(
        f"{API}/channels",
        params={"part": "id", "forUsername": handle, "key": key},
    )
    if r.status_code == 200:
        items = r.json().get("items") or []
        if items:
            return items[0].get("id")

    r = await client.get(
        f"{API}/search",
        params={"part": "snippet", "q": handle, "type": "channel", "maxResults": 1, "key": key},
    )
    if r.status_code == 200:
        items = r.json().get("items") or []
        if items:
            return items[0].get("snippet", {}).get("channelId") or items[0].get("id", {}).get("channelId")

    return None


async def fetch(profile_url: str) -> list[Post]:
    key = settings.gemini_api_key
    if not key:
        log.warning("youtube fetch: GEMINI_API_KEY not set")
        return []

    handle = _extract_handle(profile_url)
    if not handle:
        log.warning("youtube fetch: could not extract handle from %s", profile_url)
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            cid = await _resolve_channel_id(client, key, handle)
            if not cid:
                log.warning("youtube fetch: could not resolve channel for %s", profile_url)
                return []

            r = await client.get(
                f"{API}/search",
                params={
                    "part": "snippet",
                    "channelId": cid,
                    "order": "date",
                    "type": "video",
                    "maxResults": 5,
                    "key": key,
                },
            )
            if r.status_code != 200:
                log.warning("youtube search.list %s -> %s: %s", cid, r.status_code, r.text[:200])
                return []

            items = r.json().get("items") or []
            posts: list[Post] = []
            for item in items:
                vid = (item.get("id") or {}).get("videoId")
                snip = item.get("snippet") or {}
                if not vid or not snip:
                    continue
                title = snip.get("title") or ""
                desc = snip.get("description") or ""
                caption = title if not desc else f"{title}\n\n{desc[:280]}"
                thumbs = snip.get("thumbnails") or {}
                thumb = (
                    thumbs.get("high")
                    or thumbs.get("medium")
                    or thumbs.get("default")
                    or {}
                ).get("url")
                posts.append(
                    Post(
                        platform="youtube",
                        caption=caption,
                        media_urls=[thumb] if thumb else [],
                        posted_at=snip.get("publishedAt"),
                        url=f"https://www.youtube.com/watch?v={vid}",
                        likes=None,
                    )
                )
            return posts
    except Exception as e:
        log.warning("youtube fetch failed for %s: %s", profile_url, e)
        return []
