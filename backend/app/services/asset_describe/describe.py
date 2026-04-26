"""Gemini-Vision-backed describer for the brand asset library.

For each Asset row that hasn't been described yet, fetch the image bytes
and ask the FAST Gemini model for a structured description:

  - description: 1-2 sentences naming concrete subject + setting + lighting
  - tags: 5-8 single-word entities for filtering / matching
  - cast_kind: best-fit slot type (character / setting / prop / product)

The output is written back to the Asset row. The storyboard planner reads
``description`` + ``cast_kind`` per asset and uses that to pick which
brand asset binds to which cast member it authors.

Three entry points:

  - ``describe_asset(asset_id)`` — describe one asset by id
  - ``describe_brand_assets(brand_id)`` — describe every un-described
    asset for a brand (bulk catch-up)
  - ``schedule_describe(asset_id)`` — fire-and-forget background task,
    used by the library bus listener so describes don't block the upload
    response

All paths are best-effort: failures mark the row ``description_status =
'failed'`` and log a warning, never raise. The asset is still usable; the
planner just falls back to count-only awareness for that one.
"""

from __future__ import annotations

import asyncio
import json
import logging
from base64 import b64decode
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events

log = logging.getLogger(__name__)

_client: genai.Client | None = None

# Cap for the Gemini inline image input — anything bigger gets skipped
# rather than burning a File-API upload roundtrip. Brand assets are
# typically <2MB; Veo renders we don't describe (kind='video' is skipped).
_MAX_INLINE_BYTES = 8 * 1024 * 1024  # 8 MB

_DESCRIBE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 8,
        },
        "cast_kind": {
            "type": "string",
            "enum": ["character", "setting", "prop", "product"],
        },
    },
    "required": ["description", "tags", "cast_kind"],
}


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _resolve_url_to_bytes(url: str) -> tuple[bytes, str] | None:
    """Mirror frame_gen._load_asset_bytes for the describer. Local mode
    only — Supabase support would require an HTTP fetch, deferred until a
    real demo needs it.
    """
    if not url:
        return None
    if url.startswith("data:"):
        try:
            head, b64 = url.split(",", 1)
            mime = head.split(";")[0].removeprefix("data:") or "image/png"
            return b64decode(b64), mime
        except Exception:
            return None
    if settings.deploy_mode != "local":
        return None
    if not url.startswith("/api/storage/"):
        return None
    rel = url.removeprefix("/api/storage/")
    p = Path(settings.storage_dir) / rel
    if not p.exists() or not p.is_file():
        return None
    suffix = p.suffix.lstrip(".").lower()
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(suffix, "image/png")
    try:
        return p.read_bytes(), mime
    except OSError:
        return None


def _build_messages(label: str | None, hint_kind: str | None) -> str:
    """Single-string user prompt — vision input rides alongside the
    text content as a Part, so we don't need a multi-message structure.
    """
    parts = [
        "You are a visual describer for a brand asset library. Describe "
        "what the attached image actually shows in concrete, picture-"
        "specific language a creative director would use to brief a DP.",
        "",
        "Output JSON with three keys:",
        "  description: ONE OR TWO sentences. Name the subject, the "
        "    setting, the lighting, and the dominant color. No vague "
        "    vibes ('beautiful', 'modern'); use concrete nouns and verbs.",
        "  tags: 5-8 single-word entities a search bar would match — "
        "    materials, objects, locations, lighting words.",
        "  cast_kind: the best-fit slot type for the storyboard cast "
        "    bible: 'character' (a person), 'setting' (a location / "
        "    interior / exterior), 'prop' (a hero object that's not the "
        "    flagship product), 'product' (the brand's actual product).",
    ]
    if label:
        parts.append(f"\nLibrary label hint (do not parrot, just inform your read): {label!r}")
    if hint_kind:
        parts.append(
            f"Existing cast_kind tag on this asset (treat as a soft hint, "
            f"override if the image disagrees): {hint_kind!r}"
        )
    return "\n".join(parts)


async def _call_gemini_describe(
    image_bytes: bytes,
    mime: str,
    label: str | None,
    hint_kind: str | None,
) -> dict:
    client = _get_client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY not configured")

    text_prompt = _build_messages(label, hint_kind)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[text_prompt, image_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_DESCRIBE_SCHEMA,
        ),
    )
    raw = response.text or "{}"
    return json.loads(raw)


def _normalize(out: dict) -> dict:
    """Clamp the LLM output into the row contract."""
    desc = str(out.get("description") or "").strip()[:1000]
    tags_raw = out.get("tags") or []
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for t in tags_raw:
            if isinstance(t, str):
                cleaned = t.strip().lower()
                if cleaned and cleaned not in tags:
                    tags.append(cleaned[:40])
            if len(tags) >= 8:
                break
    cast_kind = str(out.get("cast_kind") or "").strip().lower()
    if cast_kind not in {"character", "setting", "prop", "product"}:
        cast_kind = ""
    return {"description": desc, "tags": tags, "cast_kind": cast_kind}


