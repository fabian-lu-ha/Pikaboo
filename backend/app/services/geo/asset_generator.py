"""Asset generator dispatch — given a recommendation, run the matching
generator, persist a GeoAsset row, and emit lifecycle events.

Each generator function returns a ``GeneratedAsset`` dataclass with
``title``, ``body_markdown``, ``body_json``, ``target_url``, and an
optional ``predicted_lift_pct``. The dispatch table maps action_type to
generator function so adding a new playbook entry is one line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.geo.playbook import action_type_label

log = logging.getLogger(__name__)


@dataclass
class GeneratedAsset:
    title: str
    body_markdown: str | None = None
    body_json: dict[str, Any] = field(default_factory=dict)
    target_url: str | None = None
    predicted_lift_pct: float | None = None


GeneratorFn = Callable[[dict, dict, dict], Awaitable[GeneratedAsset]]


async def generate_asset(recommendation_id: str) -> str | None:
    """Resolve recommendation → load context → dispatch to generator →
    persist GeoAsset → emit events. Returns the asset id or None on failure.
    """
    ctx = _load_recommendation_context(recommendation_id)
    if ctx is None:
        return None
    brand, gap, recommendation = ctx
    action_type = recommendation["action_type"]
    generator = _GENERATORS.get(action_type)
    if generator is None:
        log.warning("geo.generate_asset: unknown action_type=%s", action_type)
        return None

    bus.emit(
        Events.GEO_ASSET_GENERATING,
        {
            "recommendation_id": recommendation_id,
            "brand_id": brand["id"],
            "gap_id": gap["id"],
            "action_type": action_type,
        },
    )

    try:
        result = await generator(brand, gap, recommendation)
    except Exception as e:  # noqa: BLE001 — fail-soft, surface to UI
        log.exception("geo asset generator crashed: %s", e)
        bus.emit(
            Events.GEO_ASSET_GENERATING,
            {
                "recommendation_id": recommendation_id,
                "brand_id": brand["id"],
                "gap_id": gap["id"],
                "action_type": action_type,
                "error": str(e)[:240],
                "status": "failed",
            },
        )
        return None

    with SessionLocal() as db:
        asset = models.GeoAsset(
            brand_id=brand["id"],
            recommendation_id=recommendation_id,
            gap_id=gap["id"],
            action_type=action_type,
            title=result.title,
            body_markdown=result.body_markdown,
            body_json=result.body_json or {},
            target_url=result.target_url,
            predicted_lift_pct=result.predicted_lift_pct,
        )
        db.add(asset)
        # Mark recommendation as generated so the dashboard can flip the
        # action card to "asset ready" without a second poll.
        reco_row = db.get(models.GeoRecommendation, recommendation_id)
        if reco_row is not None:
            reco_row.status = "generated"
        gap_row = db.get(models.GeoGap, gap["id"])
        if gap_row is not None:
            gap_row.status = "addressed"
        db.flush()
        payload = _serialize_asset(asset)
        db.commit()
        asset_id = payload["id"]

    bus.emit(Events.GEO_ASSET_GENERATED, payload)
    return asset_id


def _load_recommendation_context(
    recommendation_id: str,
) -> tuple[dict, dict, dict] | None:
    with SessionLocal() as db:
        reco = db.get(models.GeoRecommendation, recommendation_id)
        if reco is None:
            return None
        gap = db.get(models.GeoGap, reco.gap_id)
        if gap is None:
            return None
        brand = db.get(models.Brand, reco.brand_id)
        if brand is None:
            return None
        return (
            {
                "id": brand.id,
                "name": brand.name,
                "url": brand.url,
                "description": brand.description,
                "voice_profile": brand.voice_profile or {},
                "recent_posts": brand.recent_posts or [],
                "handles": brand.handles or {},
            },
            {
                "id": gap.id,
                "prompt": gap.prompt,
                "competitor_name": gap.competitor_name,
                "competitor_visibility": gap.competitor_visibility,
                "own_visibility": gap.own_visibility,
                "cited_domains": gap.cited_domains or [],
                "engines_present": gap.engines_present or [],
            },
            {
                "id": reco.id,
                "action_type": reco.action_type,
                "confidence": reco.confidence,
                "rationale": reco.rationale,
                "target_engines": reco.target_engines or [],
                "asset_outline": reco.asset_outline or {},
            },
        )


def _serialize_asset(row: models.GeoAsset) -> dict:
    return {
        "id": row.id,
        "brand_id": row.brand_id,
        "recommendation_id": row.recommendation_id,
        "gap_id": row.gap_id,
        "action_type": row.action_type,
        "action_label": action_type_label(row.action_type),
        "title": row.title,
        "body_markdown": row.body_markdown,
        "body_json": row.body_json or {},
        "target_url": row.target_url,
        "status": row.status,
        "publish_url": row.publish_url,
        "predicted_lift_pct": row.predicted_lift_pct,
        "created_at": (row.created_at or datetime.now(timezone.utc)).isoformat(),
    }


def publish_asset(asset_id: str, publish_url: str | None = None) -> dict | None:
    """Mark an asset as published. publish_url is optional — for MVP, "publish"
    means "user shipped it" (manual copy/paste); the URL is captured if the
    integration layer ever ends up posting it directly to a channel."""
    with SessionLocal() as db:
        row = db.get(models.GeoAsset, asset_id)
        if row is None:
            return None
        row.status = "published"
        row.publish_url = publish_url or row.publish_url
        row.published_at = datetime.now(timezone.utc)
        payload = _serialize_asset(row)
        db.commit()
    bus.emit(Events.GEO_ASSET_PUBLISHED, payload)
    return payload


# ── Generator registry ──────────────────────────────────────────────────────

# Imported lazily inside the dict construction so the per-action generator
# modules can each pull in their own LLM helpers without a circular import.
def _gen_comparison_page() -> GeneratorFn:
    from app.services.geo.generators.comparison_page import generate
    return generate


def _gen_definition_first() -> GeneratorFn:
    from app.services.geo.generators.definition_first import generate
    return generate


def _gen_faq_schema() -> GeneratorFn:
    from app.services.geo.generators.faq_schema import generate
    return generate


def _gen_stats_quote() -> GeneratorFn:
    from app.services.geo.generators.stats_quote import generate
    return generate


def _gen_wikidata_schema() -> GeneratorFn:
    from app.services.geo.generators.wikidata_schema import generate
    return generate


def _gen_reddit_draft() -> GeneratorFn:
    from app.services.geo.generators.reddit_draft import generate
    return generate


_GENERATORS: dict[str, GeneratorFn] = {}


def _register() -> None:
    _GENERATORS["comparison_page"] = _gen_comparison_page()
    _GENERATORS["definition_first"] = _gen_definition_first()
    _GENERATORS["faq_schema"] = _gen_faq_schema()
    _GENERATORS["stats_quote"] = _gen_stats_quote()
    _GENERATORS["wikidata_schema"] = _gen_wikidata_schema()
    _GENERATORS["reddit_draft"] = _gen_reddit_draft()


_register()
