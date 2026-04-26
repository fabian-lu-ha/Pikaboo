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

  # 1:1 Personalized Campaigns & Custom Offers feature:
  POST /campaigns/plan             plan a multi-touch campaign for a target
  POST /campaigns/{id}/launch      flip status to scheduled, schedule first touch
  GET  /campaigns                  list campaigns with hydrated touches+offer
  GET  /campaigns/{id}             single campaign detail
  POST /touches/{id}/render-video  on-demand voice+video render for preview
  POST /offers                     standalone offer build (envelope-clamped)
  GET  /offers/{id}                full offer row
  GET  /policy-clamps              recent OFFER_POLICY_CLAMPED feed (trust dashboard)
  GET  /triggers                   list trigger rules + recent fires
  PUT  /triggers/{rule_id}         enable/disable a trigger rule
  GET  /brands/{id}/offer-policy   read brand offer-policy envelope
  PUT  /brands/{id}/offer-policy   write brand offer-policy envelope
  GET  /segments/{id}/offer-policy-override        read segment override
  PUT  /segments/{id}/offer-policy-override        write segment override
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
    # Optional — set when the segment is built around a single dominant
    # product feature. The video planner uses this to hero that feature
    # in any ad spot generated for the segment.
    feature_focus: str | None = None


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
        feature_focus=(body.feature_focus or None),
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    # Compute feature stats for the segment now that members are bound;
    # this also persists feature_focus when the caller didn't supply one
    # but the membership clearly centers on a single feature.
    from app.services.audience.feature_usage import attach_segment_feature_focus

    attach_segment_feature_focus(db, seg.id, commit=True)
    db.refresh(seg)

    bus.emit(
        Events.AUDIENCE_SEGMENT_SAVED,
        {
            "brand_id": body.brand_id,
            "segment_id": seg.id,
            "name": seg.name,
            "size": len(seg.customer_ids or []),
            "source": seg.source,
            "feature_focus": seg.feature_focus,
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
            "feature_focus": seg.feature_focus,
            "feature_stats": seg.feature_stats or {},
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
                "feature_focus": s.feature_focus,
                "feature_stats": s.feature_stats or {},
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


# ────────────────────────────────────────────────────────────────────────────
# 1:1 Personalized Campaigns & Custom Offers
# ────────────────────────────────────────────────────────────────────────────
#
# These routes are thin wrappers over service-layer functions. They live in
# this file (not a separate router) because the frontend already speaks one
# `/api/audience` base URL and we want to keep that shape stable.
#
# Sibling-agent modules (campaign_planner, offer_builder, triggers,
# voiceover.render_for_touch) are imported lazily inside each handler so a
# deferred sibling agent doesn't break router import — the API still
# registers, and the route returns a 503-equivalent 500 with a clear
# message until the sibling lands. Once both agents are merged, imports
# resolve at first call and every route works.

from collections import deque
from datetime import timedelta

from app.services.audience.policy_validator import (
    DEFAULT_POLICY,
    effective_policy,
)


# ---------- Policy-clamps ring buffer ----------
#
# The plan asks for a small in-memory ring buffer of recent
# OFFER_POLICY_CLAMPED events so the trust dashboard has something to render
# without us building a full event archive. 200 entries, FIFO, filterable by
# brand_id at read time.
#
# Subscribed exactly once at module import. A module-level sentinel guards
# against double-subscription if the module is re-imported (e.g. test
# harness reload, uvicorn --reload) — pyee allows multiple identical
# listeners and would double-record otherwise.

_POLICY_CLAMP_BUFFER: deque[dict] = deque(maxlen=200)
_POLICY_CLAMP_SUBSCRIBED = False


def _on_offer_policy_clamped(payload: dict) -> None:
    # Snapshot the payload — pyee handlers shouldn't mutate caller dicts and
    # we want the buffer entries immutable from the bus's perspective.
    entry = dict(payload or {})
    entry.setdefault(
        "received_at", datetime.now(timezone.utc).isoformat()
    )
    _POLICY_CLAMP_BUFFER.append(entry)


def _ensure_clamp_subscription() -> None:
    global _POLICY_CLAMP_SUBSCRIBED
    if _POLICY_CLAMP_SUBSCRIBED:
        return
    bus.on(Events.OFFER_POLICY_CLAMPED, _on_offer_policy_clamped)
    _POLICY_CLAMP_SUBSCRIBED = True


_ensure_clamp_subscription()


def _recent_clamps(brand_id: str | None, limit: int = 50) -> list[dict]:
    """Filter the ring buffer by brand_id (when provided) and cap to limit.
    Returns newest-first so the dashboard can render top-down."""
    items = list(_POLICY_CLAMP_BUFFER)
    if brand_id:
        items = [e for e in items if e.get("brand_id") == brand_id]
    items.reverse()
    return items[: max(0, int(limit))]


# ---------- Hydration helpers ----------


def _serialize_touch(t: models.CampaignTouch) -> dict:
    return {
        "id": t.id,
        "campaign_id": t.campaign_id,
        "step_index": t.step_index,
        "kind": t.kind,
        "scheduled_at": (
            t.scheduled_at.isoformat() if t.scheduled_at else None
        ),
        "content_json": dict(t.content_json or {}),
        "send_id": t.send_id,
        "render_cache_key": t.render_cache_key,
        "status": t.status,
        "sent_at": t.sent_at.isoformat() if t.sent_at else None,
    }


def _serialize_offer(o: models.Offer | None) -> dict | None:
    if o is None:
        return None
    return {
        "id": o.id,
        "brand_id": o.brand_id,
        "customer_id": o.customer_id,
        "segment_id": o.segment_id,
        "product_ids": list(o.product_ids or []),
        "rule_json": dict(o.rule_json or {}),
        "copy_json": dict(o.copy_json or {}),
        "policy_clamps": list(o.policy_clamps or []),
        "expires_at": o.expires_at.isoformat() if o.expires_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def _serialize_campaign(
    c: models.Campaign,
    touches: list[models.CampaignTouch],
    offer: models.Offer | None,
) -> dict:
    return {
        "id": c.id,
        "brand_id": c.brand_id,
        "title": c.title,
        "description": c.description,
        "target_kind": c.target_kind,
        "target_id": c.target_id,
        "trigger": c.trigger,
        "status": c.status,
        "predicted_lift": c.predicted_lift,
        "offer_id": c.offer_id,
        "bundle": dict(c.bundle or {}),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "touches": [_serialize_touch(t) for t in touches],
        "offer": _serialize_offer(offer),
    }


# ---------- Campaign plan / launch ----------


class CampaignPlanIn(BaseModel):
    brand_id: str
    target_kind: Literal["customer", "segment"]
    target_id: str
    trigger: str | None = None
    user_prompt: str | None = None


@router.post("/campaigns/plan")
async def plan_campaign_route(
    body: CampaignPlanIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    try:
        from app.services.audience.campaign_planner import plan_campaign
    except ImportError as e:
        log.exception("campaign_planner import failed")
        raise HTTPException(
            status_code=500,
            detail=f"campaign_planner not available: {e}",
        ) from e

    try:
        result = await plan_campaign(
            db,
            body.brand_id,
            body.target_kind,
            body.target_id,
            body.trigger,
            user_prompt=body.user_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        log.exception("audience.plan_campaign failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result


@router.post("/campaigns/{campaign_id}/launch")
def launch_campaign(
    campaign_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """Flip the campaign to ``scheduled`` and emit
    ``CAMPAIGN_TOUCH_SCHEDULED`` for the first touch. Actual dispatch is the
    next step (a worker / cron). This endpoint is the human's "go" button."""
    campaign = db.get(models.Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")

    touches = (
        db.query(models.CampaignTouch)
        .filter(models.CampaignTouch.campaign_id == campaign_id)
        .order_by(models.CampaignTouch.step_index)
        .all()
    )
    if not touches:
        raise HTTPException(
            status_code=400, detail="campaign has no touches to schedule"
        )

    first = touches[0]
    campaign.status = "scheduled"
    if first.scheduled_at is None:
        # Default: schedule the hook touch immediately so the demo's "Send
        # all" button results in something visible. Subsequent touches keep
        # whatever cadence the planner picked.
        first.scheduled_at = datetime.now(timezone.utc)
    if first.status == "planned":
        first.status = "scheduled"
    db.add(campaign)
    db.add(first)
    db.commit()
    db.refresh(first)

    bus.emit(
        Events.CAMPAIGN_TOUCH_SCHEDULED,
        {
            "brand_id": campaign.brand_id,
            "campaign_id": campaign.id,
            "touch_id": first.id,
            "step_index": first.step_index,
            "kind": first.kind,
            "scheduled_at": (
                first.scheduled_at.isoformat()
                if first.scheduled_at
                else None
            ),
        },
    )

    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "first_touch_id": first.id,
    }


@router.get("/campaigns")
def list_personalized_campaigns(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    target_kind: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
) -> dict:
    """List campaigns scoped to a brand with hydrated touches and offers.

    This is the *new-style* listing for 1:1 personalized campaigns —
    distinct from ``/api/campaigns/list`` which serves the legacy bundle
    library. Filters are AND-combined."""
    q = db.query(models.Campaign).filter(models.Campaign.brand_id == brand_id)
    if target_kind:
        q = q.filter(models.Campaign.target_kind == target_kind)
    if target_id:
        q = q.filter(models.Campaign.target_id == target_id)
    if status:
        q = q.filter(models.Campaign.status == status)
    rows = q.order_by(models.Campaign.created_at.desc()).all()

    campaign_ids = [c.id for c in rows]
    touches_by_campaign: dict[str, list[models.CampaignTouch]] = {
        cid: [] for cid in campaign_ids
    }
    if campaign_ids:
        for t in (
            db.query(models.CampaignTouch)
            .filter(models.CampaignTouch.campaign_id.in_(campaign_ids))
            .order_by(models.CampaignTouch.step_index)
            .all()
        ):
            touches_by_campaign.setdefault(t.campaign_id, []).append(t)

    offer_ids = [c.offer_id for c in rows if c.offer_id]
    offers_by_id: dict[str, models.Offer] = {}
    if offer_ids:
        for o in (
            db.query(models.Offer)
            .filter(models.Offer.id.in_(offer_ids))
            .all()
        ):
            offers_by_id[o.id] = o

    return {
        "campaigns": [
            _serialize_campaign(
                c,
                touches_by_campaign.get(c.id, []),
                offers_by_id.get(c.offer_id) if c.offer_id else None,
            )
            for c in rows
        ]
    }


@router.get("/campaigns/{campaign_id}")
def get_personalized_campaign(
    campaign_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    c = db.get(models.Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    touches = (
        db.query(models.CampaignTouch)
        .filter(models.CampaignTouch.campaign_id == campaign_id)
        .order_by(models.CampaignTouch.step_index)
        .all()
    )
    offer = (
        db.get(models.Offer, c.offer_id) if c.offer_id else None
    )
    return {"campaign": _serialize_campaign(c, touches, offer)}


# ---------- Touch video render ----------


@router.post("/touches/{touch_id}/render-video")
async def render_touch_video(
    touch_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    touch = db.get(models.CampaignTouch, touch_id)
    if touch is None:
        raise HTTPException(status_code=404, detail="touch not found")

    try:
        from app.services.video_gen.voiceover import render_for_touch
    except ImportError as e:
        log.exception("voiceover.render_for_touch import failed")
        raise HTTPException(
            status_code=500,
            detail=f"voiceover.render_for_touch not available: {e}",
        ) from e

    try:
        result = await render_for_touch(db, touch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        log.exception("audience.render_touch_video failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result


# ---------- Offers ----------


class OfferBuildIn(BaseModel):
    brand_id: str
    customer_id: str | None = None
    segment_id: str | None = None
    user_prompt: str | None = None


@router.post("/offers")
async def build_offer_route(
    body: OfferBuildIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    if body.customer_id and body.segment_id:
        raise HTTPException(
            status_code=400,
            detail="set exactly one of customer_id or segment_id, not both",
        )
    if not body.customer_id and not body.segment_id:
        raise HTTPException(
            status_code=400,
            detail="must provide one of customer_id or segment_id",
        )

    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    if body.customer_id:
        customer = db.get(models.Customer, body.customer_id)
        if customer is None or customer.brand_id != body.brand_id:
            raise HTTPException(status_code=404, detail="customer not found")
    if body.segment_id:
        seg = db.get(models.Segment, body.segment_id)
        if seg is None or seg.brand_id != body.brand_id:
            raise HTTPException(status_code=404, detail="segment not found")

    try:
        from app.services.audience.offer_builder import build_offer
    except ImportError as e:
        log.exception("offer_builder import failed")
        raise HTTPException(
            status_code=500,
            detail=f"offer_builder not available: {e}",
        ) from e

    try:
        result = await build_offer(
            db,
            body.brand_id,
            customer_id=body.customer_id,
            segment_id=body.segment_id,
            user_prompt=body.user_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        log.exception("audience.build_offer failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result


@router.get("/offers/{offer_id}")
def get_offer(
    offer_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    offer = db.get(models.Offer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")
    return {"offer": _serialize_offer(offer)}


# ---------- Policy clamps trust dashboard ----------


@router.get("/policy-clamps")
def list_policy_clamps(brand_id: str, limit: int = 50) -> dict:
    """Read-only feed of recent ``OFFER_POLICY_CLAMPED`` events for the
    trust dashboard. Backed by an in-memory ring buffer (last 200 events
    globally), filtered by brand_id at read time. Restarts wipe the
    history — that's intentional; events are still in the bus log."""
    return {"clamps": _recent_clamps(brand_id, limit)}


# ---------- Triggers ----------


class TriggerToggleIn(BaseModel):
    enabled: bool


@router.get("/triggers")
def list_triggers(brand_id: str | None = None) -> dict:
    try:
        from app.services.audience import triggers as trig_mod
    except ImportError as e:
        log.exception("triggers import failed")
        raise HTTPException(
            status_code=500,
            detail=f"triggers module not available: {e}",
        ) from e
    try:
        rules = trig_mod.enabled_rules()
        fires = trig_mod.recent_fires(brand_id, 20) if brand_id else []
    except Exception as e:
        log.exception("audience.list_triggers failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"rules": rules, "recent_fires": fires}


@router.put("/triggers/{rule_id}")
def set_trigger(rule_id: str, body: TriggerToggleIn) -> dict:
    try:
        from app.services.audience import triggers as trig_mod
    except ImportError as e:
        log.exception("triggers import failed")
        raise HTTPException(
            status_code=500,
            detail=f"triggers module not available: {e}",
        ) from e
    try:
        return trig_mod.set_rule_enabled(rule_id, body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        log.exception("audience.set_trigger failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------- Brand / Segment offer-policy CRUD ----------


class OfferPolicyIn(BaseModel):
    policy: dict


class OfferPolicyOverrideIn(BaseModel):
    override: dict


@router.get("/brands/{brand_id}/offer-policy")
def get_brand_offer_policy(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    policy = dict(brand.offer_policy or {})
    return {
        "policy": policy,
        "effective": effective_policy(policy, None),
        "defaults": dict(DEFAULT_POLICY),
    }


@router.put("/brands/{brand_id}/offer-policy")
def put_brand_offer_policy(
    brand_id: str,
    body: OfferPolicyIn,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    brand.offer_policy = dict(body.policy or {})
    db.add(brand)
    db.commit()
    db.refresh(brand)
    policy = dict(brand.offer_policy or {})
    return {
        "policy": policy,
        "effective": effective_policy(policy, None),
        "defaults": dict(DEFAULT_POLICY),
    }


@router.get("/segments/{segment_id}/offer-policy-override")
def get_segment_policy_override(
    segment_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    seg = db.get(models.Segment, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="segment not found")
    brand = db.get(models.Brand, seg.brand_id)
    override = dict(seg.offer_policy_override or {})
    brand_policy = dict((brand.offer_policy if brand else {}) or {})
    return {
        "override": override,
        "effective": effective_policy(brand_policy, override),
    }


@router.put("/segments/{segment_id}/offer-policy-override")
def put_segment_policy_override(
    segment_id: str,
    body: OfferPolicyOverrideIn,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    seg = db.get(models.Segment, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="segment not found")
    seg.offer_policy_override = dict(body.override or {})
    db.add(seg)
    db.commit()
    db.refresh(seg)
    brand = db.get(models.Brand, seg.brand_id)
    override = dict(seg.offer_policy_override or {})
    brand_policy = dict((brand.offer_policy if brand else {}) or {})
    return {
        "override": override,
        "effective": effective_policy(brand_policy, override),
    }


# `timedelta` import kept above for future scheduled-cadence handling in
# launch_campaign — currently scheduled_at defaults to "now" but a follow-up
# may use planner-supplied offsets.
_ = timedelta


# ── Feature usage ────────────────────────────────────────────────────────
# Three views over CustomerEvent rows whose kind == 'feature_use':
#   - brand-wide distribution (which features are most used, by how many?)
#   - per-customer top features
#   - per-segment stats (with focus + contributor counts)
# Plus a bulk ingest endpoint so demos / webhooks can seed events.


class FeatureDistributionItem(BaseModel):
    feature: str
    customer_count: int
    event_count: int
    last_seen: str | None = None


class FeatureDistributionOut(BaseModel):
    brand_id: str
    items: list[FeatureDistributionItem]


@router.get("/feature-usage", response_model=FeatureDistributionOut)
def get_feature_distribution(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> FeatureDistributionOut:
    """Brand-wide feature distribution. Sorted by distinct customer count
    desc — the planner reads this to decide which feature has a large-
    enough cohort to be a video subject."""
    from app.services.audience.feature_usage import (
        compute_brand_feature_distribution,
    )

    items = compute_brand_feature_distribution(db, brand_id)
    return FeatureDistributionOut(
        brand_id=brand_id,
        items=[FeatureDistributionItem(**i) for i in items],
    )


class CustomerFeatureItem(BaseModel):
    feature: str
    count: int
    last_used: str | None = None


class CustomerFeaturesOut(BaseModel):
    customer_id: str
    items: list[CustomerFeatureItem]


@router.get(
    "/feature-usage/customer/{customer_id}",
    response_model=CustomerFeaturesOut,
)
def get_customer_features(
    customer_id: str, db: Annotated[Session, Depends(get_db)]
) -> CustomerFeaturesOut:
    from app.services.audience.feature_usage import (
        compute_customer_top_features,
    )

    return CustomerFeaturesOut(
        customer_id=customer_id,
        items=[
            CustomerFeatureItem(**i)
            for i in compute_customer_top_features(db, customer_id)
        ],
    )


class SegmentFeatureStatsOut(BaseModel):
    segment_id: str
    focus: str | None = None
    stats: dict[str, int]
    contributor_counts: dict[str, int]


@router.get(
    "/feature-usage/segment/{segment_id}",
    response_model=SegmentFeatureStatsOut,
)
def get_segment_features(
    segment_id: str, db: Annotated[Session, Depends(get_db)]
) -> SegmentFeatureStatsOut:
    from app.services.audience.feature_usage import (
        compute_segment_feature_stats,
    )

    out = compute_segment_feature_stats(db, segment_id)
    return SegmentFeatureStatsOut(
        segment_id=segment_id,
        focus=out["focus"],
        stats=out["stats"],
        contributor_counts=out["contributor_counts"],
    )


class FeatureEventIn(BaseModel):
    customer_id: str
    feature: str
    occurred_at: str | None = None
    properties: dict | None = None


class FeatureEventsBulkIn(BaseModel):
    brand_id: str
    events: list[FeatureEventIn]


class FeatureEventsBulkOut(BaseModel):
    written: int


@router.post("/feature-events", response_model=FeatureEventsBulkOut)
def post_feature_events(
    body: FeatureEventsBulkIn, db: Annotated[Session, Depends(get_db)]
) -> FeatureEventsBulkOut:
    """Bulk ingest path — demos seed events, webhooks land them. Each
    event becomes a CustomerEvent kind='feature_use'."""
    from app.services.audience.feature_usage import bulk_track_features

    rows = [e.model_dump() for e in body.events]
    written = bulk_track_features(db, body.brand_id, rows)
    return FeatureEventsBulkOut(written=written)
