"""Kanban connection + webhook API.

Endpoints (all under /api/kanban):
  POST /test                      verify creds (round-trip the API)
  POST /connect                   store creds for a brand
  GET  /boards                    list boards on the connected provider
  POST /select                    pick which boards to sync
  POST /sync                      kick off a backfill
  GET  /cards                     last N cards persisted for this brand
  POST /webhook/{provider}/{brand_id}   provider callback
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.events.bus import bus
from app.events.types import Events
from app.services.kanban import sync as kanban_sync
from app.services.kanban.providers import available_providers, get_provider
from app.services.kanban.types import ProviderConnection

log = logging.getLogger(__name__)

router = APIRouter(prefix="/kanban")


class TestIn(BaseModel):
    provider: str
    credentials: dict


class TestOut(BaseModel):
    ok: bool


@router.post("/test", response_model=TestOut)
async def test_connection(body: TestIn) -> TestOut:
    try:
        impl = get_provider(body.provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        ok = await impl.test_connection(body.credentials)
    except Exception as e:  # noqa: BLE001
        log.warning("kanban.test failed for %s: %s", body.provider, e)
        return TestOut(ok=False)
    return TestOut(ok=ok)


class ConnectIn(BaseModel):
    brand_id: str
    provider: str
    credentials: dict


@router.post("/connect")
async def connect(
    body: ConnectIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    if body.provider not in available_providers():
        raise HTTPException(
            status_code=400, detail=f"unknown provider: {body.provider}"
        )
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    impl = get_provider(body.provider)
    try:
        ok = await impl.test_connection(body.credentials)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"connection test failed: {e}"
        ) from e
    if not ok:
        raise HTTPException(status_code=400, detail="invalid credentials")

    blob = {
        "credentials": body.credentials,
        "selected_boards": [],
        "webhook_id": None,
        "last_synced_at": None,
    }
    brand.kanban_connections = {
        **(brand.kanban_connections or {}),
        body.provider: blob,
    }
    db.add(brand)
    db.commit()
    bus.emit(
        Events.KANBAN_CONNECTED,
        {"brand_id": body.brand_id, "provider": body.provider},
    )
    return {"ok": True}


@router.get("/boards")
async def list_boards(
    brand_id: str,
    provider: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    blob = (brand.kanban_connections or {}).get(provider)
    if not blob:
        raise HTTPException(status_code=400, detail="provider not connected")

    conn = ProviderConnection(
        provider=provider,
        credentials=blob.get("credentials") or {},
        selected_boards=list(blob.get("selected_boards") or []),
    )
    impl = get_provider(provider)
    try:
        boards = await impl.list_boards(conn)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"list_boards failed: {e}"
        ) from e
    return {"boards": boards}


class SelectIn(BaseModel):
    brand_id: str
    provider: str
    board_ids: list[str]


@router.post("/select")
def select_boards(
    body: SelectIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    blob = (brand.kanban_connections or {}).get(body.provider)
    if not blob:
        raise HTTPException(status_code=400, detail="provider not connected")
    blob["selected_boards"] = body.board_ids
    brand.kanban_connections = {
        **(brand.kanban_connections or {}),
        body.provider: blob,
    }
    db.add(brand)
    db.commit()
    return {"ok": True}


class SyncIn(BaseModel):
    brand_id: str
    provider: str
    days: int = 30


@router.post("/sync")
async def sync_now(
    body: SyncIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    count = await kanban_sync.backfill(
        db, body.brand_id, body.provider, days=body.days
    )
    return {"ok": True, "card_count": count}


@router.get("/cards")
def list_cards(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 50,
) -> dict:
    rows = (
        db.query(models.KanbanCard)
        .filter(models.KanbanCard.brand_id == brand_id)
        .order_by(models.KanbanCard.moved_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    return {
        "cards": [
            {
                "external_id": r.external_id,
                "provider": r.provider,
                "board_name": r.board_name,
                "column": r.column,
                "title": r.title,
                "description": r.description,
                "labels": r.labels or [],
                "url": r.url,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "moved_at": r.moved_at.isoformat() if r.moved_at else None,
            }
            for r in rows
        ]
    }


@router.post("/webhook/{provider}/{brand_id}")
async def webhook(
    provider: str,
    brand_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    if provider not in available_providers():
        raise HTTPException(
            status_code=400, detail=f"unknown provider: {provider}"
        )
    payload = await request.json()
    headers = dict(request.headers)
    handled = await kanban_sync.handle_webhook(
        db, provider, brand_id, payload, headers
    )
    return {"ok": True, "handled": handled}
