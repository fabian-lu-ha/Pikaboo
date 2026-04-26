"""Shop-event simulator + auto-personalize listener.

Two roles:

1. ``fire_shop_event`` records a CustomerEvent of one of the shop kinds
   (``cart_abandoned``, ``subscription_lapsed``) and emits
   ``audience.shop_event_triggered`` so downstream listeners can react.

2. ``register()`` wires a bus listener that responds to that event by
   running ``personalize_for_customer`` against the customer who just had
   the shop event — the email lands in the preview queue (no auto-send).
   This is the "automate shop campaigns" loop.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.audience.personalization import personalize_for_customer

log = logging.getLogger(__name__)

ShopEventKind = Literal["cart_abandoned", "subscription_lapsed"]


def fire_shop_event(
    db: Session,
    brand_id: str,
    customer_id: str,
    kind: ShopEventKind,
    payload: dict,
) -> models.CustomerEvent:
    """Record a shop CustomerEvent and emit the trigger event.

    Caller (the API endpoint) owns the request-scoped DB session. The
    auto-personalize listener uses its own short-lived SessionLocal so it
    doesn't hold the request session past response.
    """
    customer = db.get(models.Customer, customer_id)
    if customer is None or customer.brand_id != brand_id:
        raise ValueError(f"customer {customer_id} not found for brand")

    now = datetime.now(timezone.utc)
    row = models.CustomerEvent(
        brand_id=brand_id,
        customer_id=customer_id,
        kind=kind,
        occurred_at=now,
        payload=payload or {},
    )
    db.add(row)
    customer.last_active_at = now
    db.commit()
    db.refresh(row)

    bus.emit(
        Events.AUDIENCE_SHOP_EVENT_TRIGGERED,
        {
            "brand_id": brand_id,
            "customer_id": customer_id,
            "kind": kind,
            "event_id": row.id,
            "payload": payload or {},
        },
    )
    log.info("shop trigger %s for %s", kind, customer_id)
    return row


_TRIGGER_PROMPT: dict[str, str] = {
    "cart_abandoned": (
        "The customer just abandoned a cart. Write a friendly nudge that "
        "acknowledges the items they left without being pushy — frame it "
        "as 'we held this for you' rather than 'don't miss out'."
    ),
    "subscription_lapsed": (
        "The customer's subscription just lapsed. Write a warm win-back "
        "with one specific reason this brand is still worth coming back to "
        "based on their history. Offer a small no-strings incentive only "
        "if it fits the brand voice."
    ),
}


async def _on_shop_event(payload: dict) -> None:
    brand_id = payload.get("brand_id")
    customer_id = payload.get("customer_id")
    kind = payload.get("kind")
    if not brand_id or not customer_id or not kind:
        return

    user_prompt = (
        _TRIGGER_PROMPT.get(kind)
        or f"Trigger: {kind}. Write the email AS A RESPONSE to this event."
    )

    db = SessionLocal()
    try:
        result = await personalize_for_customer(
            db, brand_id, customer_id, user_prompt
        )
    except Exception:
        log.exception("audience: shop auto-personalize failed")
        return
    finally:
        db.close()

    bus.emit(
        Events.AUDIENCE_SHOP_AUTO_PERSONALIZED,
        {
            "brand_id": brand_id,
            "customer_id": customer_id,
            "trigger_kind": kind,
            "subject_preview": (result.get("subject") or "")[:80],
            "recommended_product_ids": result.get(
                "recommended_product_ids", []
            ),
        },
    )


def register() -> None:
    """Idempotent listener registration. Safe to call once at startup."""
    bus.on(Events.AUDIENCE_SHOP_EVENT_TRIGGERED, _on_shop_event)
