"""Standalone offer generation.

Smaller, faster sibling of ``campaign_planner.plan_campaign`` — produces
the offer JSON only (no email or video copy). Same trust pattern: build
a redacted brief, render the brand's offer policy as a hard constraint
in the system prompt, run the LLM, clamp the response with
``policy_validator.clamp``, persist the row, emit ``OFFER_GENERATED`` and
one ``OFFER_POLICY_CLAMPED`` per clamp event. Unknown product ids are
dropped before persistence.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.events.bus import bus
from app.events.types import Events
from app.services.audience import policy_validator
from app.services.llm.client import chat_json
from app.services.pii import redactor

log = logging.getLogger(__name__)


OFFER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "discount_pct": {"type": "integer"},
        "discount_type": {"type": "string"},
        "product_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "addons": {
            "type": "array",
            "items": {"type": "string"},
        },
        "expiration_days": {"type": "integer"},
        "copy": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cta": {"type": "string"},
                "headline": {"type": "string"},
            },
            "required": ["subject", "body", "cta", "headline"],
        },
        "reasoning": {"type": "string"},
    },
    "required": [
        "discount_pct",
        "discount_type",
        "product_ids",
        "addons",
        "expiration_days",
        "copy",
        "reasoning",
    ],
}


def _entity_summary(entities: list[dict]) -> dict[str, Any]:
    types = sorted({e["type"] for e in entities})
    return {"entity_count": len(entities), "types": types}


def _voice_brief(brand: models.Brand) -> str:
    voice = brand.voice_profile or {}
    bits: list[str] = []
    if voice.get("tone"):
        bits.append(f"tone: {voice['tone']}")
    if voice.get("style"):
        bits.append(f"style: {voice['style']}")
    if voice.get("themes"):
        bits.append(f"themes: {', '.join(voice['themes'])}")
    return " | ".join(bits) if bits else "no voice profile yet"


def _product_catalog_text(products: list[models.Product]) -> str:
    lines = []
    for p in products:
        lines.append(
            f"- id={p.id} name={p.name} category={p.category or 'general'} "
            f"price=${(p.price_cents or 0) / 100:.2f}"
        )
    return "\n".join(lines)


def _build_customer_brief(
    customer: models.Customer,
    events: list[models.CustomerEvent],
) -> str:
    activity_lines: list[str] = []
    for e in events:
        p = e.payload or {}
        when = e.occurred_at.date().isoformat() if e.occurred_at else "?"
        if e.kind == "purchase":
            activity_lines.append(
                f"{when} purchase: {p.get('product_name') or p.get('product_id')}"
            )
        elif e.kind == "page_view":
            activity_lines.append(f"{when} page_view: {p.get('path') or ''}")
        elif e.kind in ("cart_abandoned", "subscription_lapsed"):
            activity_lines.append(f"{when} {e.kind}: {p}")
    return (
        f"Customer name: {customer.name or '(unknown)'}\n"
        f"Email: {customer.email}\n"
        f"City: {customer.city or '(unknown)'}, {customer.country or ''}\n"
        f"Tags: {', '.join(customer.tags or []) or '(none)'}\n"
        f"Total spend: ${(customer.total_spend_cents or 0) / 100:.2f}\n"
        "Recent activity:\n"
        + ("\n".join(activity_lines) or "(no activity)")
    )


def _build_segment_brief(
    segment: models.Segment,
    members: list[models.Customer],
    member_events: list[models.CustomerEvent],
) -> str:
    archetypes = Counter(
        (m.attributes or {}).get("archetype_label", "unknown") for m in members
    )
    purchase_categories = Counter(
        (e.payload or {}).get("category")
        for e in member_events
        if e.kind == "purchase" and (e.payload or {}).get("category")
    )
    top_products = Counter(
        (e.payload or {}).get("product_name")
        for e in member_events
        if e.kind == "purchase" and (e.payload or {}).get("product_name")
    )
    return (
        f"Segment: {segment.name}\n"
        f"Description: {segment.description or '(none)'}\n"
        f"Size: {len(members)} members\n"
        f"Top archetypes: {dict(archetypes.most_common(3))}\n"
        f"Top purchased categories: "
        f"{dict(purchase_categories.most_common(3))}\n"
        f"Top purchased products: {dict(top_products.most_common(3))}"
    )


async def build_offer(
    db: Session,
    brand_id: str,
    *,
    customer_id: str | None = None,
    segment_id: str | None = None,
    user_prompt: str | None = None,
) -> dict:
    """Generate a single offer for a customer or segment.

    Exactly one of ``customer_id`` / ``segment_id`` must be set. Persists
    one ``Offer`` row, emits ``OFFER_GENERATED`` once and
    ``OFFER_POLICY_CLAMPED`` per clamp event, and returns the offer as a
    dict.
    """
    if bool(customer_id) == bool(segment_id):
        raise ValueError(
            "build_offer: exactly one of customer_id/segment_id required"
        )

    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise ValueError(f"brand {brand_id} not found")

    customer: models.Customer | None = None
    segment: models.Segment | None = None
    if customer_id:
        customer = db.get(models.Customer, customer_id)
        if customer is None or customer.brand_id != brand_id:
            raise ValueError(f"customer {customer_id} not found for brand")
        events = (
            db.query(models.CustomerEvent)
            .filter_by(brand_id=brand_id, customer_id=customer_id)
            .order_by(models.CustomerEvent.occurred_at.desc())
            .limit(20)
            .all()
        )
        brief_text = _build_customer_brief(customer, events)
    else:
        segment = db.get(models.Segment, segment_id)
        if segment is None or segment.brand_id != brand_id:
            raise ValueError(f"segment {segment_id} not found for brand")
        member_ids: list[str] = list(segment.customer_ids or [])
        members = (
            db.query(models.Customer)
            .filter(
                models.Customer.brand_id == brand_id,
                models.Customer.id.in_(member_ids),
            )
            .all()
            if member_ids
            else []
        )
        member_events: list[models.CustomerEvent] = []
        if members:
            member_events = (
                db.query(models.CustomerEvent)
                .filter(
                    models.CustomerEvent.brand_id == brand_id,
                    models.CustomerEvent.customer_id.in_(
                        [m.id for m in members]
                    ),
                )
                .all()
            )
        brief_text = _build_segment_brief(segment, members, member_events)

    products = db.query(models.Product).filter_by(brand_id=brand_id).all()

    redaction = redactor.redact(brief_text)
    bus.emit(
        Events.AUDIENCE_PII_REDACTED,
        {"brand_id": brand_id, **_entity_summary(redaction.entities)},
    )

    eff_policy = policy_validator.effective_policy(
        brand.offer_policy or {},
        (segment.offer_policy_override if segment else None),
    )
    policy_block = policy_validator.policy_to_prompt(eff_policy)

    system = (
        "You are a marketing strategist designing one product offer. "
        "Output strictly within the offer policy envelope. The brief "
        "uses placeholder tokens like [NAME_1] / [EMAIL_1] — keep them "
        "verbatim where you'd reference the recipient; the system "
        "rehydrates after.\n\n" + policy_block
    )
    user = (
        f"Brand voice: {_voice_brief(brand)}\n\n"
        f"Recipient brief (PII redacted):\n{redaction.redacted_text}\n\n"
        f"Product catalog:\n{_product_catalog_text(products)}\n\n"
        f"User instruction: {user_prompt or '(none — use your judgment)'}\n\n"
        "Compose ONE offer JSON: pick 1-3 product_ids from the catalog, "
        "choose discount_pct + discount_type within the envelope, and "
        "write short copy (subject/body/cta/headline). Output schema: "
        "{discount_pct, discount_type, product_ids, addons, "
        "expiration_days, copy:{subject,body,cta,headline}, reasoning}."
    )

    raw = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        schema=OFFER_SCHEMA,
    )

    valid_ids = {p.id for p in products}
    raw_pids = [pid for pid in (raw.get("product_ids") or []) if pid in valid_ids]
    raw["product_ids"] = raw_pids

    copy = raw.get("copy") or {}
    rehydrated_copy = {
        k: redactor.rehydrate(str(copy.get(k) or ""), redaction.mapping)
        for k in ("subject", "body", "cta", "headline")
    }
    raw["copy"] = rehydrated_copy
    raw["reasoning"] = redactor.rehydrate(
        str(raw.get("reasoning") or ""), redaction.mapping
    )

    clamped, clamp_log = policy_validator.clamp(raw, eff_policy)
    for event in clamp_log:
        bus.emit(
            Events.OFFER_POLICY_CLAMPED,
            {
                "brand_id": brand_id,
                "target_kind": "customer" if customer_id else "segment",
                "target_id": customer_id or segment_id,
                **event,
            },
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=int(clamped.get("expiration_days") or eff_policy["expiration_max_days"])
    )
    rule_json = {
        "discount_pct": clamped.get("discount_pct"),
        "discount_type": clamped.get("discount_type"),
        "addons": clamped.get("addons") or [],
    }
    offer_row = models.Offer(
        brand_id=brand_id,
        customer_id=customer_id,
        segment_id=segment_id,
        product_ids=clamped.get("product_ids") or [],
        rule_json=rule_json,
        copy_json=clamped.get("copy") or {},
        policy_clamps=clamp_log,
        expires_at=expires_at,
    )
    db.add(offer_row)
    db.commit()
    db.refresh(offer_row)

    bus.emit(
        Events.OFFER_GENERATED,
        {
            "brand_id": brand_id,
            "offer_id": offer_row.id,
            "customer_id": customer_id,
            "segment_id": segment_id,
            "product_count": len(offer_row.product_ids or []),
            "discount_pct": rule_json["discount_pct"],
            "discount_type": rule_json["discount_type"],
            "policy_clamp_count": len(clamp_log),
        },
    )

    return {
        "offer_id": offer_row.id,
        "brand_id": brand_id,
        "customer_id": customer_id,
        "segment_id": segment_id,
        "product_ids": offer_row.product_ids or [],
        "rule_json": rule_json,
        "copy": offer_row.copy_json or {},
        "expires_at": expires_at.isoformat(),
        "policy_clamps": clamp_log,
        "reasoning": clamped.get("reasoning") or "",
        "redaction_summary": _entity_summary(redaction.entities),
    }
