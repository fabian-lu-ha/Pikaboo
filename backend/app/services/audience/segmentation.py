"""AI-proposed audience segmentation.

Builds PII-free per-customer summaries (no name / email / phone), feeds them
to the planning model, and asks for 3-6 segments. Returns proposals; caller
chooses which to persist via the API.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.events.bus import bus
from app.events.types import Events
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


def _days_ago(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return max(0, int(delta.total_seconds() // 86400))


def _summarize_customer(
    customer: models.Customer, events: list[models.CustomerEvent]
) -> dict:
    """PII-free summary used for the LLM segmentation call."""
    purchases = [e for e in events if e.kind == "purchase"]
    opens = [e for e in events if e.kind == "email_open"]
    sends = [
        e for e in events if e.kind in ("email_open", "email_click")
    ]
    open_rate = (len(opens) / len(sends)) if sends else 0.0

    categories = Counter(
        (e.payload or {}).get("category")
        for e in purchases
        if (e.payload or {}).get("category")
    )

    return {
        "customer_id": customer.id,
        "signup_days_ago": _days_ago(customer.signup_at),
        "last_active_days_ago": _days_ago(customer.last_active_at),
        "total_spend_cents": int(customer.total_spend_cents or 0),
        "purchase_count": len(purchases),
        "email_open_rate": round(open_rate, 2),
        "top_categories": [c for c, _ in categories.most_common(3)],
        "tags": list(customer.tags or []),
    }


SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "criteria_summary": {"type": "string"},
                    "customer_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "name",
                    "description",
                    "rationale",
                    "criteria_summary",
                    "customer_ids",
                ],
            },
        }
    },
    "required": ["segments"],
}


SYSTEM = (
    "You are an audience strategist. You group customers into 3-6 actionable "
    "segments for marketing. Use only the structured signals provided "
    "(spend, recency, open rate, categories, tags). Each segment must have a "
    "clear name, a one-sentence description, a rationale explaining the "
    "behavioral pattern, a short criteria_summary in plain English, and a "
    "non-empty customer_ids list drawn ONLY from the input ids."
)


async def propose_segments(db: Session, brand_id: str) -> list[dict]:
    """Return 3-6 proposed segments. Does not persist."""
    bus.emit(
        Events.AUDIENCE_SEGMENTS_PROPOSING, {"brand_id": brand_id}
    )

    customers = (
        db.query(models.Customer)
        .filter(models.Customer.brand_id == brand_id)
        .all()
    )
    if not customers:
        bus.emit(
            Events.AUDIENCE_SEGMENTS_PROPOSED,
            {"brand_id": brand_id, "segment_count": 0, "segments": []},
        )
        return []

    customer_ids = [c.id for c in customers]
    events_by_customer: dict[str, list[models.CustomerEvent]] = {
        cid: [] for cid in customer_ids
    }
    rows = (
        db.query(models.CustomerEvent)
        .filter(models.CustomerEvent.brand_id == brand_id)
        .all()
    )
    for r in rows:
        events_by_customer.setdefault(r.customer_id, []).append(r)

    summaries = [
        _summarize_customer(c, events_by_customer.get(c.id, []))
        for c in customers
    ]

    user = (
        "Customers (PII-free summaries):\n"
        f"{summaries}\n\n"
        "Output JSON matching the schema. customer_ids must be a subset of "
        f"these {len(customer_ids)} ids."
    )

    result = await chat_json(
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        schema=SEGMENT_SCHEMA,
        model=settings.gemini_planning_model,
    )

    valid_ids = set(customer_ids)
    segments: list[dict] = []
    for seg in result.get("segments", []) or []:
        ids = [cid for cid in (seg.get("customer_ids") or []) if cid in valid_ids]
        if not ids:
            continue
        segments.append(
            {
                "name": str(seg.get("name") or "Untitled segment"),
                "description": str(seg.get("description") or ""),
                "rationale": str(seg.get("rationale") or ""),
                "criteria_summary": str(seg.get("criteria_summary") or ""),
                "customer_ids": ids,
            }
        )

    bus.emit(
        Events.AUDIENCE_SEGMENTS_PROPOSED,
        {
            "brand_id": brand_id,
            "segment_count": len(segments),
            "segments": [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "size": len(s["customer_ids"]),
                }
                for s in segments
            ],
        },
    )
    return segments
