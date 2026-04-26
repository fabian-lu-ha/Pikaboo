"""Personalized email drafting.

Two entry points:
  - ``personalize_for_customer`` — full PII goes through the redactor; the
    LLM only ever sees ``[NAME_1]``-style tokens; result is rehydrated.
  - ``personalize_for_segment`` — aggregate brief, no PII flowing in, output
    uses ``{customer_name}`` merge tags rather than rehydrated names.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.events.bus import bus
from app.events.types import Events
from app.services.audience import renderer as email_renderer
from app.services.llm.client import chat_json
from app.services.pii import redactor

log = logging.getLogger(__name__)


EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "recommended_product_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning": {"type": "string"},
    },
    "required": ["subject", "body", "recommended_product_ids", "reasoning"],
}


def _voice_brief(brand: models.Brand) -> str:
    voice = brand.voice_profile or {}
    bits = []
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


def _entity_summary(entities: list[dict]) -> dict[str, Any]:
    types = sorted({e["type"] for e in entities})
    return {"entity_count": len(entities), "types": types}


def _competitor_catalog_text(db: Session, brand_id: str) -> tuple[str, int]:
    """Return (rendered text, total product count) of competitor catalogs.

    Caps at 10 lines across all competitors so the LLM context doesn't blow
    up. Used as 'comparison context only' — the prompt explicitly forbids
    recommending competitor products.
    """
    competitors = (
        db.query(models.Competitor)
        .filter(models.Competitor.brand_id == brand_id)
        .all()
    )
    lines: list[str] = []
    total = 0
    for c in competitors:
        products = ((c.pattern_library or {}).get("products") or [])[:3]
        total += len(products)
        for p in products:
            lines.append(
                f"- {c.name}: {p.get('name','?')} @ "
                f"{p.get('price_text','?')}: "
                f"{(p.get('description') or '')[:100]}"
            )
    if not lines:
        return "(no competitor product data)", 0
    return "\n".join(lines[:10]), total


def _attribution_narrative(customer: models.Customer) -> str:
    """One-line narrative of where this customer came from + their journey.

    Goes into the personalization brief so the LLM can write things like
    "since you came in through the summer-sale ad". Empty input still
    returns a string — the caller always splices it into the brief.
    """
    attrs = customer.attributes or {}
    acq = attrs.get("acquisition") or {}
    tps = attrs.get("touchpoints") or []
    if not acq and not tps:
        return "Acquisition: (unknown)"
    parts: list[str] = []
    src = acq.get("source") or "unknown"
    camp = acq.get("campaign") or ""
    first_url = acq.get("first_touch_url") or ""
    if src and camp:
        parts.append(f"first-touch: {src} — {camp}")
    elif src:
        parts.append(f"first-touch: {src}")
    if first_url:
        parts.append(f"landed on {first_url}")
    if len(tps) > 1:
        later = [
            f"{t.get('source','?')} ({t.get('action','?')})"
            for t in tps[1:4]
        ]
        if later:
            parts.append("then: " + ", ".join(later))
    return "Acquisition: " + " | ".join(parts)


async def personalize_for_customer(
    db: Session,
    brand_id: str,
    customer_id: str,
    user_prompt: str | None = None,
) -> dict:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise ValueError(f"brand {brand_id} not found")
    customer = db.get(models.Customer, customer_id)
    if customer is None or customer.brand_id != brand_id:
        raise ValueError(f"customer {customer_id} not found for brand")

    bus.emit(
        Events.AUDIENCE_PERSONALIZING,
        {
            "brand_id": brand_id,
            "target_kind": "customer",
            "target_id": customer_id,
        },
    )

    events = (
        db.query(models.CustomerEvent)
        .filter_by(brand_id=brand_id, customer_id=customer_id)
        .order_by(models.CustomerEvent.occurred_at.desc())
        .limit(20)
        .all()
    )
    products = (
        db.query(models.Product).filter_by(brand_id=brand_id).all()
    )

    activity_lines = []
    for e in events:
        p = e.payload or {}
        when = e.occurred_at.date().isoformat() if e.occurred_at else "?"
        if e.kind == "purchase":
            activity_lines.append(
                f"{when} purchase: {p.get('product_name') or p.get('product_id')}"
            )
        elif e.kind == "email_click":
            activity_lines.append(
                f"{when} email_click: {p.get('subject') or ''} -> {p.get('link') or ''}"
            )
        elif e.kind == "email_open":
            activity_lines.append(f"{when} email_open: {p.get('subject') or ''}")
        elif e.kind == "page_view":
            activity_lines.append(f"{when} page_view: {p.get('path') or ''}")
        elif e.kind == "support_msg":
            activity_lines.append(
                f"{when} support: {p.get('topic') or 'general'}"
            )

    brief = (
        f"Customer name: {customer.name or '(unknown)'}\n"
        f"Email: {customer.email}\n"
        f"Phone: {customer.phone or '(none)'}\n"
        f"City: {customer.city or '(unknown)'}, {customer.country or ''}\n"
        f"Tags: {', '.join(customer.tags or []) or '(none)'}\n"
        f"{_attribution_narrative(customer)}\n"
        f"Total spend: ${(customer.total_spend_cents or 0) / 100:.2f}\n"
        "Recent activity:\n" + ("\n".join(activity_lines) or "(no activity)")
    )

    redaction = redactor.redact(brief)
    bus.emit(
        Events.AUDIENCE_PII_REDACTED,
        {"brand_id": brand_id, **_entity_summary(redaction.entities)},
    )

    competitor_text, competitor_catalog_size = _competitor_catalog_text(
        db, brand_id
    )

    system = (
        "You are a marketing copywriter. Write a personalized email matching "
        "the brand's voice. The customer brief uses placeholder tokens like "
        "[NAME_1] or [EMAIL_1] — use those tokens verbatim in your output "
        "where you'd reference the person. The system will rehydrate them."
    )
    user = (
        f"Brand voice: {_voice_brief(brand)}\n\n"
        f"Customer brief (PII redacted):\n{redaction.redacted_text}\n\n"
        f"Product catalog:\n{_product_catalog_text(products)}\n\n"
        f"Competitor catalog (for comparison context only — do NOT "
        f"recommend competitor products):\n{competitor_text}\n\n"
        f"User instruction: {user_prompt or '(none — use your judgment)'}\n\n"
        "Write a short personalized email: subject + body. Reference the "
        "customer by their [NAME_x] token. Reference 1-2 specific recent "
        "activity moments. Recommend 1-2 products from OUR catalog by id. "
        "If a competitor offers something similar, ONE sentence on why ours "
        "is the better fit (no name-calling, no fabricated facts). "
        "Output JSON: {subject, body, recommended_product_ids, reasoning}."
    )

    result = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        schema=EMAIL_SCHEMA,
    )

    subject = redactor.rehydrate(
        str(result.get("subject") or ""), redaction.mapping
    )
    body = redactor.rehydrate(
        str(result.get("body") or ""), redaction.mapping
    )

    valid_ids = {p.id for p in products}
    rec_ids = [
        pid
        for pid in (result.get("recommended_product_ids") or [])
        if pid in valid_ids
    ]

    rec_products = [p for p in products if p.id in rec_ids]
    html_body = email_renderer.render(brand, body, rec_products)

    bus.emit(
        Events.AUDIENCE_PERSONALIZED,
        {
            "brand_id": brand_id,
            "customer_id": customer_id,
            "subject_preview": subject[:80],
            "recommended_product_ids": rec_ids,
        },
    )

    return {
        "subject": subject,
        "body": body,
        "html_body": html_body,
        "recommended_product_ids": rec_ids,
        "reasoning": str(result.get("reasoning") or ""),
        "redaction_summary": _entity_summary(redaction.entities),
        "competitor_catalog_size": competitor_catalog_size,
    }


async def personalize_for_segment(
    db: Session,
    brand_id: str,
    segment_id: str,
    user_prompt: str | None = None,
) -> dict:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise ValueError(f"brand {brand_id} not found")
    segment = db.get(models.Segment, segment_id)
    if segment is None or segment.brand_id != brand_id:
        raise ValueError(f"segment {segment_id} not found for brand")

    bus.emit(
        Events.AUDIENCE_PERSONALIZING,
        {
            "brand_id": brand_id,
            "target_kind": "segment",
            "target_id": segment_id,
        },
    )

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
    products = (
        db.query(models.Product).filter_by(brand_id=brand_id).all()
    )
    member_events: list[models.CustomerEvent] = []
    if members:
        member_events = (
            db.query(models.CustomerEvent)
            .filter(
                models.CustomerEvent.brand_id == brand_id,
                models.CustomerEvent.customer_id.in_([m.id for m in members]),
            )
            .all()
        )

    archetypes = Counter(
        (m.attributes or {}).get("archetype_label", "unknown") for m in members
    )
    cities = Counter((m.city or "unknown") for m in members)
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

    aggregate_brief = (
        f"Segment: {segment.name}\n"
        f"Description: {segment.description or '(none)'}\n"
        f"Size: {len(members)} members\n"
        f"Top archetypes: {dict(archetypes.most_common(3))}\n"
        f"Top cities: {dict(cities.most_common(3))}\n"
        f"Top purchased categories: {dict(purchase_categories.most_common(3))}\n"
        f"Top purchased products: {dict(top_products.most_common(3))}"
    )

    # Aggregate brief shouldn't contain PII; redactor still passes through
    # for symmetry with the per-customer flow.
    redaction = redactor.redact(aggregate_brief)
    bus.emit(
        Events.AUDIENCE_PII_REDACTED,
        {"brand_id": brand_id, **_entity_summary(redaction.entities)},
    )

    system = (
        "You are a marketing copywriter writing one email template that will "
        "be sent to a whole segment. Use the merge tag {customer_name} where "
        "you'd address the recipient — do not invent a name. Keep references "
        "general (segment-level patterns), not individual."
    )
    user = (
        f"Brand voice: {_voice_brief(brand)}\n\n"
        f"Segment brief:\n{redaction.redacted_text}\n\n"
        f"Product catalog:\n{_product_catalog_text(products)}\n\n"
        f"User instruction: {user_prompt or '(none — use your judgment)'}\n\n"
        "Write the segment email: subject + body. Use {customer_name} as the "
        "merge tag. Recommend 1-2 products by id that fit the segment's top "
        "categories. Output JSON: "
        "{subject, body, recommended_product_ids, reasoning}."
    )

    result = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        schema=EMAIL_SCHEMA,
    )

    subject = redactor.rehydrate(
        str(result.get("subject") or ""), redaction.mapping
    )
    body = redactor.rehydrate(
        str(result.get("body") or ""), redaction.mapping
    )

    valid_ids = {p.id for p in products}
    rec_ids = [
        pid
        for pid in (result.get("recommended_product_ids") or [])
        if pid in valid_ids
    ]

    # Segment emails use a {customer_name} merge tag so we can't bind a
    # single hero product the way per-customer emails do — render the body
    # with no CTA product. The frontend can still show the HTML preview.
    rec_products = [p for p in products if p.id in rec_ids][:1]
    html_body = email_renderer.render(brand, body, rec_products)

    bus.emit(
        Events.AUDIENCE_PERSONALIZED,
        {
            "brand_id": brand_id,
            "segment_id": segment_id,
            "subject_preview": subject[:80],
            "recommended_product_ids": rec_ids,
            "recipient_count": len(members),
        },
    )

    return {
        "subject": subject,
        "body": body,
        "html_body": html_body,
        "recommended_product_ids": rec_ids,
        "reasoning": str(result.get("reasoning") or ""),
        "redaction_summary": _entity_summary(redaction.entities),
    }
