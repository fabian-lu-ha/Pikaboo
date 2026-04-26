"""GEO recommender — given one gap, ask Gemini to pick one action_type
from the playbook with a confidence score, rationale, and a short asset
outline. Persists a GeoRecommendation row and emits GEO_ACTION_PROPOSED.

The recommender is *biased* by the per-engine playbook in playbook.py:
when the gap's ``engines_present`` lean toward a particular engine, the
high-leverage action_types for that engine are surfaced to the model in
the prompt so it picks them when they fit.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.geo.playbook import (
    ACTION_TYPES,
    ENGINE_PLAYBOOK,
    action_type_label,
    action_type_summary,
)
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


_RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_type": {"type": "string", "enum": list(ACTION_TYPES)},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "target_engines": {
            "type": "array",
            "items": {"type": "string"},
        },
        "asset_outline": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "target_word_count": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["title", "key_points"],
        },
    },
    "required": [
        "action_type",
        "confidence",
        "rationale",
        "asset_outline",
    ],
}


async def recommend_for_gap(gap_id: str) -> str | None:
    """Generate one GeoRecommendation for a gap. Returns the recommendation
    id, or None if the LLM call fails or the gap is missing."""
    brand_payload, gap_payload, brand_id = _load_gap_context(gap_id)
    if gap_payload is None:
        return None

    facts = _build_recommender_facts(brand_payload, gap_payload)
    system = _RECOMMENDER_SYSTEM
    user = f"GAP FACTS:\n{facts}"

    try:
        out = await chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=_RECOMMENDATION_SCHEMA,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("geo.recommend chat_json failed gap=%s: %s", gap_id, e)
        return None

    action_type = (out.get("action_type") or "").strip()
    if action_type not in ACTION_TYPES:
        log.warning(
            "geo.recommend returned unknown action_type=%s for gap=%s; coercing",
            action_type,
            gap_id,
        )
        action_type = _coerce_action_type(gap_payload)

    try:
        confidence = float(out.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    rationale = (out.get("rationale") or "").strip()
    target_engines_raw = out.get("target_engines") or []
    target_engines = [
        str(e).strip().lower()
        for e in target_engines_raw
        if isinstance(e, str) and e.strip()
    ]
    asset_outline = out.get("asset_outline") or {}

    with SessionLocal() as db:
        # Idempotent at the (gap_id, action_type) layer — a re-scan with
        # the same recommendation should update in place.
        row = (
            db.query(models.GeoRecommendation)
            .filter(
                models.GeoRecommendation.gap_id == gap_id,
                models.GeoRecommendation.action_type == action_type,
            )
            .one_or_none()
        )
        if row is None:
            row = models.GeoRecommendation(
                brand_id=brand_id,
                gap_id=gap_id,
                action_type=action_type,
                confidence=confidence,
                rationale=rationale,
                target_engines=target_engines,
                asset_outline=asset_outline,
            )
            db.add(row)
        else:
            row.confidence = confidence
            row.rationale = rationale or row.rationale
            row.target_engines = target_engines or row.target_engines
            row.asset_outline = asset_outline or row.asset_outline
            if row.status == "rejected":
                # Re-proposed after a previous rejection — back to proposed.
                row.status = "proposed"
        db.flush()
        recommendation_id = row.id
        payload = _serialize_recommendation(row)
        db.commit()

    bus.emit(Events.GEO_ACTION_PROPOSED, payload)
    return recommendation_id


_RECOMMENDER_SYSTEM = (
    "You are a Generative-Engine-Optimization (GEO) strategist. Given one "
    "GAP — a search prompt where the user's brand is absent and a competitor "
    "is winning in answer engines (ChatGPT, Perplexity, Gemini, Claude, "
    "Google AI Overviews) — choose ONE action from the playbook that will "
    "best move the brand into the cited set on this prompt.\n\n"
    "Action types (pick exactly one):\n"
    + "\n".join(
        f"  • {action_type_label(a)}: {action_type_summary(a)}"
        for a in ACTION_TYPES
    )
    + "\n\nPer-engine biases (lean toward action types that match the engines "
    "named in the gap's engines_present):\n"
    + "\n".join(
        f"  • {info['label']}: {info['note']} High-leverage: "
        + ", ".join(info["high_leverage"])
        for info in ENGINE_PLAYBOOK.values()
    )
    + "\n\nReturn JSON matching the schema. Confidence ∈ [0,1] is your "
    "calibrated belief this action will move the prompt's citation set. "
    "Rationale is one short sentence — cite the engine signal or the "
    "competitor's cited_domains when possible. asset_outline.key_points "
    "is 3-6 bullets the asset must cover. target_engines is the lower-cased "
    "engine keys (chatgpt, perplexity, gemini, claude, google_ai_overviews) "
    "this action is most likely to influence."
)


def _load_gap_context(
    gap_id: str,
) -> tuple[dict | None, dict | None, str]:
    with SessionLocal() as db:
        gap = db.get(models.GeoGap, gap_id)
        if gap is None:
            return None, None, ""
        brand = db.get(models.Brand, gap.brand_id)
        if brand is None:
            return None, None, ""
        brand_payload = {
            "id": brand.id,
            "name": brand.name,
            "url": brand.url,
            "description": brand.description,
        }
        gap_payload = {
            "prompt": gap.prompt,
            "competitor_name": gap.competitor_name,
            "competitor_visibility": gap.competitor_visibility,
            "own_visibility": gap.own_visibility,
            "gap_score": gap.gap_score,
            "cited_domains": gap.cited_domains or [],
            "engines_present": gap.engines_present or [],
        }
        return brand_payload, gap_payload, brand.id


def _build_recommender_facts(brand: dict, gap: dict) -> str:
    return (
        f"BRAND: {brand.get('name')} — {brand.get('description') or 'no description'}\n"
        f"URL: {brand.get('url') or 'unknown'}\n\n"
        f"GAP PROMPT: \"{gap['prompt']}\"\n"
        f"  competitor winning: {gap.get('competitor_name') or 'unknown'} "
        f"(visibility {gap.get('competitor_visibility')})\n"
        f"  brand visibility: {gap.get('own_visibility')}\n"
        f"  gap_score: {gap.get('gap_score')}\n"
        f"  engines_present: {', '.join(gap.get('engines_present') or []) or 'unknown'}\n"
        f"  cited_domains in answer set: {', '.join(gap.get('cited_domains') or []) or 'unknown'}"
    )


def _coerce_action_type(gap: dict) -> str:
    """Fallback when the LLM returns a non-enum action_type. Pick a
    sensible default given the engine signal: Wikipedia/Wikidata-heavy
    engine → wikidata_schema; recency-heavy → stats_quote; default →
    comparison_page (the highest-yield format)."""
    engines = {e.lower() for e in (gap.get("engines_present") or [])}
    if "chatgpt" in engines or "gemini" in engines:
        return "wikidata_schema"
    if "perplexity" in engines:
        return "stats_quote"
    return "comparison_page"


def _serialize_recommendation(row: models.GeoRecommendation) -> dict:
    return {
        "id": row.id,
        "brand_id": row.brand_id,
        "gap_id": row.gap_id,
        "action_type": row.action_type,
        "action_label": action_type_label(row.action_type),
        "confidence": row.confidence,
        "rationale": row.rationale,
        "target_engines": row.target_engines or [],
        "asset_outline": row.asset_outline or {},
        "status": row.status,
        "created_at": (row.created_at or datetime.now(timezone.utc)).isoformat(),
    }
