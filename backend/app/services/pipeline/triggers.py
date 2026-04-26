"""Pipeline triggers — event-driven pipeline execution.

Three integration points:

1. **Bus listeners** (kanban.feature_shipped, audience.shop_event_triggered)
   — for each fire, scan the brand's pipelines for a head ``trigger`` node
   whose ``variant`` matches and fire ``execute_pipeline`` with a payload
   carrying the event data.

2. **Scheduler** — asyncio loop that wakes every 60s, scans for trigger
   nodes with ``variant=scheduled``, and runs them when their interval
   has elapsed since the last completed run. Cheap, low precision (good
   enough for marketing cadences). For sub-minute timing use a real cron.

3. **Webhook** — surface in ``app/api/pipelines.py``. Anyone with the
   trigger node's token can POST JSON to ``/api/pipelines/{id}/webhook``
   and the body is forwarded as the trigger payload.

Trigger node config shape (lives inside nodes JSON, no schema change)::

    {
      "kind": "trigger",
      "config": {
        "variant": "manual" | "on_kanban_shipped" | "on_shop_event"
                   | "scheduled" | "webhook",
        # variant-specific:
        "column_filter": "Done",         # on_kanban_shipped
        "label_filter": "marketing",
        "shop_kind": "cart_abandoned",   # on_shop_event
        "interval_minutes": 60,           # scheduled
        "token": "tok_abc",              # webhook
      }
    }
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.pipeline.executor import execute as execute_pipeline

log = logging.getLogger(__name__)

# Module-level state for the scheduler loop. ``_scheduler_task`` is set on
# ``start_scheduler`` and cleared on ``stop_scheduler``.
_scheduler_task: asyncio.Task | None = None
# Last firing time per pipeline_id, populated when the scheduler triggers
# a run. Used to avoid double-firing inside the same minute when the
# interval check resets to 0 due to clock drift.
_last_scheduled_fire: dict[str, datetime] = {}


# ----------------------------------------------------------- helpers


def _matching_trigger_node(
    pipeline: models.Pipeline, variant: str
) -> dict | None:
    """Return the first node whose kind=trigger and config.variant matches."""
    for n in pipeline.nodes or []:
        if (
            n.get("kind") == "trigger"
            and (n.get("config") or {}).get("variant") == variant
        ):
            return n
    return None


def _matches_filter(value: str | None, needle: str | None) -> bool:
    """Case-insensitive substring; empty needle = match-all."""
    if not needle:
        return True
    if not value:
        return False
    return needle.strip().lower() in value.lower()


def _spawn_run(pipeline_id: str, payload: dict) -> None:
    """Fire-and-forget pipeline run on its own DB session.

    Bus listeners are sync-ish, so we kick the run as a task and return
    immediately. Errors are logged, never raised — a misconfigured pipeline
    must not block the upstream event flow.
    """
    async def _go() -> None:
        db = SessionLocal()
        try:
            await execute_pipeline(db, pipeline_id, trigger_payload=payload)
        except Exception:  # noqa: BLE001
            log.exception(
                "pipeline %s triggered run failed", pipeline_id
            )
        finally:
            db.close()

    try:
        asyncio.create_task(_go())
    except RuntimeError:
        # No running loop (rare — e.g. test teardown). Skip.
        log.warning("pipeline trigger could not schedule run for %s", pipeline_id)


def _all_pipelines_for_brand(db: Session, brand_id: str) -> list[models.Pipeline]:
    return (
        db.query(models.Pipeline)
        .filter(models.Pipeline.brand_id == brand_id)
        .all()
    )


# ----------------------------------------------------------- bus listeners


def _on_kanban_shipped(payload: dict) -> None:
    """Fire pipelines with variant=on_kanban_shipped trigger nodes.

    Payload shape (from services.kanban.signals.handle_event):
        {brand_id, provider, kind, reason, card: {...}}
    """
    brand_id = payload.get("brand_id")
    if not brand_id:
        return
    card = payload.get("card") or {}
    db = SessionLocal()
    try:
        pipelines = _all_pipelines_for_brand(db, brand_id)
        for p in pipelines:
            node = _matching_trigger_node(p, "on_kanban_shipped")
            if node is None:
                continue
            cfg = node.get("config") or {}
            if not _matches_filter(card.get("column"), cfg.get("column_filter")):
                continue
            labels_blob = " ".join(card.get("labels") or [])
            if not _matches_filter(labels_blob, cfg.get("label_filter")):
                continue
            log.info(
                "pipeline trigger: kanban_shipped → pipeline %s (card %s)",
                p.id,
                card.get("external_id"),
            )
            _spawn_run(
                p.id,
                {
                    "trigger": "on_kanban_shipped",
                    "items": [
                        {
                            "id": card.get("external_id"),
                            "title": card.get("title"),
                            "description": card.get("description"),
                            "url": card.get("url"),
                            "labels": card.get("labels") or [],
                            "column": card.get("column"),
                            "board_name": card.get("board_name"),
                        }
                    ],
                    "raw": payload,
                },
            )
    finally:
        db.close()


def _on_shop_event(payload: dict) -> None:
    """Fire pipelines with variant=on_shop_event trigger nodes.

    Payload shape (from services.audience.shop_triggers.fire_shop_event):
        {brand_id, customer_id, kind, event_id, payload}
    """
    brand_id = payload.get("brand_id")
    if not brand_id:
        return
    db = SessionLocal()
    try:
        pipelines = _all_pipelines_for_brand(db, brand_id)
        for p in pipelines:
            node = _matching_trigger_node(p, "on_shop_event")
            if node is None:
                continue
            cfg = node.get("config") or {}
            wanted = (cfg.get("shop_kind") or "").strip()
            if wanted and wanted != payload.get("kind"):
                continue
            customer = db.get(models.Customer, payload.get("customer_id"))
            customer_view: dict = {}
            if customer is not None:
                customer_view = {
                    "id": customer.id,
                    "email": customer.email,
                    "name": customer.name,
                    "tags": customer.tags or [],
                    "total_spend_cents": customer.total_spend_cents or 0,
                }
            log.info(
                "pipeline trigger: shop_event/%s → pipeline %s",
                payload.get("kind"),
                p.id,
            )
            _spawn_run(
                p.id,
                {
                    "trigger": "on_shop_event",
                    "shop_kind": payload.get("kind"),
                    "items": [customer_view] if customer_view else [],
                    "raw": payload,
                },
            )
    finally:
        db.close()


def register_listeners() -> None:
    """Idempotent — safe to call once at module import.

    pyee allows multiple listeners; we attach our handlers without removing
    any. If the module is reloaded in dev, duplicate fires are possible —
    pyee deduplicates same-function-reference, so calling register more
    than once with the same handlers is a no-op.
    """
    bus.on(Events.KANBAN_FEATURE_SHIPPED, _on_kanban_shipped)
    bus.on(Events.AUDIENCE_SHOP_EVENT_TRIGGERED, _on_shop_event)


# ----------------------------------------------------------- scheduler


async def _scheduler_loop() -> None:
    """Wake every 60s, fire pipelines whose schedule has elapsed."""
    while True:
        try:
            await _scheduler_tick()
        except Exception:  # noqa: BLE001
            log.exception("pipeline scheduler tick failed")
        await asyncio.sleep(60)


async def _scheduler_tick() -> None:
    """One pass: scan all pipelines, fire any whose schedule has elapsed."""
    db = SessionLocal()
    try:
        pipelines = (
            db.query(models.Pipeline).all()
        )
        now = datetime.now(timezone.utc)
        for p in pipelines:
            node = _matching_trigger_node(p, "scheduled")
            if node is None:
                continue
            cfg = node.get("config") or {}
            try:
                interval_min = int(cfg.get("interval_minutes") or 60)
            except (TypeError, ValueError):
                continue
            if interval_min < 1:
                continue

            # Last completed run from DB. Use started_at as the anchor —
            # finished_at can be None for in-progress runs.
            last_run = (
                db.query(models.PipelineRun)
                .filter(models.PipelineRun.pipeline_id == p.id)
                .order_by(models.PipelineRun.started_at.desc())
                .first()
            )
            last_at = (
                last_run.started_at if last_run is not None else None
            )
            if last_at is not None and last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            cached_last = _last_scheduled_fire.get(p.id)
            if cached_last is not None and (
                last_at is None or cached_last > last_at
            ):
                last_at = cached_last

            should_fire = (
                last_at is None
                or (now - last_at) >= timedelta(minutes=interval_min)
            )
            if not should_fire:
                continue

            log.info(
                "pipeline scheduled fire: %s (every %sm)",
                p.id,
                interval_min,
            )
            _last_scheduled_fire[p.id] = now
            _spawn_run(
                p.id,
                {
                    "trigger": "scheduled",
                    "fired_at": now.isoformat(),
                    "items": [],
                },
            )
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        log.warning("pipeline scheduler: no running loop, skipped")
        return
    _scheduler_task = loop.create_task(_scheduler_loop())


def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None:
        return
    _scheduler_task.cancel()
    _scheduler_task = None
