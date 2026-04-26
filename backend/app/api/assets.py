"""Brand asset library API.

Reads + AI-describer triggers — the Library page lists assets, the
storyboard editor offers them as importable ingredients, and Gemini
Vision authors a description per asset that flows into the planner.

Asset rows are populated by the bus listener in ``services/assets/library.py``.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.services.asset_describe import describe_asset, describe_brand_assets
from app.services.assets.library import backfill_brand_assets

router = APIRouter(prefix="/assets")


class AssetItem(BaseModel):
    id: str
    brand_id: str
    kind: str
    subkind: str
    url: str
    storyboard_id: str | None
    cast_kind: str | None
    label: str | None
    prompt_preview: str | None
    duration_ms: int | None
    aspect: str | None
    meta: dict[str, Any]
    description: str | None = None
    tags: list[str] = []
    description_status: str | None = None
    created_at: str


class AssetListResponse(BaseModel):
    items: list[AssetItem]
    total: int


def _to_item(a: models.Asset) -> AssetItem:
    return AssetItem(
        id=a.id,
        brand_id=a.brand_id,
        kind=a.kind,
        subkind=a.subkind,
        url=a.url,
        storyboard_id=a.storyboard_id,
        cast_kind=a.cast_kind,
        label=a.label,
        prompt_preview=a.prompt_preview,
        duration_ms=a.duration_ms,
        aspect=a.aspect,
        meta=a.meta or {},
        description=a.description,
        tags=list(a.tags or []),
        description_status=a.description_status,
        created_at=a.created_at.isoformat(),
    )


@router.get("", response_model=AssetListResponse)
def list_assets(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    kind: Literal["image", "video"] | None = Query(None),
    subkind: str | None = Query(None),
    cast_kind: str | None = Query(None),
    limit: int = 60,
) -> AssetListResponse:
    # Seed the library from the brand's existing onboarding media (logo,
    # screenshots, product images, uploaded assets) on first call. The
    # helper is idempotent — both via an in-process cache and the
    # (brand_id, url) UniqueConstraint — so it's safe to call on every
    # request as a backstop.
    backfill_brand_assets(brand_id)

    q = db.query(models.Asset).filter(models.Asset.brand_id == brand_id)
    if kind:
        q = q.filter(models.Asset.kind == kind)
    if subkind:
        q = q.filter(models.Asset.subkind == subkind)
    if cast_kind:
        q = q.filter(models.Asset.cast_kind == cast_kind)
    total = q.count()
    rows = (
        q.order_by(models.Asset.created_at.desc())
        .limit(max(1, min(200, limit)))
        .all()
    )
    return AssetListResponse(items=[_to_item(r) for r in rows], total=total)


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    a = db.get(models.Asset, asset_id)
    if a is None:
        raise HTTPException(status_code=404, detail="asset not found")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── AI describe endpoints ───────────────────────────────────────────────
# describe_asset / describe_brand_assets are async because they call
# Gemini Vision; the FastAPI handlers therefore must be async too.


class DescribeOut(BaseModel):
    asset_id: str
    described: bool
    description: str | None
    tags: list[str]
    cast_kind: str | None


@router.post("/{asset_id}/describe", response_model=DescribeOut)
async def post_describe_asset(
    asset_id: str,
    db: Annotated[Session, Depends(get_db)],
    force: bool = Query(
        False,
        description="Re-describe even if status is already 'ready'",
    ),
) -> DescribeOut:
    """Run Gemini Vision on one asset and write description + tags +
    cast_kind back to the row. Idempotent unless ``force=true``."""
    if db.get(models.Asset, asset_id) is None:
        raise HTTPException(status_code=404, detail="asset not found")
    described = await describe_asset(asset_id, force=force)
    # Re-read the row so we return the latest persisted state — the
    # describer wrote it inside its own session.
    row = db.get(models.Asset, asset_id)
    db.refresh(row) if row is not None else None
    return DescribeOut(
        asset_id=asset_id,
        described=bool(described),
        description=(row.description if row else None),
        tags=list((row.tags if row else []) or []),
        cast_kind=(row.cast_kind if row else None),
    )


class DescribeAllOut(BaseModel):
    brand_id: str
    described_count: int


@router.post("/describe-all", response_model=DescribeAllOut)
async def post_describe_all(
    brand_id: str = Query(..., min_length=1),
    only_pending: bool = Query(
        True,
        description="When false, re-describe assets even if already ready",
    ),
) -> DescribeAllOut:
    """Catch-up describer for a brand. Walks every un-described image
    asset and runs Gemini Vision on it sequentially."""
    described = await describe_brand_assets(brand_id, only_pending=only_pending)
    return DescribeAllOut(brand_id=brand_id, described_count=described)
