"""3-way head-to-head: Pioneer adapter vs generic Gemini vs frontier Gemini.

This is the *evidence* layer for the Pioneer prize. The judging criteria
ask for "evidence that the fine-tuned model improved your project's
accuracy, latency, or reliability" — so we measure all three on the
same brief, against the same brand voice rubric, then ask a frontier
model to score each output blind on voice fidelity. The Voice pane
renders the scores side by side.

Why three columns:
  * Pioneer (or simulator) — the brand-aware draft. The thing we're
    selling. With a real adapter, this is also where Pioneer's "2x
    cheaper than GPT-4o" latency claim shows up.
  * Generic Gemini Flash — same model class, NO brand voice context.
    The "what would happen without us" baseline.
  * Frontier Gemini Pro — the heavyweight model. This is the
    "general-purpose LLM API call" the criteria want us to outperform.

The judge call is run against Gemini Pro for fairness — using the same
model as judge that produced one of the candidates would bias the
result, but Pro hasn't seen the brand prompt and rates the *output*
text against the rubric, so it's clean enough for a hackathon eval.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.services.finetune import pioneer_client
from app.services.finetune.prompts import (
    render_user_turn,
    voice_system_prompt,
)
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


_GENERIC_SYSTEM = (
    "You are a competent marketing copywriter. Given a brief, write the "
    "post. Output JSON of the form {\"caption\": \"...\", "
    '"hashtags": [...], "cta": "..."}. Hashtags array may be empty. CTA '
    "may be an empty string."
)

_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "cta": {"type": "string"},
    },
    "required": ["caption", "hashtags", "cta"],
    "additionalProperties": False,
}


_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "voice_fidelity": {"type": "integer"},
                    "specificity": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "candidate_id",
                    "voice_fidelity",
                    "specificity",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scores"],
    "additionalProperties": False,
}


@dataclass
class CandidateRun:
    id: str  # "pioneer" | "gemini_generic" | "gemini_frontier"
    label: str
    model: str
    draft: dict[str, Any] | None
    latency_ms: int
    json_valid: bool
    error: str | None
    voice_fidelity: int | None = None
    specificity: int | None = None
    rationale: str | None = None


@dataclass
class BenchmarkResult:
    brand_id: str
    brief: str
    platform: str
    candidates: list[CandidateRun]
    judge_model: str
    simulator: bool


async def _time_call(coro) -> tuple[Any, int, str | None]:
    """Run an async call, return (result, ms, error_or_none)."""
    t0 = time.monotonic()
    try:
        result = await coro
        ms = int((time.monotonic() - t0) * 1000)
        return result, ms, None
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return None, ms, str(e)[:200]


def _validate_draft(d: Any) -> bool:
    if not isinstance(d, dict):
        return False
    if not isinstance(d.get("caption"), str) or not d["caption"].strip():
        return False
    if not isinstance(d.get("hashtags"), list):
        return False
    if not isinstance(d.get("cta"), str):
        return False
    return True


async def _run_pioneer(
    brand: models.Brand, brief: str, platform: str
) -> CandidateRun:
    voice_profile = dict(brand.voice_profile or {})
    system_prompt = voice_system_prompt(brand.name or "the brand", voice_profile)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": render_user_turn(brief, platform)},
    ]
    adapter_url = brand.voice_adapter_url

    if adapter_url:
        result, ms, err = await _time_call(
            pioneer_client.chat_via_adapter(
                adapter_url, messages, schema=_DRAFT_SCHEMA
            )
        )
        return CandidateRun(
            id="pioneer",
            label="Pioneer adapter",
            model="pioneer:adapter",
            draft=result if _validate_draft(result) else None,
            latency_ms=ms,
            json_valid=_validate_draft(result),
            error=err,
        )

    # No adapter deployed yet → brand-voice-prompted Gemini is the
    # honest pre-train baseline. Labelled accordingly so the chart
    # doesn't claim Pioneer numbers when nothing's been trained.
    result, ms, err = await _time_call(
        chat_json(messages, schema=_DRAFT_SCHEMA)
    )
    return CandidateRun(
        id="pioneer",
        label="Pioneer (pre-train baseline)",
        model="gemini-flash:brand-prompted",
        draft=result if _validate_draft(result) else None,
        latency_ms=ms,
        json_valid=_validate_draft(result),
        error=err,
    )


async def _run_generic(brief: str, platform: str) -> CandidateRun:
    messages = [
        {"role": "system", "content": _GENERIC_SYSTEM},
        {"role": "user", "content": render_user_turn(brief, platform)},
    ]
    result, ms, err = await _time_call(
        chat_json(messages, schema=_DRAFT_SCHEMA)
    )
    return CandidateRun(
        id="gemini_generic",
        label="Gemini Flash (generic)",
        model=settings.gemini_model,
        draft=result if _validate_draft(result) else None,
        latency_ms=ms,
        json_valid=_validate_draft(result),
        error=err,
    )


async def _run_frontier(brief: str, platform: str) -> CandidateRun:
    messages = [
        {"role": "system", "content": _GENERIC_SYSTEM},
        {"role": "user", "content": render_user_turn(brief, platform)},
    ]
    result, ms, err = await _time_call(
        chat_json(
            messages, schema=_DRAFT_SCHEMA, model=settings.gemini_planning_model
        )
    )
    return CandidateRun(
        id="gemini_frontier",
        label="Gemini Pro (frontier baseline)",
        model=settings.gemini_planning_model,
        draft=result if _validate_draft(result) else None,
        latency_ms=ms,
        json_valid=_validate_draft(result),
        error=err,
    )


async def _judge(
    brand: models.Brand, brief: str, candidates: list[CandidateRun]
) -> dict[str, Any]:
    """Ask Gemini Pro to score each candidate against the brand voice rubric.

    Inputs are stripped of their model labels so the judge can't bias by
    knowing which is the Pioneer side. The candidate IDs are anonymised
    (A/B/C) for the judge call and re-mapped on return.
    """
    # Build anonymised candidate list — only pass ones with valid drafts.
    valid = [c for c in candidates if c.draft and c.json_valid]
    if not valid:
        return {"scores": []}
    id_map: dict[str, str] = {}
    blinded: list[dict[str, Any]] = []
    for i, c in enumerate(valid):
        anon = chr(ord("A") + i)
        id_map[anon] = c.id
        blinded.append(
            {
                "candidate_id": anon,
                "caption": c.draft.get("caption") if c.draft else "",
                "hashtags": c.draft.get("hashtags") if c.draft else [],
                "cta": c.draft.get("cta") if c.draft else "",
            }
        )
    voice_profile = dict(brand.voice_profile or {})
    rubric = json.dumps(voice_profile, ensure_ascii=False, indent=2)

    system = (
        "You are a strict brand-voice judge. Given a marketing brief, a brand "
        "voice profile, and several candidate posts, score each candidate "
        "0-10 on (a) voice_fidelity — how closely the candidate matches the "
        "brand's tone, recurring phrases, do/don't list, and voice excerpt — "
        "and (b) specificity — how concrete and on-brief the post is, vs. "
        "vague generic marketing-speak. Be honest; AI slop should score low. "
        "Output JSON only."
    )
    user = (
        f"Brand: {brand.name}\n\n"
        f"Brief: {brief}\n\n"
        f"Voice profile (the rubric):\n{rubric}\n\n"
        f"Candidates:\n{json.dumps(blinded, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON: {scores: [{candidate_id, voice_fidelity, specificity, "
        "rationale}]}. Rationale must be one short sentence per candidate."
    )
    payload = await chat_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        schema=_JUDGE_SCHEMA,
        model=settings.gemini_planning_model,
    )
    # Re-map anonymised IDs back to real ones.
    scores = payload.get("scores") or []
    for s in scores:
        anon = s.get("candidate_id")
        if anon in id_map:
            s["candidate_id"] = id_map[anon]
    return {"scores": scores}


async def run_benchmark(
    brand_id: str, brief: str, platform: str = "instagram"
) -> BenchmarkResult:
    """Public entry — fan out the three calls in parallel, then judge."""
    with SessionLocal() as db:
        brand = db.get(models.Brand, brand_id)
        if brand is None:
            raise ValueError("brand not found")
        if not brand.voice_profile:
            raise ValueError("voice profile not yet extracted — finish onboarding first")

        # Snapshot fields we need; we don't keep the session open across
        # the LLM round-trips because each can take seconds.
        brand_snapshot = brand

        pioneer_task = asyncio.create_task(
            _run_pioneer(brand_snapshot, brief, platform)
        )
        generic_task = asyncio.create_task(_run_generic(brief, platform))
        frontier_task = asyncio.create_task(_run_frontier(brief, platform))
        candidates = await asyncio.gather(
            pioneer_task, generic_task, frontier_task
        )

        try:
            judge = await _judge(brand_snapshot, brief, list(candidates))
        except Exception as e:
            log.warning("judge call failed: %s", e)
            judge = {"scores": []}

    by_id = {c.id: c for c in candidates}
    for s in judge.get("scores") or []:
        cid = s.get("candidate_id")
        c = by_id.get(cid)
        if c is None:
            continue
        c.voice_fidelity = int(s.get("voice_fidelity") or 0)
        c.specificity = int(s.get("specificity") or 0)
        c.rationale = s.get("rationale")

    return BenchmarkResult(
        brand_id=brand_id,
        brief=brief,
        platform=platform,
        candidates=list(candidates),
        judge_model=settings.gemini_planning_model,
        simulator=pioneer_client.get_client().is_simulator,
    )


def serialize_result(r: BenchmarkResult) -> dict[str, Any]:
    return {
        "brand_id": r.brand_id,
        "brief": r.brief,
        "platform": r.platform,
        "judge_model": r.judge_model,
        "simulator": r.simulator,
        "candidates": [
            {
                "id": c.id,
                "label": c.label,
                "model": c.model,
                "draft": c.draft,
                "latency_ms": c.latency_ms,
                "json_valid": c.json_valid,
                "error": c.error,
                "voice_fidelity": c.voice_fidelity,
                "specificity": c.specificity,
                "rationale": c.rationale,
            }
            for c in r.candidates
        ],
    }
