"""Multi-touch 1:1 campaign planning.

Sibling of ``offer_builder``; same trust pattern, richer output. ONE
LLM call returns the touch sequence AND the bundled offer in a single
shot so tone stays coherent across email / voiceover / landing copy
and one PII redact pass covers everything.

Persistence: one ``Campaign`` (status="draft"), one ``Offer``, N
``CampaignTouch`` rows (one per step). The offer's policy clamps are
recorded on the Offer row and surfaced to the trust dashboard via the
``OFFER_POLICY_CLAMPED`` event stream.
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
from app.services.audience import renderer as email_renderer
from app.services.llm.client import chat_json
from app.services.pii import redactor

log = logging.getLogger(__name__)


# Per-target touch counts. Customer flow gets the full multi-touch sequence
# the demo storyboard renders; segment flow stays short and templatey since
# it's a single template fanned out via merge tags.
_CUSTOMER_MIN_TOUCHES = 3
_CUSTOMER_MAX_TOUCHES = 5
_SEGMENT_TOUCH_COUNT = 3

# Default cadence in days. The LLM proposes per-touch offsets; if it skips
# the field we walk these defaults.
_DEFAULT_OFFSETS = (0, 2, 4, 6, 8)


CAMPAIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "touches": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "step_index": {"type": "integer"},
                    "kind": {
                        "type": "string",
                        "enum": ["email", "video", "landing"],
                    },
                    "scheduled_offset_days": {"type": "integer"},
                    "email_subject": {"type": "string"},
                    "email_body": {"type": "string"},
                    "voiceover_script": {"type": "string"},
                    "landing_headline": {"type": "string"},
                    "landing_body": {"type": "string"},
                },
                "required": ["step_index", "kind", "scheduled_offset_days"],
            },
        },
        "offer": {
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
        },
    },
    "required": ["title", "touches", "offer"],
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
    if voice.get("dos"):
        bits.append(f"do: {'; '.join(voice['dos'])}")
    if voice.get("donts"):
        bits.append(f"avoid: {'; '.join(voice['donts'])}")
    return " | ".join(bits) if bits else "no voice profile yet"


def _product_catalog_text(products: list[models.Product]) -> str:
    lines = []
    for p in products:
        lines.append(
            f"- id={p.id} name={p.name} category={p.category or 'general'} "
            f"price=${(p.price_cents or 0) / 100:.2f}: "
            f"{(p.description or '')[:140]}"
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
                f"{when} purchase: "
                f"{p.get('product_name') or p.get('product_id')}"
            )
        elif e.kind == "email_click":
            activity_lines.append(
                f"{when} email_click: {p.get('subject') or ''} "
                f"-> {p.get('link') or ''}"
            )
        elif e.kind == "email_open":
            activity_lines.append(
                f"{when} email_open: {p.get('subject') or ''}"
            )
        elif e.kind == "page_view":
            activity_lines.append(
                f"{when} page_view: {p.get('path') or ''}"
            )
        elif e.kind in ("cart_abandoned", "subscription_lapsed"):
            activity_lines.append(f"{when} {e.kind}: {p}")
        elif e.kind == "support_msg":
            activity_lines.append(
                f"{when} support: {p.get('topic') or 'general'}"
            )
    attrs = customer.attributes or {}
    acq = attrs.get("acquisition") or {}
    acq_line = (
        f"first-touch: {acq.get('source','?')} — {acq.get('campaign','')}"
        if acq
        else "first-touch: unknown"
    )
    return (
        f"Customer name: {customer.name or '(unknown)'}\n"
        f"Email: {customer.email}\n"
        f"Phone: {customer.phone or '(none)'}\n"
        f"City: {customer.city or '(unknown)'}, {customer.country or ''}\n"
        f"Tags: {', '.join(customer.tags or []) or '(none)'}\n"
        f"Acquisition: {acq_line}\n"
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
        (m.attributes or {}).get("archetype_label", "unknown")
        for m in members
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


def _trigger_preamble(trigger: str | None) -> str:
    """Short directive that primes the LLM on why this campaign exists.
    Empty string for ``manual`` so the planner doesn't invent a fake reason."""
    if not trigger or trigger == "manual":
        return ""
    table = {
        "cart_abandoned": (
            "TRIGGER: this customer abandoned a cart. The hook touch "
            "should reference that abandonment honestly without sounding "
            "creepy or surveillance-y."
        ),
        "subscription_lapsed": (
            "TRIGGER: this customer's subscription lapsed. Reactivation "
            "tone — warm, low-pressure, acknowledge the gap."
        ),
        "new_arrival_in_category": (
            "TRIGGER: a new product arrived in a category this customer "
            "has bought before. Position the launch as relevant to their "
            "history, not as a generic announcement."
        ),
    }
    return table.get(trigger, "")


