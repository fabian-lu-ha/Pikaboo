"""HTTP surface for Pioneer-AI per-tenant fine-tuning.

Three things land here:

* ``POST /finetune/start`` — kicks off the corpus → train → deploy
  pipeline for a brand. Idempotent; returning current status when a
  job is already in flight.
* ``GET /finetune/status?brand_id=X`` — current state for the dashboard
  to reconcile after a reconnect.
* ``POST /webhooks/pioneer`` — Pioneer's adaptive-inference checkpoint
  promotion webhook. We just translate it into a ``voice.model_upgraded``
  event for the bus to fan out.

Optional helper: ``POST /finetune/preview`` runs a single inference call
against the deployed adapter so the demo can show before/after voice
fidelity side by side.
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
from app.services.finetune import benchmark, orchestrator, pioneer_client
from app.services.finetune.prompts import (
    render_user_turn,
    voice_system_prompt,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/finetune")
webhook_router = APIRouter(prefix="/webhooks")


class StartIn(BaseModel):
    brand_id: str


@router.post("/start")
async def post_start(
    body: StartIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """Async on purpose: orchestrator.start_finetune spawns a background
    task via asyncio.create_task, which requires a running event loop —
    a sync FastAPI handler runs on a threadpool without one and would
    500 on the create_task call."""
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    return orchestrator.start_finetune(body.brand_id)


@router.get("/status")
def get_status(brand_id: str) -> dict:
    return orchestrator.get_status(brand_id)


class PreviewIn(BaseModel):
    brand_id: str
    brief: str
    platform: str = "instagram"
    # "pioneer" routes through the deployed adapter (or falls back to
    # Gemini-with-voice if the adapter isn't ready). "generic" sends a
    # voice-stripped system prompt to plain Gemini — that's the
    # comparison side of the demo's voice-fidelity test.
    mode: str = "pioneer"


_GENERIC_SYSTEM = (
    "You are a competent marketing copywriter. Given a brief, write the "
    "post. Output JSON of the form {\"caption\": \"...\", "
    '"hashtags": [...], "cta": "..."}. Hashtags array may be empty. CTA '
    "may be an empty string."
)

_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "cta": {"type": "string"},
    },
    "required": ["caption", "hashtags", "cta"],
    "additionalProperties": False,
}


@router.post("/preview")
async def post_preview(
    body: PreviewIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """Single inference call.

    Two sides feed the demo's side-by-side comparison:

    * ``mode="pioneer"`` — voice system prompt + adapter (Gemini fall-back).
    * ``mode="generic"`` — voice-stripped system prompt + plain Gemini.
    """
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    from app.services.llm.client import chat_json

    user_turn = render_user_turn(body.brief, body.platform)

    if body.mode == "generic":
        messages = [
            {"role": "system", "content": _GENERIC_SYSTEM},
            {"role": "user", "content": user_turn},
        ]
        result = await chat_json(messages, schema=_DRAFT_SCHEMA)
        return {"source": "gemini_generic", "draft": result}

    voice_profile = dict(brand.voice_profile or {})
    if not voice_profile:
        raise HTTPException(
            status_code=400, detail="voice profile not yet extracted"
        )
    system_prompt = voice_system_prompt(brand.name or "the brand", voice_profile)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_turn},
    ]
    adapter_url = brand.voice_adapter_url
    if adapter_url:
        # No fallback. If the adapter is deployed we go through it; any
        # failure surfaces as a 502 so we know the real Pioneer path is
        # broken instead of pretending everything's fine via Gemini.
        try:
            result = await pioneer_client.chat_via_adapter(
                adapter_url, messages, schema=_DRAFT_SCHEMA
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"pioneer adapter inference failed: {e}",
            )
        return {"source": "pioneer", "draft": result}

    # No adapter deployed yet → brand-voice-prompted Gemini is the
    # honest path: it's the same prompt the LoRA *will* be trained on,
    # so the call is real, just unfine-tuned. We label it accordingly.
    result = await chat_json(messages, schema=_DRAFT_SCHEMA)
    return {"source": "gemini_pretrain", "draft": result}


class BenchmarkIn(BaseModel):
    brand_id: str
    brief: str
    platform: str = "instagram"


@router.post("/benchmark")
async def post_benchmark(
    body: BenchmarkIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """3-way head-to-head: Pioneer adapter vs generic Flash vs frontier Pro.

    Runs all three calls in parallel, measures latency + JSON validity,
    then asks Gemini Pro (judge) to score each output blind on voice
    fidelity + specificity. The Voice pane renders the result as a
    score chart — direct evidence for the prize criteria.
    """
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    try:
        result = await benchmark.run_benchmark(
            body.brand_id, body.brief, body.platform
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return benchmark.serialize_result(result)


class WebhookIn(BaseModel):
    event: str
    deployment_id: str | None = None
    model_id: str | None = None
    metrics: dict | None = None


@webhook_router.post("/pioneer")
async def post_pioneer_webhook(
    payload: WebhookIn, request: Request, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """Receive Pioneer's adaptive-inference checkpoint promotion events."""
    if payload.event != "deployment.checkpoint_promoted":
        return {"ok": True, "ignored": payload.event}
    deployment_id = payload.deployment_id
    if not deployment_id:
        return {"ok": False, "error": "missing deployment_id"}

    # Match the brand whose adapter URL contains this deployment id.
    matched = (
        db.query(models.Brand)
        .filter(models.Brand.voice_adapter_url.like(f"%{deployment_id}%"))
        .first()
    )
    if matched is None:
        return {"ok": True, "matched": False}

    bus.emit(
        Events.VOICE_MODEL_UPGRADED,
        {
            "brand_id": matched.id,
            "deployment_id": deployment_id,
            "model_id": payload.model_id,
            "metrics": payload.metrics or {},
        },
    )
    return {"ok": True, "brand_id": matched.id}
