"""Auto-seed the Peec project with prompts when a new brand finishes
onboarding.

The agent loop and analytics page both read from a Peec project, but
without monitored prompts the brands report stays empty. This listener
fires once per brand at the end of onboarding (when ``ONBOARDING_COMPLETED``
is emitted) and runs the seed pipeline grounded in that brand's name,
description, and competitor list.

Multi-tenancy caveat (today): a project-scoped ``skp-`` API key targets
ONE Peec project. Every brand that completes onboarding adds its prompts
to the same project. Upgrading to a company-tier key would unlock
per-brand projects via ``POST /projects`` — we don't do that here.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.peec.seed_prompts import (
    PeecSeedError,
    SeededPrompt,
    seed_prompts,
)

log = logging.getLogger(__name__)

_registered = False
_DEFAULT_TARGET = 12


def register_listener() -> None:
    """Idempotent — safe to call multiple times. Mounts a single
    ``ONBOARDING_COMPLETED`` listener on the bus so each brand's seed
    runs exactly once."""
    global _registered
    if _registered:
        return
    bus.on(Events.ONBOARDING_COMPLETED, _on_onboarding_completed)
    _registered = True


async def _on_onboarding_completed(payload: dict) -> None:
    if not settings.peec_api_key:
        log.info("peec.auto_seed: PEEC_API_KEY not set — skipping")
        return

    brand_id = payload.get("brand_id") if isinstance(payload, dict) else None
    if not brand_id:
        log.warning("peec.auto_seed: onboarding payload missing brand_id")
        return

    brand_payload = _load_brand_payload(brand_id)
    if brand_payload is None:
        log.warning("peec.auto_seed: brand %s not found in DB", brand_id)
        return

    try:
        seeded: list[SeededPrompt] = await seed_prompts(
            target_count=_DEFAULT_TARGET,
            brand_name=brand_payload["name"],
            brand_description=brand_payload["description"],
            competitors=brand_payload["competitors"],
        )
    except PeecSeedError as e:
        log.warning("peec.auto_seed: seed_prompts errored for brand=%s: %s", brand_id, e)
        return
    except Exception as e:  # noqa: BLE001 — never break onboarding on seed failure
        log.exception("peec.auto_seed: unexpected failure: %s", e)
        return

    log.info(
        "peec.auto_seed: brand=%s seeded %s prompts", brand_id, len(seeded)
    )


def _load_brand_payload(brand_id: str) -> dict | None:
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "name": row.name or "",
            "description": row.description or "",
            "competitors": [c.name for c in row.competitors if c.name][:8],
        }


# Background-task helper for callers that already have a brand id
# (e.g. /api/geo/seed-prompts re-runs even after onboarding).
async def auto_seed_for_brand(
    brand_id: str, target_count: int = _DEFAULT_TARGET
) -> list[SeededPrompt]:
    payload = _load_brand_payload(brand_id)
    if payload is None:
        return []
    return await seed_prompts(
        target_count=target_count,
        brand_name=payload["name"],
        brand_description=payload["description"],
        competitors=payload["competitors"],
    )


def schedule_seed_for_brand(brand_id: str, target_count: int = _DEFAULT_TARGET) -> None:
    """Fire-and-forget wrapper for callers in non-async contexts.
    Schedules the seed on the running event loop without blocking."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop running (e.g. called from a sync test) — bail quietly.
        log.warning("peec.auto_seed: no running loop to schedule seed")
        return
    loop.create_task(auto_seed_for_brand(brand_id, target_count))
