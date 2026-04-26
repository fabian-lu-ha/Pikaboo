"""Research API — re-run / inspect Tavily-backed brand research.

POST /api/research/refresh — recompute and persist a brand's research bundle.
GET  /api/research/{brand_id} — return the persisted snapshot (no network).
GET  /api/research/me — convenience: returns research for the latest brand.

All endpoints degrade gracefully when ``TAVILY_API_KEY`` is unset — the
event lifecycle still fires (so the UI can render the "no key" state) and
the response carries an explanatory ``error`` field.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.services.research import gather_brand_context

router = APIRouter(prefix="/research")


class RefreshIn(BaseModel):
    brand_id: str | None = None


@router.post("/refresh")
async def refresh(
    body: RefreshIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = _resolve_brand(db, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    brand_id = brand.id
    brand_name = brand.name or ""
    brand_url = brand.url
    description = brand.description
    competitors = [{"name": c.name, "url": c.url} for c in brand.competitors]

    asyncio.create_task(
        _refresh_and_persist(
            brand_id=brand_id,
            brand_name=brand_name,
            brand_url=brand_url,
            description=description,
            competitors=competitors,
        )
    )
    return {"ok": True, "brand_id": brand_id}


@router.get("/me")
def get_me(db: Annotated[Session, Depends(get_db)]) -> dict:
    brand = _resolve_brand(db, None)
    if brand is None:
        return {"brand_id": None, "research": {}}
    return {"brand_id": brand.id, "research": brand.research or {}}


@router.get("/status")
def get_status() -> dict:
    """Lightweight probe: is the Tavily key configured? Frontend hits this
    on mount so it can render the right empty state without waiting for an
    event lifecycle."""
    from app.services.research import get_tavily

    client = get_tavily()
    return {"configured": client is not None}


@router.get("/{brand_id}")
def get_one(brand_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    return {"brand_id": brand_id, "research": brand.research or {}}


def _resolve_brand(db: Session, brand_id: str | None) -> models.Brand | None:
    if brand_id:
        return db.get(models.Brand, brand_id)
    return (
        db.query(models.Brand)
        .filter(models.Brand.onboarded_at.is_not(None))
        .order_by(models.Brand.onboarded_at.desc())
        .first()
    )


async def _refresh_and_persist(
    *,
    brand_id: str,
    brand_name: str,
    brand_url: str | None,
    description: str | None,
    competitors: list[dict],
) -> None:
    from app.db.session import SessionLocal

    bundle = await gather_brand_context(
        brand_id=brand_id,
        brand_name=brand_name,
        brand_url=brand_url,
        description=description,
        competitors=competitors,
    )
    payload = bundle.to_dict()
    with SessionLocal() as bdb:
        row = bdb.get(models.Brand, brand_id)
        if row is None:
            return
        row.research = payload
        bdb.add(row)
        bdb.commit()
