"""Competitor intel API — on-demand Tavily research scoped to a single
competitor. Triggered when the user opens the watchlist insight modal.

Persisted on ``Competitor.pattern_library['intel']`` so re-opening the
modal shows the cached bundle instantly while a background refresh runs.

  POST /api/competitors/{id}/intel — kick off refresh, returns 202.
  GET  /api/competitors/{id}/intel — read cached bundle (always 200).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import SessionLocal, get_db
from app.services.research import gather_competitor_intel

router = APIRouter(prefix="/competitors")


# Cached intel older than this is considered stale; the modal still
# shows it instantly but kicks off a background refresh in the background.
STALE_AFTER_SECONDS = 60 * 60 * 6  # 6h


@router.post("/{competitor_id}/intel")
async def post_intel(
    competitor_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    comp = db.get(models.Competitor, competitor_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="competitor not found")

    own_brand_name: str | None = None
    if comp.brand_id:
        brand = db.get(models.Brand, comp.brand_id)
        if brand is not None:
            own_brand_name = brand.name

    asyncio.create_task(
        _refresh_and_persist(
            competitor_id=competitor_id,
            competitor_name=comp.name,
            competitor_url=comp.url,
            own_brand_name=own_brand_name,
        )
    )
    return {"ok": True, "competitor_id": competitor_id}


@router.get("/{competitor_id}/intel")
def get_intel(
    competitor_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    comp = db.get(models.Competitor, competitor_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="competitor not found")

    intel = (comp.pattern_library or {}).get("intel") or {}
    fetched_at = intel.get("fetched_at")
    is_stale = True
    if fetched_at:
        try:
            ts = datetime.fromisoformat(fetched_at)
            is_stale = (
                datetime.now(timezone.utc) - ts
            ).total_seconds() > STALE_AFTER_SECONDS
        except Exception:
            is_stale = True

    return {
        "competitor_id": competitor_id,
        "intel": intel,
        "is_stale": is_stale,
    }


async def _refresh_and_persist(
    *,
    competitor_id: str,
    competitor_name: str,
    competitor_url: str | None,
    own_brand_name: str | None,
) -> None:
    bundle = await gather_competitor_intel(
        competitor_id=competitor_id,
        competitor_name=competitor_name,
        competitor_url=competitor_url,
        own_brand_name=own_brand_name,
    )
    payload = bundle.to_dict()
    with SessionLocal() as cdb:
        row = cdb.get(models.Competitor, competitor_id)
        if row is None:
            return
        pattern_library = dict(row.pattern_library or {})
        pattern_library["intel"] = payload
        row.pattern_library = pattern_library
        cdb.add(row)
        cdb.commit()