def _system_prompt_customer(
    brand: models.Brand,
    eff_policy: dict,
    trigger: str | None,
) -> str:
    blocks = [
        (
            "You are a marketing strategist designing a multi-touch 1:1 "
            "campaign for ONE recipient. Output strictly within the offer "
            "policy envelope. The customer brief uses placeholder tokens "
            "like [NAME_1] / [EMAIL_1] / [PHONE_1] — keep them verbatim "
            "where you'd reference the person; the system rehydrates."
        ),
        policy_validator.policy_to_prompt(eff_policy),
        (
            f"Brand voice: {_voice_brief(brand)}\n"
            f"Produce {_CUSTOMER_MIN_TOUCHES}-{_CUSTOMER_MAX_TOUCHES} "
            "touches total. The first touch MUST be kind='email' "
            "(the hook). Subsequent touches mix email / video / landing. "
            "Use exactly one video touch (with a 15-30s conversational "
            "voiceover_script — no headers, no CTA buttons, just spoken "
            "lines that reference 1-2 personal signals). Use one offer "
            "email near the end that delivers the bundled offer. "
            "scheduled_offset_days: 0 for the hook, then ascending."
        ),
    ]
    pre = _trigger_preamble(trigger)
    if pre:
        blocks.append(pre)
    return "\n\n".join(blocks)


def _system_prompt_segment(
    brand: models.Brand,
    eff_policy: dict,
    trigger: str | None,
) -> str:
    blocks = [
        (
            "You are a marketing strategist designing a templated campaign "
            "for a whole segment. Use the merge tag {customer_name} where "
            "you'd address the recipient — never invent a specific name. "
            "Keep references general (segment-level patterns, not "
            "individual). Output strictly within the offer policy envelope."
        ),
        policy_validator.policy_to_prompt(eff_policy),
        (
            f"Brand voice: {_voice_brief(brand)}\n"
            f"Produce exactly {_SEGMENT_TOUCH_COUNT} email touches "
            "(no video, no landing). Cadence: hook at offset 0, "
            "reminder at offset 3, offer at offset 6."
        ),
    ]
    pre = _trigger_preamble(trigger)
    if pre:
        blocks.append(pre)
    return "\n\n".join(blocks)


def _emit_clamps(
    brand_id: str,
    target_kind: str,
    target_id: str,
    clamp_log: list[dict],
) -> None:
    for event in clamp_log:
        bus.emit(
            Events.OFFER_POLICY_CLAMPED,
            {
                "brand_id": brand_id,
                "target_kind": target_kind,
                "target_id": target_id,
                **event,
            },
        )


def _rehydrate_touch(touch: dict, mapping: dict[str, str]) -> dict:
    rehyd = redactor.rehydrate
    out = dict(touch)
    for field in (
        "email_subject",
        "email_body",
        "voiceover_script",
        "landing_headline",
        "landing_body",
    ):
        if out.get(field):
            out[field] = rehyd(str(out[field]), mapping)
    return out


def _rehydrate_offer(raw: dict, mapping: dict[str, str]) -> dict:
    rehyd = redactor.rehydrate
    out = dict(raw)
    copy = out.get("copy") or {}
    out["copy"] = {
        k: rehyd(str(copy.get(k) or ""), mapping)
        for k in ("subject", "body", "cta", "headline")
    }
    out["reasoning"] = rehyd(str(out.get("reasoning") or ""), mapping)
    return out


