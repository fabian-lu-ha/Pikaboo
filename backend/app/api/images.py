"""Image edit endpoints — inpaint a region of an existing image, or
generate a fresh image from a user-drawn sketch.

Both routes write to local storage under `edits/<uuid>.png` (or under a
caller-specified scope so storyboard-frame edits cluster with their parent
storyboard) and return the new public URL. The frontend updates the
relevant component's image_url to that new URL — the original image is
never overwritten, so an /edit-region call is fully reversible.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.providers.factory import get_storage
from app.services.image_edit import (
    decode_data_url,
    inpaint_image,
    sketch_to_image,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/images")

PROMPT_MAX_CHARS = 2000

# Aspect must mirror what nano-banana-pro accepts (cf. video frame_gen).
Aspect = Literal["1:1", "16:9", "9:16"]

# Limit how big a single mask/sketch payload can be. Same 5MB ceiling
# frame_gen uses for asset refs; this is generous for canvas exports.
_MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

# Save scopes the client can request. Frame edits cluster under the
# parent storyboard so cleanup later is easy; everything else lives in
# /edits/. The set is closed on purpose — never let a client write into
# arbitrary subtrees.
_SAVE_SCOPES: set[str] = {"frame", "channel", "hero", "misc"}


def _slug_safe(s: str) -> str:
    """Tight slug for use in filesystem paths. Empty in → empty out."""
    if not s:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-")
    return cleaned[:64]


def _resolve_storage_url_to_bytes(url: str) -> bytes | None:
    """Resolve a /api/storage/... URL (or a data URL) to raw bytes.

    Supabase mode is intentionally unsupported here — all current edit
    surfaces in the UI render local-mode storage URLs.
    """
    if not url:
        return None
    if url.startswith("data:"):
        decoded = decode_data_url(url)
        return decoded[0] if decoded else None
    if not url.startswith("/api/storage/"):
        return None
    if settings.deploy_mode != "local":
        return None
    rel = url.removeprefix("/api/storage/")
    # Defence in depth — never escape the storage root.
    p = (Path(settings.storage_dir) / rel).resolve()
    root = Path(settings.storage_dir).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    if not p.exists() or not p.is_file():
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


def _load_brand_for_edit() -> dict | None:
    """Mirror video.py:_load_brand_for_frame so edits inherit the same brand."""
    with SessionLocal() as db:
        brand = (
            db.query(models.Brand)
            .filter(models.Brand.onboarded_at.is_not(None))
            .order_by(models.Brand.onboarded_at.desc())
            .first()
        )
        if brand is None:
            return None
        return {
            "id": brand.id,
            "name": brand.name,
            "palette": brand.palette,
            "palette_roles": brand.palette_roles,
            "identity": brand.identity,
            "style_profile": brand.style_profile,
            "assets": brand.assets or [],
            "reference_brands": brand.reference_brands or [],
        }


def _build_storage_key(scope: str, scope_id: str | None) -> str:
    """Pick a deterministic storage key under a closed scope set.

    `scope_id` is sanitised aggressively because it can come from a path-y
    identifier (storyboard_id, channel_id) — we never trust it as-is.
    """
    edit_slug = uuid4().hex[:10]
    sid = _slug_safe(scope_id or "")
    if scope == "frame" and sid:
        return f"videos/{sid}/edits/{edit_slug}.png"
    if scope == "channel" and sid:
        return f"campaigns/edits/{sid}/{edit_slug}.png"
    if scope == "hero" and sid:
        return f"campaigns/edits/hero-{sid}/{edit_slug}.png"
    return f"edits/{edit_slug}.png"


# ── /edit-region ─────────────────────────────────────────────────────────


class EditRegionIn(BaseModel):
    """Inpaint a user-highlighted region of an existing image.

    `mask_data_url` is an RGBA PNG dataURL where alpha > 0 marks the
    pixels the user painted. The mask must match the rendered display
    size of the source — backend rescales with NEAREST so brush edges
    stay crisp regardless.
    """

    source_url: str = Field(..., min_length=1, max_length=2000)
    mask_data_url: str = Field(..., min_length=20, max_length=12_000_000)
    prompt: str = Field(..., min_length=1, max_length=PROMPT_MAX_CHARS)
    aspect: Aspect = "16:9"
    save_scope: str = Field(default="misc")
    save_scope_id: str | None = Field(default=None, max_length=128)

    @field_validator("prompt")
    @classmethod
    def _trim_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt must not be blank")
        return v

    @field_validator("save_scope")
    @classmethod
    def _scope_known(cls, v: str) -> str:
        if v not in _SAVE_SCOPES:
            raise ValueError(f"save_scope must be one of {sorted(_SAVE_SCOPES)}")
        return v


class EditOut(BaseModel):
    image_url: str
    edit_id: str


@router.post("/edit-region", response_model=EditOut)
async def post_edit_region(body: EditRegionIn) -> EditOut:
    source_bytes = _resolve_storage_url_to_bytes(body.source_url)
    if source_bytes is None:
        raise HTTPException(
            status_code=400,
            detail="source_url could not be resolved to image bytes",
        )

    decoded = decode_data_url(body.mask_data_url)
    if decoded is None:
        raise HTTPException(
            status_code=400, detail="mask_data_url is not a valid data URL"
        )
    mask_bytes, _mime = decoded
    if len(mask_bytes) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="mask exceeds 5MB")

    brand = _load_brand_for_edit()  # may be None — edit still works, just no brand block.

    edit_id = uuid4().hex[:10]
    bus.emit(
        Events.IMAGE_EDIT_STARTED,
        {
            "edit_id": edit_id,
            "kind": "inpaint",
            "scope": body.save_scope,
            "scope_id": body.save_scope_id,
        },
    )

    try:
        out_bytes = await inpaint_image(
            brand,
            source_bytes,
            mask_bytes,
            body.prompt,
            body.aspect,
        )
    except ValueError as e:
        bus.emit(
            Events.IMAGE_EDIT_FAILED,
            {"edit_id": edit_id, "kind": "inpaint", "error": str(e)},
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("images.edit-region failed: %s", e)
        bus.emit(
            Events.IMAGE_EDIT_FAILED,
            {"edit_id": edit_id, "kind": "inpaint", "error": str(e)[-200:]},
        )
        raise HTTPException(status_code=502, detail=f"inpaint failed: {e}") from e

    if not out_bytes:
        bus.emit(
            Events.IMAGE_EDIT_FAILED,
            {"edit_id": edit_id, "kind": "inpaint", "error": "no image returned"},
        )
        raise HTTPException(status_code=502, detail="inpaint returned no image")

    key = _build_storage_key(body.save_scope, body.save_scope_id)
    try:
        storage = get_storage()
        await storage.put(key, out_bytes, "image/png")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("images.edit-region store failed: %s", e)
        raise HTTPException(status_code=502, detail=f"store failed: {e}") from e

    bus.emit(
        Events.IMAGE_EDITED,
        {
            "edit_id": edit_id,
            "kind": "inpaint",
            "image_url": url,
            "scope": body.save_scope,
            "scope_id": body.save_scope_id,
            "source_url": body.source_url,
            "prompt_preview": body.prompt[:240],
        },
    )
    return EditOut(image_url=url, edit_id=edit_id)


# ── /from-sketch ─────────────────────────────────────────────────────────


class FromSketchIn(BaseModel):
    """Generate a new image conditioned on a user-drawn sketch.

    `sketch_data_url` is a PNG dataURL of the canvas (white background OK —
    the model treats the sketch as layout/shape guidance, not literal pixels).
    """

    sketch_data_url: str = Field(..., min_length=20, max_length=12_000_000)
    prompt: str = Field(..., min_length=1, max_length=PROMPT_MAX_CHARS)
    aspect: Aspect = "16:9"
    save_scope: str = Field(default="misc")
    save_scope_id: str | None = Field(default=None, max_length=128)

    @field_validator("prompt")
    @classmethod
    def _trim_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt must not be blank")
        return v

    @field_validator("save_scope")
    @classmethod
    def _scope_known(cls, v: str) -> str:
        if v not in _SAVE_SCOPES:
            raise ValueError(f"save_scope must be one of {sorted(_SAVE_SCOPES)}")
        return v


@router.post("/from-sketch", response_model=EditOut)
async def post_from_sketch(body: FromSketchIn) -> EditOut:
    decoded = decode_data_url(body.sketch_data_url)
    if decoded is None:
        raise HTTPException(
            status_code=400, detail="sketch_data_url is not a valid data URL"
        )
    sketch_bytes, _mime = decoded
    if len(sketch_bytes) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="sketch exceeds 5MB")

    brand = _load_brand_for_edit()

    edit_id = uuid4().hex[:10]
    bus.emit(
        Events.IMAGE_EDIT_STARTED,
        {
            "edit_id": edit_id,
            "kind": "sketch",
            "scope": body.save_scope,
            "scope_id": body.save_scope_id,
        },
    )

    try:
        out_bytes = await sketch_to_image(
            brand, sketch_bytes, body.prompt, body.aspect
        )
    except ValueError as e:
        bus.emit(
            Events.IMAGE_EDIT_FAILED,
            {"edit_id": edit_id, "kind": "sketch", "error": str(e)},
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("images.from-sketch failed: %s", e)
        bus.emit(
            Events.IMAGE_EDIT_FAILED,
            {"edit_id": edit_id, "kind": "sketch", "error": str(e)[-200:]},
        )
        raise HTTPException(status_code=502, detail=f"sketch→image failed: {e}") from e

    if not out_bytes:
        bus.emit(
            Events.IMAGE_EDIT_FAILED,
            {"edit_id": edit_id, "kind": "sketch", "error": "no image returned"},
        )
        raise HTTPException(status_code=502, detail="sketch→image returned no image")

    key = _build_storage_key(body.save_scope, body.save_scope_id)
    try:
        storage = get_storage()
        await storage.put(key, out_bytes, "image/png")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("images.from-sketch store failed: %s", e)
        raise HTTPException(status_code=502, detail=f"store failed: {e}") from e

    bus.emit(
        Events.IMAGE_EDITED,
        {
            "edit_id": edit_id,
            "kind": "sketch",
            "image_url": url,
            "scope": body.save_scope,
            "scope_id": body.save_scope_id,
            "prompt_preview": body.prompt[:240],
        },
    )
    return EditOut(image_url=url, edit_id=edit_id)
