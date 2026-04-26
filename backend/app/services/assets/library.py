"""Asset library helpers + bus listener.

The listener subscribes once at module load (called from main.py during
lifespan startup) and writes Asset rows as ingredients, scenes, and
renders complete. Brand id is resolved from the storyboards table when
the event carries a storyboard_id; otherwise we fall back to the most
recently onboarded brand (single-brand demo today).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events

log = logging.getLogger(__name__)

_LISTENER_BOUND = False
_BACKFILLED: set[str] = set()


def _latest_brand_id(db) -> str | None:
    row = (
        db.query(models.Brand.id)
        .order_by(models.Brand.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _brand_id_for_storyboard(db, storyboard_id: str | None) -> str | None:
    if not storyboard_id:
        return None
    sb = db.get(models.Storyboard, storyboard_id)
    return sb.brand_id if sb and sb.brand_id else None


def record_asset(
    *,
    brand_id: str | None,
    kind: str,
    subkind: str,
    url: str,
    storyboard_id: str | None = None,
    cast_kind: str | None = None,
    label: str | None = None,
    prompt_preview: str | None = None,
    duration_ms: int | None = None,
    aspect: str | None = None,
    meta: dict[str, Any] | None = None,
) -> models.Asset | None:
    """Persist one asset row. Idempotent on (brand_id, url) — duplicate
    callers (e.g. multiple bus listeners or retries) won't double-insert.
    Returns the row if a new one was written, ``None`` on dedupe / no
    brand_id.
    """
    if not url:
        return None
    with SessionLocal() as db:
        if not brand_id:
            brand_id = _brand_id_for_storyboard(db, storyboard_id) or _latest_brand_id(db)
        if not brand_id:
            log.debug("assets: no brand_id available, skipping %s", url)
            return None

        row = models.Asset(
            brand_id=brand_id,
            kind=kind,
            subkind=subkind,
            url=url,
            storyboard_id=storyboard_id,
            cast_kind=cast_kind,
            label=label,
            prompt_preview=(prompt_preview or "")[:500] or None,
            duration_ms=duration_ms,
            aspect=aspect,
            meta=meta or {},
        )
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            return None
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("assets: failed to persist %s", url)
            return None

    # Outside the session — fire-and-forget AI describe so the planner
    # has a description to read on the next /suggest. Image-only;
    # video clips are recorded for the library but skipped by the
    # describer (cast bindings are image-only).
    if row.kind == "image":
        try:
            from app.services.asset_describe import schedule_describe

            schedule_describe(row.id)
        except Exception:  # noqa: BLE001
            log.exception(
                "assets: schedule_describe failed for %s", row.id
            )
    return row


def _on_ingredient_generated(p: dict) -> None:
    record_asset(
        brand_id=None,
        kind="image",
        subkind="ingredient",
        url=str(p.get("canonical_url") or ""),
        storyboard_id=p.get("storyboard_id"),
        cast_kind=p.get("kind"),
        label=p.get("cast_id"),
        meta={"from_brand_asset": bool(p.get("from_brand_asset"))},
    )


def _on_frame_generated(p: dict) -> None:
    record_asset(
        brand_id=None,
        kind="image",
        subkind="frame",
        url=str(p.get("image_url") or ""),
        storyboard_id=p.get("storyboard_id"),
        label=p.get("frame_id"),
        prompt_preview=p.get("prompt_preview"),
        aspect=p.get("aspect"),
    )


def _on_scene_generated(p: dict) -> None:
    record_asset(
        brand_id=None,
        kind="video",
        subkind="scene",
        url=str(p.get("clip_url") or ""),
        storyboard_id=p.get("storyboard_id"),
        label=p.get("frame_id"),
        duration_ms=p.get("duration_ms"),
        aspect=p.get("aspect"),
        meta={"quality": p.get("quality")},
    )


def _on_video_rendered(p: dict) -> None:
    record_asset(
        brand_id=None,
        kind="video",
        subkind="render",
        url=str(p.get("video_url") or ""),
        duration_ms=p.get("duration_ms"),
        meta={"frame_count": p.get("frame_count")},
    )


def start_listener() -> None:
    """Bind bus listeners exactly once. Idempotent so the lifespan can
    call it freely on every reload."""
    global _LISTENER_BOUND
    if _LISTENER_BOUND:
        return
    bus.on(Events.VIDEO_INGREDIENT_GENERATED, _on_ingredient_generated)
    bus.on(Events.VIDEO_FRAME_GENERATED, _on_frame_generated)
    bus.on(Events.VIDEO_SCENE_GENERATED, _on_scene_generated)
    bus.on(Events.VIDEO_RENDERED, _on_video_rendered)
    _LISTENER_BOUND = True
    log.info("assets: bus listener bound")


def _record_brand_image(
    brand_id: str,
    url: str,
    *,
    label: str,
    subkind: str = "upload",
    cast_kind: str | None = None,
) -> None:
    """Tiny wrapper around ``record_asset`` for backfill use. The unique
    constraint on (brand_id, url) handles dedupe."""
    record_asset(
        brand_id=brand_id,
        kind="image",
        subkind=subkind,
        url=url,
        label=label,
        cast_kind=cast_kind,
        meta={"source": "onboarding"},
    )


def backfill_brand_assets(brand_id: str) -> int:
    """Seed the asset library from the brand's onboarding-time media —
    logo, screenshots, product images, and any uploaded assets — so the
    Library page paints immediately even before the first video render.

    Idempotent twice: short-circuits in-process via a per-brand cache,
    and the (brand_id, url) UniqueConstraint catches anything that slips
    through (e.g. process restart).
    """
    if brand_id in _BACKFILLED:
        return 0
    inserted = 0
    with SessionLocal() as db:
        brand = db.get(models.Brand, brand_id)
        if brand is None:
            return 0

        if brand.logo_url:
            row = record_asset(
                brand_id=brand_id,
                kind="image",
                subkind="upload",
                url=brand.logo_url,
                label="Brand logo",
                cast_kind="product",
                meta={"source": "onboarding", "role": "logo"},
            )
            if row is not None:
                inserted += 1

        for i, url in enumerate(brand.screenshots or []):
            if not url or not isinstance(url, str):
                continue
            row = record_asset(
                brand_id=brand_id,
                kind="image",
                subkind="upload",
                url=url,
                label=f"Site screenshot {i + 1}",
                cast_kind="setting",
                meta={"source": "onboarding", "role": "screenshot"},
            )
            if row is not None:
                inserted += 1

        for i, url in enumerate(brand.product_images or []):
            if not url or not isinstance(url, str):
                continue
            row = record_asset(
                brand_id=brand_id,
                kind="image",
                subkind="upload",
                url=url,
                label=f"Product photo {i + 1}",
                cast_kind="product",
                meta={"source": "onboarding", "role": "product"},
            )
            if row is not None:
                inserted += 1

        for i, entry in enumerate(brand.assets or []):
            url = None
            label = f"Brand asset {i + 1}"
            if isinstance(entry, str):
                url = entry
            elif isinstance(entry, dict):
                url = entry.get("url") or entry.get("asset_url")
                label = entry.get("name") or entry.get("label") or label
            if not url:
                continue
            row = record_asset(
                brand_id=brand_id,
                kind="image",
                subkind="upload",
                url=str(url),
                label=str(label),
                meta={"source": "onboarding", "role": "asset"},
            )
            if row is not None:
                inserted += 1

    _BACKFILLED.add(brand_id)
    if inserted:
        log.info("assets: backfilled %d items for brand %s", inserted, brand_id)
    return inserted