def _persist_offer(
    db: Session,
    brand_id: str,
    customer_id: str | None,
    segment_id: str | None,
    clamped: dict,
    clamp_log: list[dict],
    fallback_expiration_days: int,
) -> models.Offer:
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=int(
            clamped.get("expiration_days") or fallback_expiration_days
        )
    )
    rule_json = {
        "discount_pct": clamped.get("discount_pct"),
        "discount_type": clamped.get("discount_type"),
        "addons": clamped.get("addons") or [],
    }
    row = models.Offer(
        brand_id=brand_id,
        customer_id=customer_id,
        segment_id=segment_id,
        product_ids=clamped.get("product_ids") or [],
        rule_json=rule_json,
        copy_json=clamped.get("copy") or {},
        policy_clamps=clamp_log,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return row


def _persist_touches(
    db: Session,
    campaign: models.Campaign,
    touches_raw: list[dict],
    brand: models.Brand,
    products_by_id: dict[str, models.Product],
    rec_product_ids: list[str],
) -> list[models.CampaignTouch]:
    rows: list[models.CampaignTouch] = []
    base = datetime.now(timezone.utc)
    rec_products = [
        products_by_id[pid] for pid in rec_product_ids if pid in products_by_id
    ]
    for i, t in enumerate(touches_raw):
        offset = int(
            t.get("scheduled_offset_days")
            if t.get("scheduled_offset_days") is not None
            else _DEFAULT_OFFSETS[min(i, len(_DEFAULT_OFFSETS) - 1)]
        )
        scheduled_at = base + timedelta(days=max(0, offset))
        kind = t.get("kind") or "email"
        content: dict[str, Any] = {
            "step_index": int(t.get("step_index") or i + 1),
            "scheduled_offset_days": offset,
        }
        if kind == "email":
            subject = str(t.get("email_subject") or "")
            body = str(t.get("email_body") or "")
            content["subject"] = subject
            content["body"] = body
            try:
                content["html_body"] = email_renderer.render(
                    brand, body, rec_products[:1]
                )
            except Exception:  # noqa: BLE001
                log.exception("campaign_planner: email render failed")
                content["html_body"] = None
        elif kind == "video":
            content["voiceover_script"] = str(
                t.get("voiceover_script") or ""
            )
        elif kind == "landing":
            content["headline"] = str(t.get("landing_headline") or "")
            content["body"] = str(t.get("landing_body") or "")
        rows.append(
            models.CampaignTouch(
                campaign_id=campaign.id,
                step_index=int(t.get("step_index") or i + 1),
                kind=kind,
                scheduled_at=scheduled_at,
                content_json=content,
                status="planned",
            )
        )
    for r in rows:
        db.add(r)
    db.flush()
    return rows


def _serialize_touch(t: models.CampaignTouch) -> dict:
    return {
        "id": t.id,
        "step_index": t.step_index,
        "kind": t.kind,
        "scheduled_at": (
            t.scheduled_at.isoformat() if t.scheduled_at else None
        ),
        "content": t.content_json or {},
        "status": t.status,
    }


def _serialize_offer(o: models.Offer) -> dict:
    return {
        "offer_id": o.id,
        "product_ids": o.product_ids or [],
        "rule": o.rule_json or {},
        "copy": o.copy_json or {},
        "policy_clamps": o.policy_clamps or [],
        "expires_at": o.expires_at.isoformat() if o.expires_at else None,
    }


async def plan_campaign(
    db: Session,
    brand_id: str,
    target_kind: str,
    target_id: str,
    trigger: str | None = None,
    *,
    user_prompt: str | None = None,
) -> dict:
    """Plan a 1:1 campaign for one customer or a segment.

    Returns the persisted shape; the API surface returns this verbatim.
    """
    if target_kind not in ("customer", "segment"):
        raise ValueError(
            f"target_kind must be 'customer' or 'segment', got {target_kind!r}"
        )

    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise ValueError(f"brand {brand_id} not found")

    bus.emit(
        Events.CAMPAIGN_PLANNING,
        {
            "brand_id": brand_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "trigger": trigger or "manual",
        },
    )

    customer: models.Customer | None = None
    segment: models.Segment | None = None
    if target_kind == "customer":
        customer = db.get(models.Customer, target_id)
        if customer is None or customer.brand_id != brand_id:
            raise ValueError(f"customer {target_id} not found for brand")
        events = (
            db.query(models.CustomerEvent)
            .filter_by(brand_id=brand_id, customer_id=target_id)
            .order_by(models.CustomerEvent.occurred_at.desc())
            .limit(20)
            .all()
        )
        brief_text = _build_customer_brief(customer, events)
        target_label = customer.name or customer.email
    else:
        segment = db.get(models.Segment, target_id)
        if segment is None or segment.brand_id != brand_id:
            raise ValueError(f"segment {target_id} not found for brand")
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
        target_label = segment.name

    products = (
        db.query(models.Product).filter_by(brand_id=brand_id).all()
    )
    products_by_id = {p.id: p for p in products}

    redaction = redactor.redact(brief_text)
    bus.emit(
        Events.AUDIENCE_PII_REDACTED,
        {"brand_id": brand_id, **_entity_summary(redaction.entities)},
    )

    eff_policy = policy_validator.effective_policy(
        brand.offer_policy or {},
        (segment.offer_policy_override if segment else None),
    )

    system = (
        _system_prompt_customer(brand, eff_policy, trigger)
        if target_kind == "customer"
        else _system_prompt_segment(brand, eff_policy, trigger)
    )
    user = (
        f"Recipient brief (PII redacted):\n{redaction.redacted_text}\n\n"
        f"Product catalog:\n{_product_catalog_text(products)}\n\n"
        f"User instruction: {user_prompt or '(none — use your judgment)'}\n\n"
        "Output JSON: {title, description, touches:[{...}], offer:{...}}."
    )

    raw = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        schema=CAMPAIGN_SCHEMA,
    )

    raw_offer = dict(raw.get("offer") or {})
    valid_ids = set(products_by_id.keys())
    raw_offer["product_ids"] = [
        pid
        for pid in (raw_offer.get("product_ids") or [])
        if pid in valid_ids
    ]
    rehyd_offer = _rehydrate_offer(raw_offer, redaction.mapping)
    clamped_offer, clamp_log = policy_validator.clamp(rehyd_offer, eff_policy)
    _emit_clamps(brand_id, target_kind, target_id, clamp_log)

    offer_row = _persist_offer(
        db,
        brand_id,
        customer.id if customer else None,
        segment.id if segment else None,
        clamped_offer,
        clamp_log,
        fallback_expiration_days=int(eff_policy["expiration_max_days"]),
    )

    raw_touches = list(raw.get("touches") or [])
    rehyd_touches = [
        _rehydrate_touch(t, redaction.mapping) for t in raw_touches
    ]

    title = redactor.rehydrate(
        str(raw.get("title") or f"{trigger or 'manual'} — {target_label}"),
        redaction.mapping,
    )
    description = redactor.rehydrate(
        str(raw.get("description") or ""), redaction.mapping
    )

    campaign = models.Campaign(
        brand_id=brand_id,
        title=title[:200],
        target_kind=target_kind,
        target_id=target_id,
        trigger=trigger or "manual",
        status="draft",
        description=description,
        offer_id=offer_row.id,
        bundle={},  # legacy column kept empty for the new flow
    )
    db.add(campaign)
    db.flush()

    touch_rows = _persist_touches(
        db,
        campaign,
        rehyd_touches,
        brand,
        products_by_id,
        clamped_offer.get("product_ids") or [],
    )

    bus.emit(
        Events.OFFER_GENERATED,
        {
            "brand_id": brand_id,
            "offer_id": offer_row.id,
            "customer_id": customer.id if customer else None,
            "segment_id": segment.id if segment else None,
            "product_count": len(offer_row.product_ids or []),
            "discount_pct": (offer_row.rule_json or {}).get("discount_pct"),
            "discount_type": (offer_row.rule_json or {}).get("discount_type"),
            "policy_clamp_count": len(clamp_log),
        },
    )

    db.commit()
    db.refresh(campaign)
    for r in touch_rows:
        db.refresh(r)
    db.refresh(offer_row)

    bus.emit(
        Events.CAMPAIGN_PLANNED,
        {
            "brand_id": brand_id,
            "campaign_id": campaign.id,
            "target_kind": target_kind,
            "target_id": target_id,
            "trigger": trigger or "manual",
            "touch_count": len(touch_rows),
            "offer_id": offer_row.id,
            "redaction_summary": _entity_summary(redaction.entities),
        },
    )

    return {
        "campaign_id": campaign.id,
        "title": campaign.title,
        "description": campaign.description,
        "trigger": campaign.trigger,
        "status": campaign.status,
        "target_kind": campaign.target_kind,
        "target_id": campaign.target_id,
        "touches": [_serialize_touch(t) for t in touch_rows],
        "offer": _serialize_offer(offer_row),
        "redaction_summary": _entity_summary(redaction.entities),
        "policy_clamps": clamp_log,
    }
