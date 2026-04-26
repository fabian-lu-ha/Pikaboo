"""Gap detection — pulls a fresh Peec snapshot and persists GeoGap rows.

Wraps ``select_target_prompts`` (which ranks absent prompts by competitor
visibility × visibility gap) and writes one GeoGap row per top-K prompt.
Re-detection is idempotent on (brand_id, prompt) — repeat scans bump
``last_seen_at`` instead of duplicating rows.

Each newly detected (or re-scored) gap fires GEO_GAP_DETECTED, then the
caller (or the agent loop) immediately runs the recommender so the
dashboard fills in proposed actions without a second click.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.peec import (
    PeecSnapshot,
    fetch_snapshot,
    select_target_prompts,
)

log = logging.getLogger(__name__)


async def detect_gaps_for_brand(
    brand_id: str,
    *,
    snapshot: PeecSnapshot | None = None,
    top_k: int = 5,
    source_campaign_id: str | None = None,
) -> list[str]:
    """Persist GeoGap rows for the top-K absent prompts. Returns the list of
    persisted gap_ids.

    If ``snapshot`` is provided we reuse it (campaign loop already fetched
    one); otherwise we pull a fresh one ourselves.
    """
    brand_payload = _load_brand_payload(brand_id)
    if brand_payload is None:
        log.warning("geo.detect_gaps: brand not found id=%s", brand_id)
        return []

    snap = snapshot
    if snap is None:
        try:
            snap = await fetch_snapshot(brand_payload)
        except Exception as e:  # noqa: BLE001 — Peec fail-soft
            log.warning("geo.detect_gaps: peec fetch_snapshot crashed: %s", e)
            snap = None

    if snap is None:
        bus.emit(
            Events.GEO_SCAN_UNAVAILABLE,
            {
                "brand_id": brand_id,
                "reason": "peec snapshot unavailable",
            },
        )
        return []

    targets = select_target_prompts(snap, k=top_k)
    if not targets:
        bus.emit(
            Events.GEO_SCAN_COMPLETED,
            {
                "brand_id": brand_id,
                "gap_count": 0,
                "source_campaign_id": source_campaign_id,
            },
        )
        return []

    # Build a {prompt_text → engines_present} index from the snapshot so we
    # can attach the per-prompt engine mix to each gap (powers the per-engine
    # bias in the recommender).
    engines_index: dict[str, list[str]] = {}
    for d in snap.prompt_details:
        if d.prompt:
            engines_index[d.prompt] = list(d.engines or [])

    gap_ids: list[str] = []
    persisted: list[dict] = []
    with SessionLocal() as db:
        for tp in targets:
            row = (
                db.query(models.GeoGap)
                .filter(
                    models.GeoGap.brand_id == brand_id,
                    models.GeoGap.prompt == tp.prompt,
                )
                .one_or_none()
            )
            engines = engines_index.get(tp.prompt, [])
            comp_vis = _resolve_competitor_visibility(snap, tp.prompt)
            if row is None:
                row = models.GeoGap(
                    brand_id=brand_id,
                    prompt=tp.prompt,
                    competitor_name=tp.competitor_winning,
                    competitor_visibility=comp_vis,
                    own_visibility=tp.own_visibility,
                    gap_score=tp.score,
                    cited_domains=list(tp.top_cited_domains or []),
                    engines_present=engines,
                    source_campaign_id=source_campaign_id,
                )
                db.add(row)
                db.flush()
            else:
                # Re-score — competitor positions change, refresh in place.
                row.competitor_name = tp.competitor_winning or row.competitor_name
                row.competitor_visibility = comp_vis or row.competitor_visibility
                row.own_visibility = tp.own_visibility
                row.gap_score = tp.score
                row.cited_domains = list(tp.top_cited_domains or [])
                row.engines_present = engines or row.engines_present or []
                row.last_seen_at = datetime.now(timezone.utc)
                if source_campaign_id:
                    row.source_campaign_id = source_campaign_id
                if row.status == "dismissed":
                    # Resurfaced after dismissal — re-open so the user sees it again.
                    row.status = "open"
            gap_ids.append(row.id)
            persisted.append(_serialize_gap(row))
        db.commit()

    for g in persisted:
        bus.emit(Events.GEO_GAP_DETECTED, g)

    bus.emit(
        Events.GEO_SCAN_COMPLETED,
        {
            "brand_id": brand_id,
            "gap_count": len(gap_ids),
            "source_campaign_id": source_campaign_id,
        },
    )
    return gap_ids


async def scan_for_brand(
    brand_id: str,
    *,
    source_campaign_id: str | None = None,
    auto_recommend: bool = True,
    top_k: int = 5,
) -> list[str]:
    """One-shot scan: detect gaps, then (optionally) propose actions for
    each. Returns the persisted gap_ids. Used by both the agent loop fan-out
    and the manual ``POST /api/geo/scan`` endpoint."""
    bus.emit(
        Events.GEO_SCAN_STARTED,
        {
            "brand_id": brand_id,
            "source_campaign_id": source_campaign_id,
        },
    )
    gap_ids = await detect_gaps_for_brand(
        brand_id,
        top_k=top_k,
        source_campaign_id=source_campaign_id,
    )
    if not auto_recommend or not gap_ids:
        return gap_ids

    # Lazy import to keep the package import graph clean (recommender
    # depends on the LLM client which loads google.genai at import time).
    from app.services.geo.recommender import recommend_for_gap

    # Run recommendations concurrently — each is one Gemini call, gated on
    # network latency, no shared state. Fail-soft per gap.
    await asyncio.gather(
        *(_safe_recommend(recommend_for_gap, gid) for gid in gap_ids),
        return_exceptions=False,
    )
    return gap_ids


async def _safe_recommend(fn, gap_id: str) -> None:
    try:
        await fn(gap_id)
    except Exception as e:  # noqa: BLE001
        log.warning("geo.recommend failed for gap=%s: %s", gap_id, e)


def _load_brand_payload(brand_id: str) -> dict | None:
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return None
        return {"id": row.id, "name": row.name, "url": row.url}


def _resolve_competitor_visibility(
    snap: PeecSnapshot, prompt_text: str
) -> float | None:
    for ap in snap.absent_from:
        if ap.prompt == prompt_text:
            return ap.competitor_visibility
    return None


def _serialize_gap(row: models.GeoGap) -> dict:
    return {
        "id": row.id,
        "brand_id": row.brand_id,
        "prompt": row.prompt,
        "competitor_name": row.competitor_name,
        "competitor_visibility": row.competitor_visibility,
        "own_visibility": row.own_visibility,
        "gap_score": row.gap_score,
        "cited_domains": row.cited_domains or [],
        "engines_present": row.engines_present or [],
        "source_campaign_id": row.source_campaign_id,
        "detected_at": (row.detected_at or datetime.now(timezone.utc)).isoformat(),
        "status": row.status,
    }
