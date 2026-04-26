"""Onboarding orchestrator.

Single canonical pipeline: every brand-like subject (main brand, competitor,
reference brand) flows through `app.services.pipeline.visual` — same scrape,
same extract, same storage shape. Subject-specific work (LLM voice, posts,
style, persistence) layers on top.
"""

import asyncio
import logging
from dataclasses import asdict

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.llm import prompts
from app.services.llm.client import chat_json
from app.services.pipeline import (
    VisualIdentity,
    enrich_logo_only,
    enrich_visual,
    visual_to_event_payload,
)
from app.services.research import gather_brand_context
from app.services.social import Post, post_to_dict
from app.services.social import instagram as social_instagram
from app.services.social import linkedin as social_linkedin
from app.services.social import tiktok as social_tiktok
from app.services.social import x as social_x
from app.services.social import youtube as social_youtube
from app.services.style import analyze_style
from app.services.video import attach_analysis, is_video_post

log = logging.getLogger(__name__)

_PLATFORM_FETCHERS = {
    "youtube": social_youtube.fetch,
    "instagram": social_instagram.fetch,
    "tiktok": social_tiktok.fetch,
    "x": social_x.fetch,
    "linkedin": social_linkedin.fetch,
}

VIDEO_ANALYZE_CAP = 5


async def _fetch_handle(platform: str, url: str) -> list[Post]:
    fetcher = _PLATFORM_FETCHERS.get(platform)
    if fetcher is None or not url:
        return []
    try:
        return await fetcher(url)
    except Exception as e:
        log.warning("social fetch failed [%s] %s: %s", platform, url, e)
        return []


async def _fetch_all_posts(handles: dict[str, str]) -> list[Post]:
    if not handles:
        return []
    pairs = [(p, u) for p, u in handles.items() if u]
    if not pairs:
        return []
    results = await asyncio.gather(
        *(_fetch_handle(p, u) for p, u in pairs), return_exceptions=True
    )
    posts: list[Post] = []
    for r in results:
        if isinstance(r, list):
            posts.extend(r)
    return posts


async def _enrich_video_posts(posts: list[Post]) -> list[Post]:
    if not posts:
        return posts
    seen: set[str | None] = set()
    targets: list[Post] = []
    for p in posts:
        if p.url in seen:
            continue
        seen.add(p.url)
        if is_video_post(p) and len(targets) < VIDEO_ANALYZE_CAP:
            targets.append(p)
    if not targets:
        return posts
    try:
        await asyncio.gather(*(attach_analysis(p) for p in targets))
    except Exception as e:
        log.warning("video analysis batch failed: %s", e)
    return posts


async def enrich_competitor(brand_id: str, comp_id: str, url: str) -> str | None:
    """Public entry point for the lite competitor enrichment path.
    Used by the orchestrator AND by the on-demand /competitors/add endpoint."""
    return await enrich_logo_only(
        url, f"brands/{brand_id}/competitors/{comp_id}"
    )


async def _extract_and_persist_competitor_products(
    brand_id: str, comp_id: str, url: str
) -> int:
    """Pull a small product catalog from the competitor URL and stash it
    on ``Competitor.pattern_library['products']``. Fail-soft: returns 0 on
    any extractor error so onboarding never gets stuck on a brittle scrape."""
    if not url:
        return 0
    from app.services.enrichment.competitor_products import (
        extract as _extract_products,
    )

    bus.emit(
        Events.ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTING,
        {"brand_id": brand_id, "competitor_id": comp_id, "url": url},
    )
    try:
        products = await _extract_products(url)
    except Exception:
        log.exception("competitor product extract crashed (treating as 0)")
        products = []

    with SessionLocal() as cdb:
        row = cdb.get(models.Competitor, comp_id)
        if row is not None:
            pattern_library = dict(row.pattern_library or {})
            pattern_library["products"] = products
            row.pattern_library = pattern_library
            cdb.add(row)
            cdb.commit()

    bus.emit(
        Events.ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTED,
        {
            "brand_id": brand_id,
            "competitor_id": comp_id,
            "product_count": len(products),
        },
    )
    return len(products)


