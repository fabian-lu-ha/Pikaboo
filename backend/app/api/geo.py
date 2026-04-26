"""GEO Optimization API.

Surface for the GeoPanel dashboard:

  GET  /api/geo/overview?brand_id=...        snapshot of gaps + recos + assets + playbook
  POST /api/geo/scan                         force a re-detection (auto-recommends top-K)
  POST /api/geo/recommendations/{id}/accept  user accepted; kicks asset generation
  POST /api/geo/recommendations/{id}/reject  user dismissed
  GET  /api/geo/assets/{id}                  fetch one asset (full markdown body)
  POST /api/geo/assets/{id}/publish          mark published (manual MVP)

All write endpoints emit GEO_* events on the bus so the dashboard
updates without polling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.events.bus import bus
from app.events.types import Events
from app.services.geo import (
    ENGINE_PLAYBOOK,
    action_type_label,
    action_type_summary,
    generate_asset,
    scan_for_brand,
)
from app.services.geo.asset_generator import publish_asset
from app.services.geo.playbook import ACTION_TYPES
from app.services.peec.auto_seed import auto_seed_for_brand
from app.services.peec.seed_prompts import PeecSeedError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/geo")


# --------------------------------------------------------------- response shapes


class GapOut(BaseModel):
    id: str
    prompt: str
    competitor_name: str | None
    competitor_visibility: float | None
    own_visibility: float | None
    gap_score: float
    cited_domains: list[str]
    engines_present: list[str]
    source_campaign_id: str | None
    detected_at: str
    last_seen_at: str
    status: str


class RecommendationOut(BaseModel):
    id: str
    gap_id: str
    action_type: str
    action_label: str
    action_summary: str
    confidence: float
    rationale: str | None
    target_engines: list[str]
    asset_outline: dict[str, Any]
    status: str
    created_at: str


class AssetOut(BaseModel):
    id: str
    recommendation_id: str
    gap_id: str
    action_type: str
    action_label: str
    title: str | None
    body_markdown: str | None
    body_json: dict[str, Any]
    target_url: str | None
    status: str
    publish_url: str | None
    predicted_lift_pct: float | None
    created_at: str
    published_at: str | None


class ActionTypeOut(BaseModel):
    key: str
    label: str
    summary: str


class EnginePlaybookOut(BaseModel):
    key: str
    label: str
    retrieval: str
    high_leverage: list[str]
    note: str


class GeoOverviewOut(BaseModel):
    brand_id: str
    brand_name: str
    fetched_at: str
    gaps: list[GapOut]
    recommendations: list[RecommendationOut]
    assets: list[AssetOut]
    action_types: list[ActionTypeOut]
    engine_playbook: list[EnginePlaybookOut]
    summary: dict[str, int]


class ScanIn(BaseModel):
    brand_id: str | None = None
    top_k: int = 5


class PublishIn(BaseModel):
    publish_url: str | None = None


class SeedPromptsIn(BaseModel):
    brand_id: str | None = None
    target_count: int = 12


class SeededPromptOut(BaseModel):
    id: str
    text: str
    source: str


class SeedPromptsOut(BaseModel):
    brand_id: str
    seeded: list[SeededPromptOut]
    seeded_count: int


# ------------------------------------------------------------------ endpoints


@router.get("/overview", response_model=GeoOverviewOut)
def overview(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> GeoOverviewOut:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    gaps = (
        db.query(models.GeoGap)
        .filter(models.GeoGap.brand_id == brand_id)
        .order_by(models.GeoGap.gap_score.desc())
        .all()
    )
    gap_ids = [g.id for g in gaps]
    recos = (
        db.query(models.GeoRecommendation)
        .filter(models.GeoRecommendation.brand_id == brand_id)
        .order_by(models.GeoRecommendation.created_at.desc())
        .all()
    )
    assets = (
        db.query(models.GeoAsset)
        .filter(models.GeoAsset.brand_id == brand_id)
        .order_by(models.GeoAsset.created_at.desc())
        .all()
    )

    summary = {
        "gap_count": len(gap_ids),
        "open_gap_count": sum(1 for g in gaps if g.status == "open"),
        "recommendation_count": len(recos),
        "accepted_count": sum(
            1 for r in recos if r.status in ("accepted", "generated")
        ),
        "asset_count": len(assets),
        "published_count": sum(1 for a in assets if a.status == "published"),
    }

    return GeoOverviewOut(
        brand_id=brand.id,
        brand_name=brand.name,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        gaps=[_serialize_gap_model(g) for g in gaps],
        recommendations=[_serialize_recommendation_model(r) for r in recos],
        assets=[_serialize_asset_model(a) for a in assets],
        action_types=[
            ActionTypeOut(
                key=a,
                label=action_type_label(a),
                summary=action_type_summary(a),
            )
            for a in ACTION_TYPES
        ],
        engine_playbook=[
            EnginePlaybookOut(
                key=key,
                label=info["label"],
                retrieval=info["retrieval"],
                high_leverage=info["high_leverage"],
                note=info["note"],
            )
            for key, info in ENGINE_PLAYBOOK.items()
        ],
        summary=summary,
    )


@router.post("/scan")
async def scan(
    body: ScanIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand_id = _resolve_brand_id(db, body.brand_id)
    if brand_id is None:
        raise HTTPException(status_code=404, detail="brand not found")

    # Run in the background — scan + recommend can take ~10-20s with Peec
    # latency + N Gemini calls. Fire the events lifecycle so the dashboard
    # reflects progress without blocking the HTTP request.
    asyncio.create_task(
        scan_for_brand(brand_id, top_k=body.top_k, auto_recommend=True)
    )
    return {"ok": True, "brand_id": brand_id}


@router.post("/recommendations/{recommendation_id}/accept")
async def accept_recommendation(
    recommendation_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    reco = db.get(models.GeoRecommendation, recommendation_id)
    if reco is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    reco.status = "accepted"
    db.commit()
    # Generate asset off the request thread — the GENERATING / GENERATED
    # events drive the UI.
    asyncio.create_task(generate_asset(recommendation_id))
    return {"ok": True, "recommendation_id": recommendation_id}


@router.post("/recommendations/{recommendation_id}/reject")
def reject_recommendation(
    recommendation_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    reco = db.get(models.GeoRecommendation, recommendation_id)
    if reco is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    reco.status = "rejected"
    payload = {
        "id": reco.id,
        "brand_id": reco.brand_id,
        "gap_id": reco.gap_id,
        "action_type": reco.action_type,
    }
    db.commit()
    bus.emit(Events.GEO_ACTION_REJECTED, payload)
    return {"ok": True, "recommendation_id": recommendation_id}


@router.post("/seed-prompts", response_model=SeedPromptsOut)
async def seed_prompts_endpoint(
    body: SeedPromptsIn, db: Annotated[Session, Depends(get_db)]
) -> SeedPromptsOut:
    """Seed the configured Peec project with brand-relevant prompts.

    Two-stage: accepts existing AI suggestions first, then tops up with
    Gemini-generated category prompts grounded in the brand's name +
    description + competitor list. Idempotent — if the project already
    has ≥ target_count prompts, returns an empty list."""
    brand_id = _resolve_brand_id(db, body.brand_id)
    if brand_id is None:
        raise HTTPException(status_code=404, detail="brand not found")
    try:
        seeded = await auto_seed_for_brand(brand_id, target_count=body.target_count)
    except PeecSeedError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return SeedPromptsOut(
        brand_id=brand_id,
        seeded=[
            SeededPromptOut(id=s.id, text=s.text, source=s.source) for s in seeded
        ],
        seeded_count=len(seeded),
    )


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: str, db: Annotated[Session, Depends(get_db)]
) -> AssetOut:
    asset = db.get(models.GeoAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return _serialize_asset_model(asset)


@router.post("/assets/{asset_id}/publish")
def publish(
    asset_id: str,
    body: PublishIn,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    if db.get(models.GeoAsset, asset_id) is None:
        raise HTTPException(status_code=404, detail="asset not found")
    payload = publish_asset(asset_id, publish_url=body.publish_url)
    if payload is None:
        raise HTTPException(status_code=500, detail="publish failed")
    return payload


# ------------------------------------------------------------------ helpers


def _resolve_brand_id(db: Session, brand_id: str | None) -> str | None:
    if brand_id:
        return brand_id if db.get(models.Brand, brand_id) else None
    row = (
        db.query(models.Brand)
        .filter(models.Brand.onboarded_at.is_not(None))
        .order_by(models.Brand.onboarded_at.desc())
        .first()
    )
    return row.id if row else None


def _serialize_gap_model(row: models.GeoGap) -> GapOut:
    return GapOut(
        id=row.id,
        prompt=row.prompt,
        competitor_name=row.competitor_name,
        competitor_visibility=row.competitor_visibility,
        own_visibility=row.own_visibility,
        gap_score=row.gap_score or 0.0,
        cited_domains=list(row.cited_domains or []),
        engines_present=list(row.engines_present or []),
        source_campaign_id=row.source_campaign_id,
        detected_at=(row.detected_at or datetime.now(timezone.utc)).isoformat(),
        last_seen_at=(row.last_seen_at or row.detected_at or datetime.now(timezone.utc)).isoformat(),
        status=row.status,
    )


def _serialize_recommendation_model(
    row: models.GeoRecommendation,
) -> RecommendationOut:
    return RecommendationOut(
        id=row.id,
        gap_id=row.gap_id,
        action_type=row.action_type,
        action_label=action_type_label(row.action_type),
        action_summary=action_type_summary(row.action_type),
        confidence=row.confidence or 0.0,
        rationale=row.rationale,
        target_engines=list(row.target_engines or []),
        asset_outline=dict(row.asset_outline or {}),
        status=row.status,
        created_at=(row.created_at or datetime.now(timezone.utc)).isoformat(),
    )


def _serialize_asset_model(row: models.GeoAsset) -> AssetOut:
    return AssetOut(
        id=row.id,
        recommendation_id=row.recommendation_id,
        gap_id=row.gap_id,
        action_type=row.action_type,
        action_label=action_type_label(row.action_type),
        title=row.title,
        body_markdown=row.body_markdown,
        body_json=dict(row.body_json or {}),
        target_url=row.target_url,
        status=row.status,
        publish_url=row.publish_url,
        predicted_lift_pct=row.predicted_lift_pct,
        created_at=(row.created_at or datetime.now(timezone.utc)).isoformat(),
        published_at=row.published_at.isoformat() if row.published_at else None,
    )
