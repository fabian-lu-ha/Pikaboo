"""Canonical visual-identity enrichment pipeline.

ONE entry point used by every brand-like subject (main brand, reference brand,
and the lite path for competitors). Same scrape, same extract, same storage
shape. Avoid copy-pasting scrape+extract+store sequences anywhere else.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import httpx

from app.providers.factory import get_storage
from app.services.enrichment.extract import (
    extract,
    extract_logo,
    is_parking_page,
)
from app.services.enrichment.scraper import scrape, scrape_lite
from app.services.utils.security import is_safe_http_url, safe_extension

log = logging.getLogger(__name__)


@dataclass
class VisualIdentity:
    """Unified shape for everything we know about a brand-like subject's
    visual presence after a full scrape + extract pass."""

    url: str
    final_url: str
    title: str | None = None
    description: str | None = None
    logo_url: str | None = None
    screenshots: list[str] = field(default_factory=list)
    palette: list[str] = field(default_factory=list)
    palette_roles: list[dict] = field(default_factory=list)
    theme_color: str | None = None
    handles: dict[str, str] = field(default_factory=dict)
    product_images: list[str] = field(default_factory=list)
    body_markdown: str | None = None
    css_palette: dict | None = None
    identity: dict = field(default_factory=dict)
    parked: bool = False


def visual_to_event_payload(v: VisualIdentity) -> dict:
    """Strip non-serializable / oversized fields before emitting on the bus."""
    payload = asdict(v)
    payload.pop("body_markdown", None)
    payload.pop("css_palette", None)
    return payload


async def _download(
    url: str, timeout: float = 15.0
) -> tuple[bytes, str] | None:
    if not is_safe_http_url(url):
        log.warning("download blocked (unsafe url): %s", url)
        return None
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        ctype = (
            resp.headers.get("content-type", "application/octet-stream")
            .split(";")[0]
            .strip()
        )
        return resp.content, ctype
    except Exception as e:
        log.warning("download failed for %s: %s", url, e)
        return None


async def _proxy_logo(
    storage_prefix: str, logo_url: str | None
) -> str | None:
    """Proxy a logo URL through our storage layer. Pass-through for data: URIs."""
    if not logo_url:
        return None
    if logo_url.startswith("data:"):
        return logo_url
    fetched = await _download(logo_url)
    if fetched is None:
        return logo_url
    data, ctype = fetched
    ext = safe_extension(ctype.split("/")[-1].split("+")[0])
    storage = get_storage()
    key = f"{storage_prefix}/logo.{ext}"
    await storage.put(key, data, ctype)
    return await storage.get_url(key)


async def _store_screenshots(
    storage_prefix: str, frames: list[bytes]
) -> list[str]:
    storage = get_storage()
    urls: list[str] = []
    for i, png in enumerate(frames):
        key = f"{storage_prefix}/screenshot_{i}.png"
        await storage.put(key, png, "image/png")
        urls.append(await storage.get_url(key))
    return urls


async def enrich_visual(
    url: str, storage_prefix: str
) -> VisualIdentity:
    """Full visual identity: scrape → extract → store. Used by main brand AND
    reference brands. Returns a unified `VisualIdentity` regardless of caller.

    `storage_prefix` examples:
      brands/{brand_id}                       (main brand)
      brands/{brand_id}/references/{ref_id}   (reference brand)
    """
    if not is_safe_http_url(url):
        raise ValueError(f"unsafe url: {url}")

    scraped = await scrape(url)
    if is_parking_page(scraped.html):
        return VisualIdentity(
            url=url, final_url=scraped.final_url, parked=True
        )

    ex = extract(
        scraped.html,
        scraped.screenshots,
        scraped.final_url,
        css_palette=scraped.css_palette,
    )

    screenshot_urls = await _store_screenshots(
        storage_prefix, scraped.screenshots
    )
    logo_url = await _proxy_logo(storage_prefix, ex.logo_url)

    return VisualIdentity(
        url=url,
        final_url=scraped.final_url,
        title=ex.title,
        description=ex.description,
        logo_url=logo_url,
        screenshots=screenshot_urls,
        palette=ex.palette,
        palette_roles=ex.palette_roles,
        theme_color=ex.theme_color,
        handles=ex.handles,
        product_images=ex.product_images,
        body_markdown=ex.body_markdown,
        css_palette=scraped.css_palette,
        identity=ex.identity,
        parked=False,
    )


async def enrich_logo_only(
    url: str, storage_prefix: str
) -> str | None:
    """Lite path: scrape_lite + extract_logo + proxy. Used for competitors
    at scale where we don't need screenshots / palette / voice."""
    if not is_safe_http_url(url):
        log.warning("enrich_logo_only blocked (unsafe url): %s", url)
        return None
    try:
        scraped = await scrape_lite(url)
        if is_parking_page(scraped.html):
            log.info(
                "enrich_logo_only: %s is a parked domain, skipping", url
            )
            return None
        logo = extract_logo(scraped.html, scraped.final_url)
        return await _proxy_logo(storage_prefix, logo)
    except Exception as e:
        log.warning("enrich_logo_only failed for %s: %s", url, e)
        return None