async def _run_post_enrichment(
    brand_id: str,
    handles: dict[str, str],
    screenshots: list[bytes] | None,
    brand_name: str,
    palette: list[str],
) -> None:
    if handles:
        bus.emit(Events.ONBOARDING_POSTS_FETCHING, {"brand_id": brand_id})
        try:
            posts = await _fetch_all_posts(handles)
            if posts:
                await _enrich_video_posts(posts)
            serialized = [post_to_dict(p) for p in posts]
            with SessionLocal() as bdb:
                row = bdb.get(models.Brand, brand_id)
                if row is not None:
                    row.recent_posts = serialized
                    bdb.add(row)
                    bdb.commit()
            bus.emit(
                Events.ONBOARDING_POSTS_FETCHED,
                {"brand_id": brand_id, "posts": serialized},
            )
        except Exception as e:
            log.exception("post fetch failed: %s", e)

    if screenshots:
        bus.emit(Events.ONBOARDING_STYLE_ANALYZING, {"brand_id": brand_id})
        try:
            style = await analyze_style(
                screenshots, brand_name or "the brand", palette or []
            )
            if style is not None:
                style_dict = asdict(style)
                with SessionLocal() as bdb:
                    row = bdb.get(models.Brand, brand_id)
                    if row is not None:
                        row.style_profile = style_dict
                        bdb.add(row)
                        bdb.commit()
                bus.emit(
                    Events.ONBOARDING_STYLE_ANALYZED,
                    {"brand_id": brand_id, "style_profile": style_dict},
                )
            else:
                bus.emit(
                    Events.ONBOARDING_FAILED,
                    {"brand_id": brand_id, "error": "style: returned None"},
                )
        except Exception as e:
            log.exception("style analysis failed: %s", e)
            bus.emit(
                Events.ONBOARDING_FAILED,
                {"brand_id": brand_id, "error": f"style: {e}"},
            )


async def _persist_visual(brand: models.Brand, v: VisualIdentity) -> None:
    """Apply a VisualIdentity to a Brand row. Doesn't commit — caller owns the txn."""
    if (not brand.name or brand.name == "(unnamed)") and v.title:
        cleaned = v.title.split(" | ")[0].split(" — ")[0].strip()
        if cleaned:
            brand.name = cleaned[:120]
    if not brand.description and v.description:
        brand.description = v.description
    brand.logo_url = v.logo_url
    brand.screenshots = v.screenshots
    brand.theme_color = v.theme_color
    brand.palette = v.palette
    brand.palette_roles = v.palette_roles
    brand.identity = v.identity
    brand.product_images = v.product_images
    brand.handles = {**(brand.handles or {}), **v.handles}


