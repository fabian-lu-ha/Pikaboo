"""Audience API.

Endpoints (all under /api/audience):
  POST /connect_crm                connect a CRM provider for a brand
  POST /import                     pull customers + events + products
  GET  /customers                  list customers (with recent events)
  GET  /customers/{customer_id}    full customer + last 50 events + stats
  GET  /products                   list products
  POST /segments/propose           AI-propose 3-6 segments (does not save)
  POST /segments                   persist a segment row
  GET  /segments                   list saved segments
  GET  /segments/{segment_id}      saved segment + hydrated customer rows
  POST /personalize                draft an email for a customer or segment
  POST /dispatch                   record an EmailSend (mock — does not send)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.events.bus import bus
from app.events.types import Events
from app.services.audience.personalization import (
    personalize_for_customer,
    personalize_for_segment,
)
from app.services.audience.segmentation import propose_segments
from app.services.audience.shop_triggers import fire_shop_event
from app.services.crm import sync as crm_sync
from app.services.crm.providers import available_providers, get_provider

log = logging.getLogger(__name__)

router = APIRouter(prefix="/audience")


# ---------- CRM connection / import ----------


class ConnectIn(BaseModel):
    brand_id: str
    provider: str
    credentials: dict


@router.post("/connect_crm")
async def connect_crm(
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

    blob = {"credentials": body.credentials, "last_synced_at": None}
    brand.crm_connections = {
        **(brand.crm_connections or {}),
        body.provider: blob,
    }
    db.add(brand)
    db.commit()
    bus.emit(
        Events.AUDIENCE_CRM_CONNECTED,
        {"brand_id": body.brand_id, "provider": body.provider},
    )
    return {"ok": True}


class ImportIn(BaseModel):
    brand_id: str
    provider: str


@router.post("/import")
async def import_now(
    body: ImportIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    if body.provider not in available_providers():
        raise HTTPException(
            status_code=400, detail=f"unknown provider: {body.provider}"
        )
    counts = await crm_sync.import_all(db, body.brand_id, body.provider)
    return {"ok": True, **counts}


# ---------- Customer reads ----------


def _serialize_event(e: models.CustomerEvent) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
        "payload": e.payload or {},
    }


def _serialize_customer(c: models.Customer, recent_events: list[dict]) -> dict:
    attrs = c.attributes or {}
    return {
        "id": c.id,
        "provider": c.provider,
        "external_id": c.external_id,
        "email": c.email,
        "name": c.name,
        "phone": c.phone,
        "city": c.city,
        "country": c.country,
        "tags": list(c.tags or []),
        "attributes": attrs,
        "acquisition": dict(attrs.get("acquisition") or {}),
        "touchpoints": list(attrs.get("touchpoints") or []),
        "signup_at": c.signup_at.isoformat() if c.signup_at else None,
        "last_active_at": (
            c.last_active_at.isoformat() if c.last_active_at else None
        ),
        "total_spend_cents": int(c.total_spend_cents or 0),
        "recent_events": recent_events,
    }


@router.get("/customers")
def list_customers(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 50,
) -> dict:
    rows = (
        db.query(models.Customer)
        .filter(models.Customer.brand_id == brand_id)
        .order_by(models.Customer.last_active_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    if not rows:
        return {"customers": []}

    ids = [r.id for r in rows]
    events = (
        db.query(models.CustomerEvent)
        .filter(
            models.CustomerEvent.brand_id == brand_id,
            models.CustomerEvent.customer_id.in_(ids),
        )
        .order_by(models.CustomerEvent.occurred_at.desc())
        .all()
    )
    by_customer: dict[str, list[models.CustomerEvent]] = {cid: [] for cid in ids}
    for e in events:
        bucket = by_customer.setdefault(e.customer_id, [])
        if len(bucket) < 5:
            bucket.append(e)

    return {
        "customers": [
            _serialize_customer(
                r, [_serialize_event(e) for e in by_customer.get(r.id, [])]
            )
            for r in rows
        ]
    }


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    customer = db.get(models.Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="customer not found")

    events = (
        db.query(models.CustomerEvent)
        .filter_by(customer_id=customer_id)
        .order_by(models.CustomerEvent.occurred_at.desc())
        .limit(50)
        .all()
    )

    purchases = [e for e in events if e.kind == "purchase"]
    opens = [e for e in events if e.kind == "email_open"]
    sends = [e for e in events if e.kind in ("email_open", "email_click")]
    open_rate = (len(opens) / len(sends)) if sends else 0.0
    stats = {
        "total_spend_cents": int(customer.total_spend_cents or 0),
        "purchase_count": len(purchases),
        "open_rate": round(open_rate, 3),
        "event_count": len(events),
    }

    return {
        "customer": _serialize_customer(
            customer, [_serialize_event(e) for e in events[:5]]
        ),
        "events": [_serialize_event(e) for e in events],
        "stats": stats,
    }


@router.get("/products")
def list_products(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    rows = (
        db.query(models.Product)
        .filter(models.Product.brand_id == brand_id)
        .order_by(models.Product.created_at.desc())
        .all()
    )
    return {
        "products": [
            {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "price_cents": int(p.price_cents or 0),
                "image_url": p.image_url,
                "category": p.category,
                "tags": list(p.tags or []),
            }
            for p in rows
        ]
    }


# ---------- Segments ----------


class ProposeIn(BaseModel):
    brand_id: str


@router.post("/segments/propose")
async def propose(
    body: ProposeIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    try:
        segments = await propose_segments(db, body.brand_id)
    except Exception as e:
        log.exception("audience.propose_segments failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"segments": segments}


class CreateSegmentIn(BaseModel):
    brand_id: str
    name: str
    description: str | None = None
    rationale: str | None = None
    customer_ids: list[str]
    source: Literal["ai_proposed", "user_created"] = "user_created"


@router.post("/segments")
def create_segment(
    body: CreateSegmentIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    seg = models.Segment(
        brand_id=body.brand_id,
        name=body.name,
        description=body.description,
        rationale=body.rationale,
        customer_ids=list(body.customer_ids or []),
        source=body.source,
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    bus.emit(
        Events.AUDIENCE_SEGMENT_SAVED,
        {
            "brand_id": body.brand_id,
            "segment_id": seg.id,
            "name": seg.name,
            "size": len(seg.customer_ids or []),
            "source": seg.source,
        },
    )
    return {
        "segment": {
            "id": seg.id,
            "name": seg.name,
            "description": seg.description,
            "rationale": seg.rationale,
            "customer_ids": list(seg.customer_ids or []),
            "source": seg.source,
            "created_at": seg.created_at.isoformat() if seg.created_at else None,
        }
    }


@router.get("/segments")
def list_segments(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    rows = (
        db.query(models.Segment)
        .filter(models.Segment.brand_id == brand_id)
        .order_by(models.Segment.created_at.desc())
        .all()
    )
    return {
        "segments": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "rationale": s.rationale,
                "customer_ids": list(s.customer_ids or []),
                "size": len(s.customer_ids or []),
                "source": s.source,
                "created_at": (
                    s.created_at.isoformat() if s.created_at else None
                ),
            }
            for s in rows
        ]
    }


@router.get("/segments/{segment_id}")
def get_segment(
    segment_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    seg = db.get(models.Segment, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="segment not found")

    ids = list(seg.customer_ids or [])
    members = (
        db.query(models.Customer)
        .filter(
            models.Customer.brand_id == seg.brand_id,
            models.Customer.id.in_(ids),
        )
        .all()
        if ids
        else []
    )
    return {
        "segment": {
            "id": seg.id,
            "name": seg.name,
            "description": seg.description,
            "rationale": seg.rationale,
            "customer_ids": ids,
            "size": len(ids),
            "source": seg.source,
            "created_at": seg.created_at.isoformat() if seg.created_at else None,
            "customers": [
                {"id": m.id, "name": m.name, "email": m.email}
                for m in members
            ],
        }
    }


# ---------- Personalize + dispatch ----------


class PersonalizeIn(BaseModel):
    brand_id: str
    target_kind: Literal["customer", "segment"]
    target_id: str
    user_prompt: str | None = None


@router.post("/personalize")
async def personalize(
    body: PersonalizeIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    try:
        if body.target_kind == "customer":
            email = await personalize_for_customer(
                db, body.brand_id, body.target_id, body.user_prompt
            )
        else:
            email = await personalize_for_segment(
                db, body.brand_id, body.target_id, body.user_prompt
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        log.exception("audience.personalize failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"email": email}


class DispatchIn(BaseModel):
    brand_id: str
    target_kind: Literal["customer", "segment"]
    target_id: str
    subject: str
    body: str
    html_body: str | None = None


@router.post("/dispatch")
def dispatch(
    body: DispatchIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    if body.target_kind == "segment":
        seg = db.get(models.Segment, body.target_id)
        if seg is None or seg.brand_id != body.brand_id:
            raise HTTPException(status_code=404, detail="segment not found")
        recipient_count = len(seg.customer_ids or [])
    else:
        customer = db.get(models.Customer, body.target_id)
        if customer is None or customer.brand_id != body.brand_id:
            raise HTTPException(status_code=404, detail="customer not found")
        recipient_count = 1

    now = datetime.now(timezone.utc)
    send = models.EmailSend(
        brand_id=body.brand_id,
        target_kind=body.target_kind,
        target_id=body.target_id,
        subject=body.subject,
        body=body.body,
        html_body=body.html_body,
        status="sent",
        sent_at=now,
    )
    db.add(send)
    db.commit()
    db.refresh(send)

    bus.emit(
        Events.AUDIENCE_EMAIL_DISPATCHED,
        {
            "brand_id": body.brand_id,
            "target_kind": body.target_kind,
            "target_id": body.target_id,
            "recipient_count": recipient_count,
            "email_send_id": send.id,
        },
    )

    return {
        "ok": True,
        "email_send": {
            "id": send.id,
            "status": send.status,
            "sent_at": send.sent_at.isoformat() if send.sent_at else None,
            "recipient_count": recipient_count,
        },
    }


# ---------- Shop-event triggers ----------


class ShopTriggerIn(BaseModel):
    brand_id: str
    customer_id: str
    kind: Literal["cart_abandoned", "subscription_lapsed"]
    payload: dict = {}


@router.post("/shop_trigger")
def shop_trigger(
    body: ShopTriggerIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """Manually fire a shop event for a customer. The audience auto-personalize
    listener handles the rest (drafts an email, emits ``audience.shop_auto_personalized``)."""
    try:
        row = fire_shop_event(
            db, body.brand_id, body.customer_id, body.kind, body.payload
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "ok": True,
        "event": {
            "id": row.id,
            "kind": row.kind,
            "occurred_at": row.occurred_at.isoformat(),
            "payload": row.payload or {},
        },
    }