async def describe_asset(asset_id: str, *, force: bool = False) -> bool:
    """Describe a single asset row. Returns True iff the row was updated.

    Skips:
      - missing rows
      - non-image rows (videos, renders) unless force=True
      - rows already described (description_status='ready') unless force=True
      - rows whose URL can't be resolved to bytes (Supabase mode, dead path)
    """
    if not asset_id:
        return False
    with SessionLocal() as db:
        row = db.get(models.Asset, asset_id)
        if row is None:
            return False
        if row.kind != "image" and not force:
            return False
        if row.description_status == "ready" and not force:
            return False
        url = row.url
        label = row.label
        hint_kind = row.cast_kind
        brand_id = row.brand_id

        # Mark pending so concurrent callers don't double-fire.
        row.description_status = "pending"
        db.commit()

    bus.emit(
        Events.ASSET_DESCRIBING,
        {"asset_id": asset_id, "brand_id": brand_id},
    )

    loaded = _resolve_url_to_bytes(url)
    if loaded is None:
        log.info("describe: cannot load %s — skipping", url)
        with SessionLocal() as db:
            row = db.get(models.Asset, asset_id)
            if row is not None:
                row.description_status = "failed"
                db.commit()
        bus.emit(
            Events.ASSET_DESCRIBE_FAILED,
            {"asset_id": asset_id, "reason": "asset bytes not available"},
        )
        return False
    data, mime = loaded
    if len(data) > _MAX_INLINE_BYTES:
        log.info("describe: %s too large (%d bytes) — skipping", asset_id, len(data))
        with SessionLocal() as db:
            row = db.get(models.Asset, asset_id)
            if row is not None:
                row.description_status = "failed"
                db.commit()
        bus.emit(
            Events.ASSET_DESCRIBE_FAILED,
            {"asset_id": asset_id, "reason": "too large for inline describe"},
        )
        return False

    try:
        out = await _call_gemini_describe(data, mime, label, hint_kind)
    except Exception as e:
        log.warning("describe: gemini call failed for %s: %s", asset_id, e)
        with SessionLocal() as db:
            row = db.get(models.Asset, asset_id)
            if row is not None:
                row.description_status = "failed"
                db.commit()
        bus.emit(
            Events.ASSET_DESCRIBE_FAILED,
            {"asset_id": asset_id, "reason": str(e)[:240]},
        )
        return False

    norm = _normalize(out)
    with SessionLocal() as db:
        row = db.get(models.Asset, asset_id)
        if row is None:
            return False
        row.description = norm["description"] or None
        row.tags = norm["tags"]
        # Only override cast_kind if the model gave us one AND the row
        # didn't already have a hand-set hint (e.g. the onboarding
        # backfill tagged the logo as 'product' — trust that).
        if norm["cast_kind"] and not row.cast_kind:
            row.cast_kind = norm["cast_kind"]
        row.description_status = "ready" if norm["description"] else "failed"
        db.commit()
        bus.emit(
            Events.ASSET_DESCRIBED,
            {
                "asset_id": asset_id,
                "brand_id": row.brand_id,
                "description": row.description,
                "tags": row.tags or [],
                "cast_kind": row.cast_kind,
            },
        )
    return bool(norm["description"])


async def describe_brand_assets(
    brand_id: str, *, only_pending: bool = True
) -> int:
    """Catch up every un-described asset for a brand. Returns the count
    that were successfully described (failures don't count)."""
    if not brand_id:
        return 0
    with SessionLocal() as db:
        q = db.query(models.Asset.id).filter(
            models.Asset.brand_id == brand_id,
            models.Asset.kind == "image",
        )
        if only_pending:
            q = q.filter(
                (models.Asset.description_status.is_(None))
                | (models.Asset.description_status == "idle")
                | (models.Asset.description_status == "failed")
            )
        ids = [r[0] for r in q.all()]
    described = 0
    # Run sequentially — Gemini is fast enough for a brand library
    # (~50 assets) and serial keeps us under quota. Parallelize later if
    # users start uploading hundreds at once.
    for aid in ids:
        ok = await describe_asset(aid)
        if ok:
            described += 1
    return described


def schedule_describe(asset_id: str) -> None:
    """Fire-and-forget describe — used by the library bus listener so a
    new asset gets described without blocking the upload response. Falls
    back to a no-op when called outside an asyncio loop (e.g. sync test
    code) so callers never have to guard.
    """
    if not asset_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop — caller is sync; skip
    loop.create_task(describe_asset(asset_id))