async def run(brand_id: str) -> None:
    db = SessionLocal()
    try:
        brand = db.get(models.Brand, brand_id)
        if not brand or not brand.url:
            bus.emit(
                Events.ONBOARDING_FAILED,
                {"brand_id": brand_id, "error": "no url"},
            )
            return

        url = brand.url
        bus.emit(
            Events.ONBOARDING_SCRAPING, {"brand_id": brand_id, "url": url}
        )

        try:
            visual = await enrich_visual(url, f"brands/{brand_id}")
        except Exception as e:
            log.exception("enrich_visual failed")
            bus.emit(
                Events.ONBOARDING_FAILED,
                {"brand_id": brand_id, "error": f"scrape: {e}"},
            )
            return

        if visual.parked:
            bus.emit(
                Events.ONBOARDING_FAILED,
                {"brand_id": brand_id, "error": "site is a parked domain"},
            )
            return

        await _persist_visual(brand, visual)
        db.add(brand)
        db.commit()
        db.refresh(brand)

        brand_name = brand.name
        brand_handles = dict(brand.handles or {})
        brand_palette = list(brand.palette or [])

        bus.emit(
            Events.ONBOARDING_SCRAPED,
            {
                "brand_id": brand_id,
                **visual_to_event_payload(visual),
            },
        )

        if visual.identity:
            bus.emit(
                Events.ONBOARDING_IDENTITY_EXTRACTED,
                {"brand_id": brand_id, "identity": visual.identity},
            )

        bus.emit(Events.ONBOARDING_VOICE_DISTILLING, {"brand_id": brand_id})
        try:
            voice_profile = await chat_json(
                prompts.voice_profile_messages(
                    brand_name or "the company",
                    visual.body_markdown or "",
                    pasted_posts=brand.pasted_posts,
                ),
                schema=prompts.VOICE_PROFILE_SCHEMA,
            )
            brand.voice_profile = voice_profile
            db.add(brand)
            db.commit()
            bus.emit(
                Events.ONBOARDING_VOICE_DISTILLED,
                {"brand_id": brand_id, "voice_profile": voice_profile},
            )
        except Exception as e:
            log.exception("voice distill failed")
            bus.emit(
                Events.ONBOARDING_FAILED,
                {"brand_id": brand_id, "error": f"voice: {e}"},
            )

        bus.emit(Events.ONBOARDING_COMPETITORS_SUGGESTING, {"brand_id": brand_id})
        try:
            comps_payload = await chat_json(
                prompts.competitors_messages(
                    brand_name or "the company",
                    brand.description,
                    visual.body_markdown or "",
                ),
                schema=prompts.COMPETITORS_SCHEMA,
            )
            comps = (comps_payload.get("competitors") or [])[:5]
            saved: list[dict] = []
            for c in comps:
                row = models.Competitor(
                    brand_id=brand_id,
                    name=(c.get("name") or "").strip() or "(unnamed)",
                    url=c.get("url"),
                    reason=c.get("reason"),
                )
                db.add(row)
                db.flush()
                saved.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "url": row.url,
                        "reason": row.reason,
                    }
                )
            db.commit()
            bus.emit(
                Events.ONBOARDING_COMPETITORS_SUGGESTED,
                {"brand_id": brand_id, "competitors": saved},
            )

            async def enrich_and_persist(comp: dict) -> None:
                if not comp["url"]:
                    return
                logo = await enrich_competitor(
                    brand_id, comp["id"], comp["url"]
                )
                with SessionLocal() as cdb:
                    row = cdb.get(models.Competitor, comp["id"])
                    if row is None:
                        return
                    row.logo_url = logo
                    cdb.add(row)
                    cdb.commit()
                bus.emit(
                    Events.ONBOARDING_COMPETITOR_ENRICHED,
                    {
                        "brand_id": brand_id,
                        "competitor_id": comp["id"],
                        "logo_url": logo,
                    },
                )
                # Pull product catalog asynchronously — fail-soft, doesn't
                # block subsequent onboarding events.
                await _extract_and_persist_competitor_products(
                    brand_id, comp["id"], comp["url"]
                )

            await asyncio.gather(*(enrich_and_persist(c) for c in saved))
        except Exception as e:
            log.exception("competitor suggestion failed")
            bus.emit(
                Events.ONBOARDING_FAILED,
                {"brand_id": brand_id, "error": f"competitors: {e}"},
            )

        # release main session before kicking off post-enrichment
        screenshots_for_style = await _reload_screenshot_bytes(
            brand_id, len(visual.screenshots)
        )
        brand_description = brand.description
        # snapshot competitors for the research call before we drop the session
        research_competitors = [
            {"name": c.name, "url": c.url} for c in brand.competitors
        ]
    finally:
        db.close()

    # Post-enrichment + research run without the main session held — they
    # each open fresh short-lived sessions for their own writes. Research is
    # parallel to style/posts because Tavily is network-bound and the LLM
    # for style analysis is GPU-bound; no shared state.
    await asyncio.gather(
        _run_post_enrichment(
            brand_id=brand_id,
            handles=brand_handles,
            screenshots=screenshots_for_style,
            brand_name=brand_name or "",
            palette=brand_palette,
        ),
        _run_research(
            brand_id=brand_id,
            brand_name=brand_name or "",
            brand_url=url,
            description=brand_description,
            competitors=research_competitors,
        ),
    )


async def _run_research(
    *,
    brand_id: str,
    brand_name: str,
    brand_url: str | None,
    description: str | None,
    competitors: list[dict],
) -> None:
    """Tavily research leg — fail-soft, persists onto Brand.research."""
    try:
        bundle = await gather_brand_context(
            brand_id=brand_id,
            brand_name=brand_name,
            brand_url=brand_url,
            description=description,
            competitors=competitors,
        )
    except Exception:
        log.exception("brand research crashed")
        return

    payload = bundle.to_dict()
    try:
        with SessionLocal() as bdb:
            row = bdb.get(models.Brand, brand_id)
            if row is not None:
                row.research = payload
                bdb.add(row)
                bdb.commit()
    except Exception:
        log.exception("brand research persist failed")


async def _reload_screenshot_bytes(
    brand_id: str, count: int
) -> list[bytes] | None:
    """Re-read screenshot bytes from local FS for style analysis.
    For Supabase mode we'd download from storage instead — out of scope for v0.
    """
    if count <= 0:
        return None
    from pathlib import Path

    from app.config import settings

    if settings.deploy_mode != "local":
        return None
    base = Path(settings.storage_dir) / "brands" / brand_id
    out: list[bytes] = []
    for i in range(count):
        p = base / f"screenshot_{i}.png"
        if p.exists():
            out.append(p.read_bytes())
    return out or None
