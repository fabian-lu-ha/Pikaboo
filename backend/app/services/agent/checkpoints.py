"""Run-lifecycle checkpoints + asset capture for chat-driven campaigns.

The agent loop (``services/agent/loop.py``) only writes the Campaign row at
the very end, when everything bundled successfully. That means a crash or
failure halfway through wipes the entire run from durable storage and the
user sees an empty Recent Runs list after retry.

This module subscribes to the run's progress events and writes a row eagerly:

  agent.started                 → create Campaign(status='running') + Storyboard
                                  (linked to brand). Pre-allocates the IDs the
                                  rest of the events use as their primary key.
  draft.created                 → patch Campaign.bundle with the new draft;
                                  if the draft body is an image URL, persist
                                  it into the Asset library too.
  agent.peec_data_fetched       → cache the Peec snapshot inside Campaign.bundle
  lift.predicted                → stamp predicted_lift on Campaign + bundle
  campaign.bundled              → final bundle replace (loop.py also writes,
                                  this acts as a backstop on race / crash)
  agent.failed                  → mark the bundle status='failed'

Every write is dedupe-safe: ``Campaign(id=campaign_id)`` is upserted via
``db.merge``, drafts are merged by ``channel`` (so re-emits don't double
up), and asset writes flow through ``record_asset`` which is unique on
(brand_id, url).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.assets.library import record_asset

log = logging.getLogger(__name__)

_LISTENER_BOUND = False

# campaign_id → storyboard_id, so subsequent events know which storyboard
# to attach asset rows to without hitting the DB.
_storyboard_for_campaign: dict[str, str] = {}


def _looks_like_image_url(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    if not value.startswith(("/api/storage/", "http://", "https://")):
        return False
    lowered = value.lower().split("?", 1)[0]
    return any(lowered.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))


def _ensure_campaign(
    db, campaign_id: str, brand_id: str, title: str
) -> models.Campaign:
    camp = db.get(models.Campaign, campaign_id)
    if camp is not None:
        return camp
    camp = models.Campaign(
        id=campaign_id,
        brand_id=brand_id,
        title=title,
        bundle={"status": "running"},
        predicted_lift=None,
    )
    db.add(camp)
    db.flush()
    return camp


def _ensure_storyboard(db, brand_id: str, campaign_id: str) -> str:
    sid = _storyboard_for_campaign.get(campaign_id)
    if sid is not None:
        if db.get(models.Storyboard, sid) is not None:
            return sid
    sid = str(uuid4())
    sb = models.Storyboard(
        id=sid,
        brand_id=brand_id,
        cast={},
        cinematic_brief={"campaign_id": campaign_id},
        voiceover={},
    )
    db.add(sb)
    try:
        db.flush()
        _storyboard_for_campaign[campaign_id] = sid
        return sid
    except IntegrityError:
        db.rollback()
        return sid


def _patch_bundle(campaign_id: str, patch: dict[str, Any]) -> None:
    """Read-modify-write the Campaign.bundle JSON. SQLAlchemy needs a new
    object handed back for JSON columns to detect a change."""
    if not patch:
        return
    with SessionLocal() as db:
        camp = db.get(models.Campaign, campaign_id)
        if camp is None:
            return
        merged = dict(camp.bundle or {})
        merged.update(patch)
        camp.bundle = merged
        db.add(camp)
        db.commit()


def _on_started(p: dict) -> None:
    campaign_id = str(p.get("campaign_id") or "")
    brand_id = str(p.get("brand_id") or "")
    if not campaign_id or not brand_id:
        return
    title = str(p.get("user_request") or "")[:80] or "Campaign"
    try:
        with SessionLocal() as db:
            _ensure_campaign(db, campaign_id, brand_id, title)
            _ensure_storyboard(db, brand_id, campaign_id)
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("checkpoints: failed to seed campaign+storyboard")


def _on_draft_created(p: dict) -> None:
    """Append/replace a draft inside Campaign.bundle.drafts and capture
    image-channel bodies as Asset rows."""
    campaign_id = str(p.get("campaign_id") or "")
    if not campaign_id:
        return
    channel = str(p.get("channel") or "")
    body = p.get("body")
    title = p.get("title")

    with SessionLocal() as db:
        camp = db.get(models.Campaign, campaign_id)
        if camp is None:
            return
        bundle = dict(camp.bundle or {})
        drafts: list[dict] = list(bundle.get("drafts") or [])
        existing = next((d for d in drafts if d.get("channel") == channel), None)
        record = {
            "channel": channel,
            "title": title,
            "body": body,
            "preview": p.get("preview"),
        }
        if existing is None:
            drafts.append(record)
        else:
            existing.update(record)
        bundle["drafts"] = drafts
        camp.bundle = bundle
        db.add(camp)
        db.commit()
        brand_id = camp.brand_id

    # Image channels — body is the asset URL, not text. Persist to library.
    if channel == "hero_image" or channel.endswith("_image"):
        if isinstance(body, str) and _looks_like_image_url(body):
            cast_kind = "product" if channel == "hero_image" else None
            label = (title or channel).strip() or channel
            record_asset(
                brand_id=brand_id,
                kind="image",
                subkind="upload",
                url=body,
                cast_kind=cast_kind,
                label=label,
                meta={"source": "campaign", "campaign_id": campaign_id, "channel": channel},
            )


def _on_lift_predicted(p: dict) -> None:
    campaign_id = str(p.get("campaign_id") or "")
    if not campaign_id:
        return
    lift_value = p.get("lift_percent")
    with SessionLocal() as db:
        camp = db.get(models.Campaign, campaign_id)
        if camp is None:
            return
        bundle = dict(camp.bundle or {})
        # Strip the campaign_id key the bus payload carries; the bundle
        # already lives under that ID.
        lift_payload = {k: v for k, v in p.items() if k != "campaign_id"}
        bundle["predicted_lift"] = lift_payload
        camp.bundle = bundle
        if isinstance(lift_value, (int, float)):
            camp.predicted_lift = float(lift_value)
        db.add(camp)
        db.commit()


def _on_peec(p: dict) -> None:
    campaign_id = str(p.get("campaign_id") or "")
    if not campaign_id:
        return
    snapshot = p.get("snapshot")
    targets = p.get("target_prompts") or []
    _patch_bundle(
        campaign_id,
        {
            "peec_snapshot": snapshot,
            "target_prompts": [
                t.get("prompt") if isinstance(t, dict) else t for t in targets
            ],
        },
    )


def _on_bundled(p: dict) -> None:
    """Final bundle replace. ``loop.py`` writes Campaign.bundle wholesale
    around the same time — we run on the same event so whichever finishes
    first wins, and the next one is a no-op rewrite."""
    campaign_id = str(p.get("campaign_id") or "")
    bundle = p.get("bundle")
    if not campaign_id or not isinstance(bundle, dict):
        return
    with SessionLocal() as db:
        camp = db.get(models.Campaign, campaign_id)
        if camp is None:
            return
        merged = dict(bundle)
        merged.setdefault("status", "bundled")
        camp.bundle = merged
        title = p.get("title")
        if isinstance(title, str) and title:
            camp.title = title[:200]
        lift = bundle.get("predicted_lift")
        if isinstance(lift, dict):
            v = lift.get("lift_percent")
            if isinstance(v, (int, float)):
                camp.predicted_lift = float(v)
        db.add(camp)
        db.commit()


def _on_failed(p: dict) -> None:
    campaign_id = str(p.get("campaign_id") or "")
    if not campaign_id:
        return
    _patch_bundle(
        campaign_id,
        {"status": "failed", "error": str(p.get("error") or "")[:500]},
    )


def start_listener() -> None:
    """Idempotent — safe to call from lifespan startup on every reload."""
    global _LISTENER_BOUND
    if _LISTENER_BOUND:
        return
    bus.on(Events.AGENT_STARTED, _on_started)
    bus.on(Events.DRAFT_CREATED, _on_draft_created)
    bus.on(Events.LIFT_PREDICTED, _on_lift_predicted)
    bus.on(Events.AGENT_PEEC_DATA_FETCHED, _on_peec)
    bus.on(Events.CAMPAIGN_BUNDLED, _on_bundled)
    bus.on(Events.AGENT_FAILED, _on_failed)
    _LISTENER_BOUND = True
    log.info("checkpoints: agent run listeners bound")
