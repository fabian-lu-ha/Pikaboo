"""Marketing-video endpoints (the 5th surface).

Three POST routes under `/api/video/`:

  - /suggest  — LLM proposes a 6-frame storyboard from latest brand + campaign.
  - /frame    — generates ONE keyframe via nano-banana-pro (no baked-in text).
  - /render   — invokes the standalone Remotion CLI to composite frames + captions.

Captions live in JSON (returned by /suggest, fed into /render); they are
NEVER baked into the keyframe images (see frame_gen.py for the anti-prompt).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.providers.factory import get_storage
from app.services.video_gen.cast import registry as cast_registry
from app.services.video_gen.canvas import generate_canvas
from app.services.video_gen.critic import (
    critique_effects_in_motion,
    critique_video,
)
from app.services.video_gen.frame_gen import (
    VALID_ASPECTS,
    generate_ingredient,
    generate_video_frame,
)
from app.services.video_gen.improver import (
    apply_mutations,
    get_version,
    list_versions,
    record_version,
)
from app.services.video_gen.renderer import (
    RemotionNotInstalledError,
    build_props,
    render_video,
)
from app.services.video_gen.scene_gen import SceneGenError, generate_scene
from app.services.video_gen.storyboard import suggest_storyboard
from app.services.video_gen.transitions import (
    extract_last_frame_to_storage,
    plan_transitions,
    render_transition_clip,
)
from app.services.video_gen.voiceover import (
    VoiceoverGenError,
    generate_tts_audio,
    mux_audio_into_video,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/video")

# Match the boundary cap mentioned in the spec.
PROMPT_MAX_CHARS = 2000
CAPTION_MAX_CHARS = 120


Aspect = Literal["1:1", "16:9", "9:16"]
CastKindLiteral = Literal["character", "setting", "prop", "product"]
FocalZoneLiteral = Literal[
    "tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"
]


# ── /suggest ─────────────────────────────────────────────────────────────


class CastBindingOut(BaseModel):
    type: Literal["brand_asset", "needs_generation"]
    asset_index: int | None = None


class CastMemberOut(BaseModel):
    id: str
    kind: CastKindLiteral
    role: str
    description: str
    narrative_purpose: str = ""
    neutral_pose_hint: str | None = None
    binding: CastBindingOut
    canonical_url: str | None = None


EffectKindLiteral = Literal[
    "kinetic_text",
    "lower_third",
    "brand_stinger",
    "spotlight",
    "kinetic_lines",
    "data_pop",
]


class EffectOut(BaseModel):
    id: str
    kind: EffectKindLiteral
    params: dict = {}
    start_ms: int | None = None
    duration_ms: int | None = None


FrameKindLiteral = Literal["live_action", "design_sequence"]
DesignTemplateLiteral = Literal[
    "gradient_kinetic",
    "spec_card",
    "ui_zoom",
    "code_window",
    "logo_reveal",
    "comparison_split",
    "text_scroll",
    "headline_punch",
    "word_kinetic",
    "canvas_kinetic",
]


class StoryboardFrameOut(BaseModel):
    id: str
    # kind defaults to live_action so legacy /suggest responses
    # (no kind field) deserialize unchanged.
    kind: FrameKindLiteral = "live_action"
    prompt: str
    motion: str = ""
    caption: str
    duration_ms: int
    cast_refs: list[str] = []
    focal_zone: FocalZoneLiteral = "mc"
    effects: list[EffectOut] = []
    # Only set when kind='design_sequence' — picks the Remotion template
    # and its parameter payload. Frontend's SequenceRouter consumes both.
    template: DesignTemplateLiteral | None = None
    template_params: dict | None = None


class NarrativeOut(BaseModel):
    premise: str = ""
    arc: str = ""
    tone: str = ""


class CinematicBriefOut(BaseModel):
    reference_films: str = ""
    lensing: str = ""
    lighting: str = ""
    palette_grade: str = ""
    pacing: str = ""
    do_not: str = ""


VoiceNameLiteral = Literal[
    "Aoede", "Charon", "Fenrir", "Kore", "Leda",
    "Orus", "Puck", "Schedar", "Vindemiatrix", "Zephyr",
]


class VoiceoverSpecOut(BaseModel):
    script: str = ""
    voice_persona: str = ""
    voice_name: VoiceNameLiteral = "Charon"


class TitleCardOut(BaseModel):
    text: str


class EndCardOut(BaseModel):
    headline: str = ""
    cta: str = ""


class SegmentTargetOut(BaseModel):
    id: str
    name: str
    description: str = ""
    rationale: str = ""
    size: int = 0
    feature_focus: str | None = None
    feature_stats: dict[str, int] = {}
    contributor_counts: dict[str, int] = {}


class SuggestOut(BaseModel):
    storyboard_id: str
    aspect: Aspect
    narrative: NarrativeOut = NarrativeOut()
    cinematic_brief: CinematicBriefOut = CinematicBriefOut()
    voiceover: VoiceoverSpecOut = VoiceoverSpecOut()
    title_card: TitleCardOut | None = None
    end_card: EndCardOut | None = None
    cast: list[CastMemberOut]
    frames: list[StoryboardFrameOut]
    # Echoed back when /suggest was called with a target segment so the
    # frontend can render a "Targeted for: …" banner on the storyboard
    # panel.
    segment: SegmentTargetOut | None = None


class SuggestIn(BaseModel):
    """Optional payload for /suggest. Empty body still works — the legacy
    "generate from latest brand + latest campaign" flow stays intact."""

    segment_id: str | None = None


@router.post("/suggest", response_model=SuggestOut)
async def post_suggest(body: SuggestIn | None = None) -> SuggestOut:
    seg_id = body.segment_id if body is not None else None
    try:
        result = await suggest_storyboard(segment_id=seg_id)
    except LookupError as e:
        # No onboarded brand yet — distinct from a failed LLM call.
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        log.exception("video.suggest failed: %s", e)
        raise HTTPException(status_code=502, detail=f"storyboard llm failed: {e}") from e

    storyboard_id = str(uuid4())
    cast_registry.upsert_storyboard(storyboard_id, result.get("cast") or [])
    # Persist the director's brief on the registry so /scene can fetch it
    # by storyboard_id without round-tripping through the frontend.
    cast_registry.set_brief(storyboard_id, result.get("cinematic_brief") or {})
    # Same pattern for the voiceover spec — /voiceover fetches it by id.
    cast_registry.set_voiceover(storyboard_id, result.get("voiceover") or {})
    # Persist the rest of the planner output (narrative, frames, bookends,
    # aspect) plus brand_id so /storyboard/latest can rehydrate the
    # frontend store after a reload without re-running /suggest.
    brand_for_link = _load_brand_for_frame()
    cast_registry.set_plan(
        storyboard_id,
        brand_id=(brand_for_link or {}).get("id"),
        aspect=result.get("aspect"),
        narrative=result.get("narrative") or {},
        title_card=result.get("title_card"),
        end_card=result.get("end_card"),
        frames=result.get("frames") or [],
    )
    # Persist the segment FK separately — set_plan doesn't take it (the
    # plan helper predates segment-aware /suggest). Direct write to the
    # row, idempotent and tiny.
    seg_target = result.get("segment")
    if seg_target:
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is not None:
                sb.segment_id = seg_target.get("id")
                db.commit()

    payload = {
        "storyboard_id": storyboard_id,
        "aspect": result["aspect"],
        "narrative": result.get("narrative") or {},
        "cinematic_brief": result.get("cinematic_brief") or {},
        "voiceover": result.get("voiceover") or {},
        "title_card": result.get("title_card"),
        "end_card": result.get("end_card"),
        "cast": result.get("cast") or [],
        "frames": result.get("frames") or [],
        "segment": seg_target,
    }
    # storyboard_suggested keeps the full payload (cast + narrative included)
    # so any downstream listener has everything it needs in one event.
    bus.emit(Events.VIDEO_STORYBOARD_SUGGESTED, payload)
    bus.emit(
        Events.VIDEO_CAST_PROPOSED,
        {"storyboard_id": storyboard_id, "cast": payload["cast"]},
    )
    return SuggestOut(**payload)


# ── /ingredient ──────────────────────────────────────────────────────────
# Generates the canonical reference sheet for one cast member that has
# binding.type='needs_generation'. brand_asset bindings short-circuit and
# return the bound URL without calling the model.


class IngredientIn(BaseModel):
    storyboard_id: str = Field(..., min_length=1)
    cast_id: str = Field(..., min_length=1)
    variation_hint: str | None = Field(default=None, max_length=600)


class IngredientOut(BaseModel):
    storyboard_id: str
    cast_id: str
    canonical_url: str
    kind: CastKindLiteral


async def _generate_and_store_ingredient(
    storyboard_id: str,
    cast_id: str,
    variation_hint: str | None,
) -> tuple[str, str]:
    """Shared body of /ingredient and /regenerate-ingredient.

    Returns (canonical_url, kind). Raises HTTPException on failure paths
    so the caller's error handling is uniform.
    """
    member = cast_registry.get_member(storyboard_id, cast_id)
    if member is None:
        # Distinguish "we never knew this storyboard" (frontend should
        # re-suggest) from "this cast id isn't in the storyboard's bible"
        # (frontend bug — wrong id sent). Both are 404 but the actionable
        # next step differs.
        if not cast_registry.has_storyboard(storyboard_id):
            raise HTTPException(
                status_code=404,
                detail=(
                    "storyboard not found — re-run /suggest "
                    f"(storyboard_id={storyboard_id})"
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=f"unknown cast member {cast_id} in storyboard {storyboard_id}",
        )

    brand = _load_brand_for_frame()
    if brand is None:
        raise HTTPException(status_code=409, detail="no onboarded brand")

    cast_for_gen: dict = dict(member)
    if variation_hint:
        base_desc = cast_for_gen.get("description", "") or ""
        cast_for_gen["description"] = (
            f"{base_desc} Variation hint: {variation_hint}".strip()
        )

    try:
        image_bytes = await generate_ingredient(brand, cast_for_gen)
    except Exception as e:
        log.exception("video.ingredient gen failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"ingredient gen failed: {e}"
        ) from e

    if not image_bytes:
        raise HTTPException(
            status_code=502, detail="ingredient gen returned no image"
        )

    key = f"videos/{storyboard_id}/ingredients/{cast_id}.png"
    try:
        storage = get_storage()
        await storage.put(key, image_bytes, "image/png")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("video.ingredient store failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"ingredient store failed: {e}"
        ) from e

    cast_registry.bind_canonical(storyboard_id, cast_id, url)
    kind = str(member.get("kind") or "character")
    return url, kind


@router.post("/ingredient", response_model=IngredientOut)
async def post_ingredient(body: IngredientIn) -> IngredientOut:
    member = cast_registry.get_member(body.storyboard_id, body.cast_id)
    if member is None:
        if not cast_registry.has_storyboard(body.storyboard_id):
            raise HTTPException(
                status_code=404,
                detail=(
                    "storyboard not found — re-run /suggest "
                    f"(storyboard_id={body.storyboard_id})"
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=f"unknown cast member {body.cast_id} in storyboard {body.storyboard_id}",
        )

    binding = member.get("binding") or {}
    bound_url = member.get("canonical_url")
    # Brand-asset binding: already resolved at /suggest time. Return as-is
    # without calling the model.
    if binding.get("type") == "brand_asset" and bound_url:
        kind = str(member.get("kind") or "character")
        bus.emit(
            Events.VIDEO_INGREDIENT_GENERATED,
            {
                "storyboard_id": body.storyboard_id,
                "cast_id": body.cast_id,
                "canonical_url": bound_url,
                "kind": kind,
                "from_brand_asset": True,
            },
        )
        if cast_registry.all_locked(body.storyboard_id):
            bus.emit(
                Events.VIDEO_CAST_BIBLE_LOCKED,
                {"storyboard_id": body.storyboard_id},
            )
        return IngredientOut(
            storyboard_id=body.storyboard_id,
            cast_id=body.cast_id,
            canonical_url=bound_url,
            kind=kind,  # type: ignore[arg-type]
        )

    bus.emit(
        Events.VIDEO_INGREDIENT_GENERATING,
        {
            "storyboard_id": body.storyboard_id,
            "cast_id": body.cast_id,
            "kind": str(member.get("kind") or "character"),
        },
    )

    url, kind = await _generate_and_store_ingredient(
        body.storyboard_id, body.cast_id, body.variation_hint
    )

    bus.emit(
        Events.VIDEO_INGREDIENT_GENERATED,
        {
            "storyboard_id": body.storyboard_id,
            "cast_id": body.cast_id,
            "canonical_url": url,
            "kind": kind,
            "from_brand_asset": False,
        },
    )
    if cast_registry.all_locked(body.storyboard_id):
        bus.emit(
            Events.VIDEO_CAST_BIBLE_LOCKED,
            {"storyboard_id": body.storyboard_id},
        )
    return IngredientOut(
        storyboard_id=body.storyboard_id,
        cast_id=body.cast_id,
        canonical_url=url,
        kind=kind,  # type: ignore[arg-type]
    )


# ── /regenerate-ingredient ───────────────────────────────────────────────
# Same shape as /ingredient but always re-generates (brand_asset bindings
# would not normally call regen — they bypass to /ingredient — but if they
# do, we honour the request and synth a fresh sheet).


class RegenIngredientIn(IngredientIn):
    """Frames that reference this cast become stale after regen."""

    pass


@router.post("/regenerate-ingredient", response_model=IngredientOut)
async def post_regenerate_ingredient(body: RegenIngredientIn) -> IngredientOut:
    member = cast_registry.get_member(body.storyboard_id, body.cast_id)
    if member is None:
        if not cast_registry.has_storyboard(body.storyboard_id):
            raise HTTPException(
                status_code=404,
                detail=(
                    "storyboard not found — re-run /suggest "
                    f"(storyboard_id={body.storyboard_id})"
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=f"unknown cast member {body.cast_id} in storyboard {body.storyboard_id}",
        )

    previous_url = member.get("canonical_url")

    bus.emit(
        Events.VIDEO_INGREDIENT_GENERATING,
        {
            "storyboard_id": body.storyboard_id,
            "cast_id": body.cast_id,
            "kind": str(member.get("kind") or "character"),
            "regenerate": True,
        },
    )

    url, kind = await _generate_and_store_ingredient(
        body.storyboard_id, body.cast_id, body.variation_hint
    )

    bus.emit(
        Events.VIDEO_INGREDIENT_REGENERATED,
        {
            "storyboard_id": body.storyboard_id,
            "cast_id": body.cast_id,
            "canonical_url": url,
            "previous_url": previous_url,
            "kind": kind,
        },
    )
    return IngredientOut(
        storyboard_id=body.storyboard_id,
        cast_id=body.cast_id,
        canonical_url=url,
        kind=kind,  # type: ignore[arg-type]
    )


# ── /frame ───────────────────────────────────────────────────────────────


class FrameIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=PROMPT_MAX_CHARS)
    aspect: Aspect
    storyboard_id: str | None = None
    frame_id: str | None = Field(default=None, max_length=120)
    cast_refs: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("prompt")
    @classmethod
    def _trim_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt must not be blank")
        return v


class FrameOut(BaseModel):
    image_url: str
    frame_id: str | None = None
    cast_refs: list[str] = []


# ── /scene — per-frame Veo clip ──────────────────────────────────────────
# Replaces /frame for the production path. Returns an mp4 clip URL and
# echoes back the frame_id + cast_refs so the frontend can match the
# response to the local storyboard frame.


SceneQualityLiteral = Literal["fast", "quality"]


class SceneIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=PROMPT_MAX_CHARS)
    motion: str = Field(default="", max_length=600)
    aspect: Aspect
    duration_ms: int = Field(default=2500, ge=2000, le=8000)
    storyboard_id: str = Field(..., min_length=1)
    frame_id: str = Field(..., min_length=1, max_length=120)
    cast_refs: list[str] = Field(default_factory=list, max_length=8)
    # Veo model tier — fast (default, ~30-45s) or quality (~60-90s, hero render)
    quality: SceneQualityLiteral = "fast"
    # Per-frame keyframe URL (image_url from a prior /frame call). When set,
    # Veo runs in image-to-video mode with this as the first frame —
    # composition is locked, motion is added. This is the canonical flow.
    keyframe_url: str | None = Field(default=None, max_length=2000)

    @field_validator("prompt")
    @classmethod
    def _trim_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt must not be blank")
        return v


class SceneOut(BaseModel):
    clip_url: str
    frame_id: str
    cast_refs: list[str] = []
    quality: SceneQualityLiteral = "fast"


@router.post("/scene", response_model=SceneOut)
async def post_scene(body: SceneIn) -> SceneOut:
    brand = _load_brand_for_frame()
    if brand is None:
        raise HTTPException(status_code=409, detail="no onboarded brand")

    refs = cast_registry.resolve(body.storyboard_id, body.cast_refs)

    bus.emit(
        Events.VIDEO_SCENE_GENERATING,
        {
            "storyboard_id": body.storyboard_id,
            "frame_id": body.frame_id,
            "cast_refs": list(body.cast_refs),
            "duration_ms": body.duration_ms,
            "quality": body.quality,
            "from_keyframe": bool(body.keyframe_url),
        },
    )

    # Veo's hard floor is 4s — clamp upward defensively even though the
    # plan should already pick within bounds. Remotion will only play
    # `duration_ms` worth of the clip at composite time.
    duration_s = max(4, min(8, round(body.duration_ms / 1000)))

    def _emit_retry(info: dict) -> None:
        bus.emit(
            Events.VIDEO_SCENE_RETRYING,
            {
                "storyboard_id": body.storyboard_id,
                "frame_id": body.frame_id,
                "phase": info["phase"],
                "attempt": info["attempt"],
                "max_attempts": info["max_attempts"],
                "delay_s": info["delay_s"],
                "reason": info["reason"],
            },
        )

    cinematic_brief = cast_registry.get_brief(body.storyboard_id)

    try:
        mp4_bytes = await generate_scene(
            brand=brand,
            scene_prompt=body.prompt,
            aspect=body.aspect,
            duration_s=duration_s,
            cast_refs=refs,
            motion=body.motion,
            quality=body.quality,
            keyframe_url=body.keyframe_url,
            cinematic_brief=cinematic_brief,
            on_retry=_emit_retry,
        )
    except SceneGenError as e:
        # User-facing — message is already concise (e.g. "aspectRatio does
        # not support 1:1", "durationSeconds out of bound", etc).
        log.warning("video.scene gen rejected: %s", e)
        raise HTTPException(status_code=502, detail=f"Veo: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("video.scene gen failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"scene gen failed: {e}"
        ) from e

    if not mp4_bytes:
        # Should be unreachable now — generate_scene raises on every
        # failure path — but keep the safety net.
        raise HTTPException(
            status_code=502, detail="scene gen returned no clip"
        )

    key = f"videos/{body.storyboard_id}/scenes/{body.frame_id}.mp4"
    try:
        storage = get_storage()
        await storage.put(key, mp4_bytes, "video/mp4")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("video.scene store failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"scene store failed: {e}"
        ) from e

    # Persist the clip URL onto the storyboard so the frontend can recover
    # this Veo render after a reload — the file would still be on disk but
    # the frontend would have no way to find it without DB-side tracking.
    cast_registry.update_frame(
        body.storyboard_id, body.frame_id, {"clip_url": url}
    )

    bus.emit(
        Events.VIDEO_SCENE_GENERATED,
        {
            "storyboard_id": body.storyboard_id,
            "frame_id": body.frame_id,
            "clip_url": url,
            "aspect": body.aspect,
            "cast_refs": list(body.cast_refs),
            "duration_ms": body.duration_ms,
            "quality": body.quality,
            "from_keyframe": bool(body.keyframe_url),
        },
    )
    return SceneOut(
        clip_url=url,
        frame_id=body.frame_id,
        cast_refs=list(body.cast_refs),
        quality=body.quality,
    )


def _load_brand_for_frame() -> dict | None:
    """Snapshot the latest onboarded brand for keyframe generation. Mirrors
    the agent's `_load_latest_brand` pattern but only reads the fields
    frame_gen actually consumes."""
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


@router.post("/frame", response_model=FrameOut)
async def post_frame(body: FrameIn) -> FrameOut:
    brand = _load_brand_for_frame()
    if brand is None:
        raise HTTPException(status_code=409, detail="no onboarded brand")

    # Resolve cast_refs against the storyboard registry. If storyboard_id is
    # missing or the registry doesn't know it, refs become an empty list and
    # frame_gen falls back to its no-cast prompt path.
    refs: list = []
    if body.storyboard_id and body.cast_refs:
        refs = cast_registry.resolve(body.storyboard_id, body.cast_refs)

    bus.emit(
        Events.VIDEO_FRAME_GENERATING,
        {
            "storyboard_id": body.storyboard_id,
            "frame_id": body.frame_id,
            "cast_refs": list(body.cast_refs),
        },
    )

    try:
        image_bytes = await generate_video_frame(
            brand, body.prompt, body.aspect, cast_refs=refs
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("video.frame gen failed: %s", e)
        raise HTTPException(status_code=502, detail=f"frame gen failed: {e}") from e

    if not image_bytes:
        # Most often: GEMINI_API_KEY missing or model returned no image part.
        raise HTTPException(status_code=502, detail="frame gen returned no image")

    # Storage path — prefer storyboard scope so all assets for a single video
    # cluster under videos/{sid}/. Falls back to a one-off uuid scope when
    # the caller hasn't suggested a storyboard yet.
    if body.storyboard_id:
        frame_slug = uuid4().hex[:8]
        key = f"videos/{body.storyboard_id}/frames/{frame_slug}.png"
    else:
        video_id = str(uuid4())
        frame_slug = uuid4().hex[:8]
        key = f"videos/{video_id}/frames/{frame_slug}.png"
    try:
        storage = get_storage()
        await storage.put(key, image_bytes, "image/png")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("video.frame store failed: %s", e)
        raise HTTPException(status_code=502, detail=f"frame store failed: {e}") from e

    # Persist the keyframe URL on the storyboard so a reload can recover it
    # without re-running /frame and burning another nano-banana-pro call.
    if body.storyboard_id and body.frame_id:
        cast_registry.update_frame(
            body.storyboard_id, body.frame_id, {"image_url": url}
        )

    bus.emit(
        Events.VIDEO_FRAME_GENERATED,
        {
            "storyboard_id": body.storyboard_id,
            "frame_id": body.frame_id,
            "image_url": url,
            "aspect": body.aspect,
            "prompt_preview": body.prompt[:240],
            "cast_refs": list(body.cast_refs),
        },
    )
    return FrameOut(
        image_url=url,
        frame_id=body.frame_id,
        cast_refs=list(body.cast_refs),
    )


# ── /render ──────────────────────────────────────────────────────────────


class RenderEffectIn(BaseModel):
    id: str = Field(..., min_length=1)
    kind: EffectKindLiteral
    params: dict = Field(default_factory=dict)
    start_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=60)


class RenderFrameIn(BaseModel):
    # live_action frames need clip_url or image_url. design_sequence frames
    # need template + template_params and don't carry mp4/png at all (the
    # Remotion template renders them from scratch).
    kind: FrameKindLiteral = "live_action"
    clip_url: str | None = Field(default=None)
    image_url: str | None = Field(default=None)
    caption: str = Field(default="", max_length=CAPTION_MAX_CHARS)
    duration_ms: int = Field(..., ge=300, le=15000)
    focal_zone: FocalZoneLiteral = "mc"
    effects: list[RenderEffectIn] = Field(default_factory=list, max_length=3)
    # Frontend-side frame identifier — only required when transitions are
    # enabled (so the planner can name pairs as "f0_f1" etc.). Legacy
    # callers without this still render fine; transitions just won't fire.
    frame_id: str | None = Field(default=None, max_length=120)
    # design_sequence-only — Remotion's SequenceRouter picks the right
    # template and feeds it the params object.
    template: DesignTemplateLiteral | None = Field(default=None)
    template_params: dict | None = Field(default=None)

    @model_validator(mode="after")
    def _shape_per_kind(self) -> "RenderFrameIn":
        if self.kind == "design_sequence":
            if not self.template:
                raise ValueError(
                    "design_sequence frames require `template`"
                )
            # template_params is optional — most templates have sensible
            # defaults, but the renderer needs at least an empty dict so
            # the discriminator inside Remotion is happy.
            if self.template_params is None:
                self.template_params = {}
            # canvas_kinetic carries an LLM-authored canvas_prompt the
            # backend uses to generate the nano-banana backdrop at render
            # time. canvas_url is filled in server-side — callers should
            # not provide it. Require canvas_prompt so the renderer has
            # something to send to nano-banana.
            if self.template == "canvas_kinetic":
                cp = str(self.template_params.get("canvas_prompt") or "").strip()
                if not cp:
                    raise ValueError(
                        "canvas_kinetic frame requires "
                        "template_params.canvas_prompt"
                    )
            self.template_params.setdefault("template", self.template)
            return self
        # live_action: must have clip_url or image_url.
        if not self.clip_url and not self.image_url:
            raise ValueError(
                "live_action frame must include clip_url or image_url"
            )
        return self


class RenderTitleCardIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=80)


class RenderEndCardIn(BaseModel):
    headline: str = Field(default="", max_length=120)
    cta: str = Field(default="", max_length=40)


class RenderIn(BaseModel):
    aspect: Aspect
    frames: list[RenderFrameIn] = Field(..., min_length=1, max_length=24)
    title_card: RenderTitleCardIn | None = None
    end_card: RenderEndCardIn | None = None
    # Optional: when supplied, the rendered video_url is persisted on the
    # storyboard row so the frontend can recover it after a reload. The
    # render path stays valid without it (legacy callers still work).
    storyboard_id: str | None = Field(default=None, max_length=120)


class RenderOut(BaseModel):
    video_id: str
    video_url: str
    duration_ms: int


def _load_brand_for_render() -> dict | None:
    """Lighter snapshot: only what the Remotion props need (palette + fonts)."""
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
            "palette": brand.palette,
            "palette_roles": brand.palette_roles,
            "identity": brand.identity,
        }


async def _plan_and_render_transitions(
    body: RenderIn,
    brand: dict | None,
) -> list[dict]:
    """Run the inter-scene transitions planner + bridge renderer when the
    feature flag is on. Returns a (possibly empty) list of decision dicts
    suitable for ``build_props(transitions=...)``.

    Failure modes are intentionally non-fatal:
      * planner LLM fails → empty list (render proceeds without bridges).
      * any single Veo bridge fails → that decision is downgraded to
        ``match_cut`` and the render still proceeds.
      * ffmpeg can't extract a from-frame → bridge is downgraded to
        ``match_cut`` (we'd otherwise fire Veo on bad inputs).

    Each decision in the returned list shares the planner shape
    (``from_id, to_id, style, reason, motion_hint``) plus a ``clip_url``
    field that's None for non-bridge styles.
    """
    if not settings.enable_veo_transitions:
        return []
    if len(body.frames) < 2:
        return []
    if not body.storyboard_id:
        log.info(
            "video.render: transitions skipped — flag on but no storyboard_id "
            "supplied (planner needs it to scope storage paths)"
        )
        return []

    # Build per-scene dicts for the planner. We prefer the caller-supplied
    # frame_id (gives stable pair labels like "f0_f1"); fall back to the
    # array index when the frontend hasn't plumbed ids through yet.
    sb_brief = cast_registry.get_brief(body.storyboard_id) or {}
    # Try to enrich each frame with the planner's prompt + motion if we
    # have it on the storyboard registry — gives the LLM real shot context
    # rather than just "Scene 0, Scene 1, ...".
    sb_full = cast_registry.get_full_storyboard(body.storyboard_id) or {}
    sb_frames_by_id = {
        f.get("id"): f for f in (sb_full.get("frames") or []) if isinstance(f, dict)
    }

    planner_scenes: list[dict] = []
    for i, f in enumerate(body.frames):
        fid = f.frame_id or f"scene_{i}"
        sb_meta = sb_frames_by_id.get(fid) or {}
        planner_scenes.append(
            {
                "frame_id": fid,
                "clip_url": f.clip_url,
                "image_url": f.image_url,
                "prompt": sb_meta.get("prompt") or "",
                "motion": sb_meta.get("motion") or "",
                "caption": f.caption,
            }
        )

    bus.emit(
        Events.VIDEO_TRANSITIONS_PLANNING,
        {
            "storyboard_id": body.storyboard_id,
            "scene_count": len(planner_scenes),
        },
    )

    try:
        decisions = await plan_transitions(
            scenes=planner_scenes,
            brand=brand or {},
            cinematic_brief=sb_brief,
        )
    except Exception as e:
        log.warning(
            "video.render: transitions planner crashed (%s) — rendering without",
            e,
        )
        bus.emit(
            Events.VIDEO_TRANSITIONS_PLANNED,
            {
                "storyboard_id": body.storyboard_id,
                "decisions": [],
                "error": str(e)[:300],
            },
        )
        return []

    bus.emit(
        Events.VIDEO_TRANSITIONS_PLANNED,
        {
            "storyboard_id": body.storyboard_id,
            "decisions": [
                {
                    "from_id": d.get("from_id"),
                    "to_id": d.get("to_id"),
                    "style": d.get("style"),
                    "reason": d.get("reason"),
                }
                for d in decisions
            ],
        },
    )

    # Render Veo bridges for any veo_bridge decisions. We do this serially
    # so we don't hammer Veo with extra concurrent submissions on top of
    # whatever scene-gen pressure is in flight; bridges are a luxury and
    # 30-60s extra latency is acceptable.
    transitions_out: list[dict] = []
    for i, d in enumerate(decisions):
        base = {
            "from_id": d.get("from_id"),
            "to_id": d.get("to_id"),
            "style": d.get("style") or "match_cut",
            "reason": d.get("reason") or "",
            "motion_hint": d.get("motion_hint"),
            "clip_url": None,
        }
        if base["style"] != "veo_bridge":
            transitions_out.append(base)
            continue

        # Find the from-scene clip and the to-scene keyframe.
        from_idx = i
        to_idx = i + 1
        from_clip_url = body.frames[from_idx].clip_url
        to_keyframe_url = (
            body.frames[to_idx].image_url or body.frames[to_idx].clip_url
        )
        pair_id = f"{base['from_id']}_{base['to_id']}"

        if not from_clip_url or not to_keyframe_url:
            log.info(
                "video.render: bridge pair %s missing inputs (from_clip=%s, "
                "to_keyframe=%s) — downgrading to match_cut",
                pair_id, bool(from_clip_url), bool(to_keyframe_url),
            )
            base["style"] = "match_cut"
            base["reason"] = (
                (base["reason"] or "")
                + " [downgraded: missing bridge inputs]"
            )
            transitions_out.append(base)
            continue

        # Extract last-frame PNG from the from-scene clip and persist it
        # so render_transition_clip can fetch via storage URL.
        try:
            from_last_url = await extract_last_frame_to_storage(
                mp4_url=from_clip_url,
                storyboard_id=body.storyboard_id,
                frame_label=pair_id,
            )
        except Exception as e:
            log.warning(
                "video.render: bridge pair %s ffmpeg extract crashed (%s) — "
                "downgrading to match_cut",
                pair_id, e,
            )
            from_last_url = None

        if from_last_url is None:
            base["style"] = "match_cut"
            base["reason"] = (
                (base["reason"] or "")
                + " [downgraded: last-frame extract failed]"
            )
            transitions_out.append(base)
            continue

        bus.emit(
            Events.VIDEO_TRANSITION_GENERATING,
            {
                "storyboard_id": body.storyboard_id,
                "pair_id": pair_id,
                "from_id": base["from_id"],
                "to_id": base["to_id"],
                "motion_hint": base["motion_hint"],
            },
        )

        def _emit_retry(info: dict, _pair=pair_id) -> None:
            # Reuse the scene retry event — the UI distinguishes by the
            # presence of pair_id vs frame_id.
            bus.emit(
                Events.VIDEO_SCENE_RETRYING,
                {
                    "storyboard_id": body.storyboard_id,
                    "pair_id": _pair,
                    "phase": info["phase"],
                    "attempt": info["attempt"],
                    "max_attempts": info["max_attempts"],
                    "delay_s": info["delay_s"],
                    "reason": info["reason"],
                },
            )

        try:
            tclip_url = await render_transition_clip(
                from_frame_url=from_last_url,
                to_frame_url=to_keyframe_url,
                motion_hint=base["motion_hint"] or "",
                brand=brand or {},
                storyboard_id=body.storyboard_id,
                pair_id=pair_id,
                on_retry=_emit_retry,
                aspect=body.aspect,
            )
            base["clip_url"] = tclip_url
            transitions_out.append(base)
            bus.emit(
                Events.VIDEO_TRANSITION_GENERATED,
                {
                    "storyboard_id": body.storyboard_id,
                    "pair_id": pair_id,
                    "from_id": base["from_id"],
                    "to_id": base["to_id"],
                    "clip_url": tclip_url,
                },
            )
        except Exception as e:
            log.warning(
                "video.render: bridge pair %s failed (%s) — downgrading to match_cut",
                pair_id, e,
            )
            bus.emit(
                Events.VIDEO_TRANSITION_FAILED,
                {
                    "storyboard_id": body.storyboard_id,
                    "pair_id": pair_id,
                    "error": str(e)[:400],
                },
            )
            base["style"] = "match_cut"
            base["reason"] = (
                (base["reason"] or "")
                + f" [downgraded: bridge gen failed: {str(e)[:120]}]"
            )
            transitions_out.append(base)

    return transitions_out


async def _ensure_canvases(
    body: RenderIn,
    canvas_brand: dict | None,
) -> dict[int, str]:
    """Generate any missing canvas_kinetic backdrops in parallel.

    Returns a dict mapping frame index → canvas_url for the frames where
    nano-banana succeeded. Frames with an existing template_params.canvas_url
    are skipped (idempotent). Frames where generation fails are NOT in the
    returned dict — the caller wires canvas_url=None and the Remotion side
    falls back to a brand gradient bg.

    nano-banana-pro has higher throughput than Veo, so we fire all canvas
    requests concurrently with asyncio.gather.
    """
    if not body.storyboard_id:
        # Without a storyboard_id we can't scope the storage key cleanly.
        # Fall back to using the first 8 chars of the video uuid via a
        # deterministic hint — but for v1 just skip canvas gen and let the
        # Remotion fallback render.
        log.info(
            "video.render: canvas_kinetic frames present but no "
            "storyboard_id — skipping canvas gen, frontend will fall back"
        )
        return {}

    pending: list[tuple[int, str, str]] = []  # (frame_idx, frame_id, canvas_prompt)
    for idx, f in enumerate(body.frames):
        if f.kind != "design_sequence":
            continue
        if f.template != "canvas_kinetic":
            continue
        params = f.template_params or {}
        if params.get("canvas_url"):
            continue  # already generated, skip
        canvas_prompt = str(params.get("canvas_prompt") or "").strip()
        if not canvas_prompt:
            continue  # validator should have caught this — defensive
        frame_id = (f.frame_id or f"f{idx}").strip() or f"f{idx}"
        pending.append((idx, frame_id, canvas_prompt))

    if not pending:
        return {}

    bus.emit(
        Events.VIDEO_CANVAS_GEN_STARTED,
        {
            "storyboard_id": body.storyboard_id,
            "count": len(pending),
        },
    )

    async def _one(frame_id: str, canvas_prompt: str) -> str | None:
        try:
            return await generate_canvas(
                brand=canvas_brand or {},
                canvas_prompt=canvas_prompt,
                aspect=body.aspect,
                storyboard_id=body.storyboard_id or "",
                frame_id=frame_id,
            )
        except Exception as e:
            log.warning(
                "video.render: canvas gen for frame %s failed: %s",
                frame_id, e,
            )
            return None

    results = await asyncio.gather(
        *[_one(fid, prompt) for _, fid, prompt in pending]
    )

    out: dict[int, str] = {}
    for (idx, _fid, _prompt), url in zip(pending, results, strict=True):
        if url:
            out[idx] = url

    bus.emit(
        Events.VIDEO_CANVAS_GEN_COMPLETED,
        {
            "storyboard_id": body.storyboard_id,
            "succeeded": len(out),
            "failed": len(pending) - len(out),
        },
    )
    return out


@router.post("/render", response_model=RenderOut)
async def post_render(body: RenderIn) -> RenderOut:
    brand = _load_brand_for_render()  # may be None — Remotion uses sensible defaults

    # Pre-generate canvas_kinetic backdrops via nano-banana before we hand
    # frames to build_props. Canvas brand needs the richer 'name' /
    # 'style_profile' fields, so pull a heavier snapshot when there's at
    # least one canvas_kinetic frame; otherwise skip the extra DB hit.
    needs_canvas_brand = any(
        f.kind == "design_sequence"
        and f.template == "canvas_kinetic"
        and not (f.template_params or {}).get("canvas_url")
        and (f.template_params or {}).get("canvas_prompt")
        for f in body.frames
    )
    canvas_brand = _load_brand_for_frame() if needs_canvas_brand else None
    canvas_urls = await _ensure_canvases(body, canvas_brand)

    frames_payload: list[dict] = []
    for idx, f in enumerate(body.frames):
        params_out: dict | None = f.template_params
        if (
            f.kind == "design_sequence"
            and f.template == "canvas_kinetic"
        ):
            base_params = dict(f.template_params or {})
            new_url = canvas_urls.get(idx)
            if new_url:
                base_params["canvas_url"] = new_url
            params_out = base_params
        frames_payload.append(
            {
                "kind": f.kind,
                "clip_url": f.clip_url,
                "image_url": f.image_url,
                "caption": f.caption,
                "duration_ms": f.duration_ms,
                "focal_zone": f.focal_zone,
                "effects": [e.model_dump() for e in f.effects],
                # Only set when kind='design_sequence' — build_props ignores
                # them on live_action.
                "template": f.template,
                "template_params": params_out,
            }
        )
    title_payload = (
        {"text": body.title_card.text} if body.title_card else None
    )
    end_payload = (
        {
            "headline": body.end_card.headline,
            "cta": body.end_card.cta,
        }
        if body.end_card
        else None
    )

    # Plan + render AI-decided inter-scene transitions when the feature
    # flag is on AND we have ≥2 frames AND a storyboard_id (we need it
    # both for the transitions storage path and for resolving frame_ids).
    transitions_payload = await _plan_and_render_transitions(
        body=body,
        brand=brand,
    )

    props = build_props(
        body.aspect,
        frames_payload,
        brand,
        title_card=title_payload,
        end_card=end_payload,
        transitions=transitions_payload,
    )

    video_id = str(uuid4())
    bus.emit(
        Events.VIDEO_RENDER_STARTED,
        {
            "video_id": video_id,
            "aspect": body.aspect,
            "frame_count": len(body.frames),
            "transition_count": len(transitions_payload),
        },
    )

    try:
        mp4_bytes, total_duration_ms = await render_video(props)
    except RemotionNotInstalledError as e:
        bus.emit(
            Events.VIDEO_RENDER_FAILED,
            {
                "video_id": video_id,
                "error": e.reason,
                "stderr": (e.stderr or "")[-1200:],
            },
        )
        # 503 — service partially unavailable until Remotion is set up.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "remotion not installed",
                "stderr": (e.stderr or e.reason)[-1200:],
            },
        ) from e
    except Exception as e:
        log.exception("video.render failed: %s", e)
        stderr_tail = str(e)[-1200:]
        bus.emit(
            Events.VIDEO_RENDER_FAILED,
            {"video_id": video_id, "error": "render failed", "stderr": stderr_tail},
        )
        raise HTTPException(status_code=502, detail=f"render failed: {stderr_tail}") from e

    key = f"videos/{video_id}/output.mp4"
    try:
        storage = get_storage()
        await storage.put(key, mp4_bytes, "video/mp4")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("video.render store failed: %s", e)
        bus.emit(
            Events.VIDEO_RENDER_FAILED,
            {"video_id": video_id, "error": "store failed", "stderr": str(e)[-400:]},
        )
        raise HTTPException(status_code=502, detail=f"video store failed: {e}") from e

    # Persist the rendered video on the storyboard row so reload recovers
    # the URL — only when the caller plumbed storyboard_id through. We also
    # null out any prior voiced_video_url because a fresh silent render
    # invalidates the previously-muxed voiceover track.
    if body.storyboard_id:
        cast_registry.set_render(
            body.storyboard_id,
            video_id=video_id,
            video_url=url,
            duration_ms=total_duration_ms,
        )
        # Auto-record v1 (the first successful render). The improver
        # de-dupes on (video_url, critique=None) so re-runs don't pile
        # duplicate v1 entries; v2+ always carry a critique payload so
        # they're never deduped.
        try:
            record_version(
                body.storyboard_id,
                frames=frames_payload,
                video_url=url,
                critique=None,
                applied_mutations=None,
                aspect=body.aspect,
                title_card=title_payload,
                end_card=end_payload,
            )
        except Exception as e:
            log.warning(
                "video.render: v1 version snapshot failed (non-fatal): %s", e
            )

    bus.emit(
        Events.VIDEO_RENDERED,
        {
            "video_id": video_id,
            "video_url": url,
            "duration_ms": total_duration_ms,
            "frame_count": len(body.frames),
            "storyboard_id": body.storyboard_id,
        },
    )
    return RenderOut(
        video_id=video_id, video_url=url, duration_ms=total_duration_ms
    )


# ── /voiceover ───────────────────────────────────────────────────────────
# Adds a Gemini-TTS narration track to an already-rendered silent video.
# Script and voice spec default to what the planner authored at /suggest
# time (stored on the registry by storyboard_id) — callers may override
# any field for one-off variations. The original silent mp4 stays in
# storage; the voiced one is a sibling artifact at output_voiced.mp4.


class VoiceoverIn(BaseModel):
    storyboard_id: str = Field(..., min_length=1)
    video_id: str = Field(..., min_length=1)
    # Optional overrides — when omitted, we use the planner's voiceover spec.
    script: str | None = Field(default=None, max_length=2000)
    voice_persona: str | None = Field(default=None, max_length=400)
    voice_name: VoiceNameLiteral | None = None


class VoiceoverOut(BaseModel):
    video_id: str
    video_url: str
    voice_name: VoiceNameLiteral
    script: str


def _resolve_local_video_bytes(video_id: str) -> bytes | None:
    """Read the rendered mp4 back off local storage so we can mux audio
    in. Supabase mode is not yet supported — return None and the caller
    raises a 503 so the failure surfaces clearly."""
    if settings.deploy_mode != "local":
        return None
    path = Path(settings.storage_dir) / "videos" / video_id / "output.mp4"
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


@router.post("/voiceover", response_model=VoiceoverOut)
async def post_voiceover(body: VoiceoverIn) -> VoiceoverOut:
    spec = cast_registry.get_voiceover(body.storyboard_id) or {}

    script = (body.script or spec.get("script") or "").strip()
    voice_persona = (body.voice_persona or spec.get("voice_persona") or "").strip()
    voice_name = body.voice_name or spec.get("voice_name") or "Charon"
    if not script:
        raise HTTPException(
            status_code=409,
            detail=(
                "no voiceover script available — re-run /suggest or pass "
                "an explicit script in the request body"
            ),
        )

    video_bytes = _resolve_local_video_bytes(body.video_id)
    if video_bytes is None:
        raise HTTPException(
            status_code=409,
            detail=f"rendered video {body.video_id} not found in local storage",
        )

    bus.emit(
        Events.VIDEO_VOICEOVER_GENERATING,
        {
            "video_id": body.video_id,
            "storyboard_id": body.storyboard_id,
            "voice_name": voice_name,
            "word_count": len(script.split()),
        },
    )

    try:
        wav_bytes = await generate_tts_audio(
            script=script,
            voice_persona=voice_persona,
            voice_name=voice_name,
        )
    except VoiceoverGenError as e:
        log.warning("video.voiceover tts failed: %s", e)
        bus.emit(
            Events.VIDEO_VOICEOVER_FAILED,
            {"video_id": body.video_id, "error": str(e)[:400]},
        )
        raise HTTPException(status_code=502, detail=f"voiceover tts: {e}") from e
    except Exception as e:
        log.exception("video.voiceover gen failed: %s", e)
        bus.emit(
            Events.VIDEO_VOICEOVER_FAILED,
            {"video_id": body.video_id, "error": str(e)[:400]},
        )
        raise HTTPException(
            status_code=502, detail=f"voiceover gen failed: {e}"
        ) from e

    try:
        muxed_bytes = await mux_audio_into_video(video_bytes, wav_bytes)
    except VoiceoverGenError as e:
        log.warning("video.voiceover mux failed: %s", e)
        bus.emit(
            Events.VIDEO_VOICEOVER_FAILED,
            {"video_id": body.video_id, "error": str(e)[:400]},
        )
        raise HTTPException(status_code=502, detail=f"voiceover mux: {e}") from e

    storage = get_storage()
    audio_key = f"videos/{body.video_id}/voiceover.wav"
    voiced_key = f"videos/{body.video_id}/output_voiced.mp4"
    try:
        await storage.put(audio_key, wav_bytes, "audio/wav")
        await storage.put(voiced_key, muxed_bytes, "video/mp4")
        voiced_url = await storage.get_url(voiced_key)
    except Exception as e:
        log.exception("video.voiceover store failed: %s", e)
        bus.emit(
            Events.VIDEO_VOICEOVER_FAILED,
            {"video_id": body.video_id, "error": str(e)[:400]},
        )
        raise HTTPException(
            status_code=502, detail=f"voiceover store failed: {e}"
        ) from e

    # Persist the voiced URL on the storyboard so reload picks the muxed
    # mp4 over the silent original automatically.
    cast_registry.set_voiced_video(body.storyboard_id, voiced_url)

    bus.emit(
        Events.VIDEO_VOICEOVER_GENERATED,
        {
            "video_id": body.video_id,
            "storyboard_id": body.storyboard_id,
            "video_url": voiced_url,
            "voice_name": voice_name,
            "script": script,
        },
    )
    return VoiceoverOut(
        video_id=body.video_id,
        video_url=voiced_url,
        voice_name=voice_name,
        script=script,
    )


# ── /storyboard/latest ───────────────────────────────────────────────────
# Hydration endpoint: returns the most-recent storyboard for the latest
# brand, including frames (with image_url + clip_url), narrative, brief,
# voiceover spec, and the post-render artifacts (silent + voiced URLs).
# The frontend store calls this on mount so a page reload doesn't lose
# in-flight work.


class StoryboardVersionIndexEntry(BaseModel):
    """Lightweight version-index entry — frame snapshots are loaded via
    the dedicated /version/{n} route."""

    version_number: int
    video_url: str | None = None
    summary: str | None = None
    mutation_count: int = 0
    created_at: str | None = None


class StoryboardFullOut(BaseModel):
    storyboard_id: str
    brand_id: str | None = None
    aspect: Aspect
    narrative: NarrativeOut = NarrativeOut()
    cinematic_brief: CinematicBriefOut = CinematicBriefOut()
    voiceover: VoiceoverSpecOut = VoiceoverSpecOut()
    title_card: TitleCardOut | None = None
    end_card: EndCardOut | None = None
    cast: list[CastMemberOut]
    # Frames carry image_url + clip_url so the UI can re-display the
    # rendered keyframes / Veo clips without re-running gen.
    frames: list[dict]
    video_id: str | None = None
    video_url: str | None = None
    video_duration_ms: int | None = None
    voiced_video_url: str | None = None
    # Targeted segment (when /suggest was called with a segment_id) — the
    # frontend renders a "Targeted for: …" banner from this and the
    # planner's prompts already cascaded through it.
    segment: SegmentTargetOut | None = None
    # Append-only version history for the improvement loop. Each entry
    # carries enough metadata to render a version-picker chip; full
    # frame snapshots load on demand via /version/{n}.
    versions: list[StoryboardVersionIndexEntry] = []
    current_version: int = 1
    updated_at: str | None = None


@router.get("/storyboard/latest", response_model=StoryboardFullOut | None)
async def get_latest_storyboard() -> StoryboardFullOut | None:
    """Return the most-recently-touched storyboard for the latest brand.

    None (HTTP 200 with `null` body) when no storyboard exists yet — the
    frontend treats null as "show empty state, prompt user to /suggest".
    """
    brand = _load_brand_for_frame()
    brand_id = (brand or {}).get("id")
    full = cast_registry.get_latest_for_brand(brand_id)
    if full is None:
        return None
    return StoryboardFullOut(**full)


# ── /critique ────────────────────────────────────────────────────────────
# Multimodal Gemini reviews a rendered v1 (or any version) and returns a
# structured plan: weaknesses + concrete mutations the user can approve
# one-by-one. Plan-only — never auto-applies. The /improve endpoint takes
# the user's approved subset and materialises v2.


class CritiqueFrameIn(BaseModel):
    """Frame snapshot the critic sees. We accept the wide superset of
    fields the UI carries — the critic ignores anything not relevant."""

    id: str
    kind: FrameKindLiteral = "live_action"
    prompt: str = ""
    motion: str = ""
    caption: str = ""
    duration_ms: int = 2500
    focal_zone: FocalZoneLiteral = "mc"
    cast_refs: list[str] = Field(default_factory=list)
    image_url: str | None = None
    clip_url: str | None = None
    template: DesignTemplateLiteral | None = None
    template_params: dict | None = None
    effects: list[dict] = Field(default_factory=list)


class CritiqueIn(BaseModel):
    storyboard_id: str = Field(..., min_length=1)
    video_url: str = Field(..., min_length=1, max_length=2000)
    frames: list[CritiqueFrameIn] = Field(..., min_length=1, max_length=24)


class CritiqueWeaknessOut(BaseModel):
    id: str
    frame_id: str | None = None
    transition: str | None = None
    issue: str
    severity: Literal["high", "medium", "low"]
    category: Literal[
        "contrast",
        "cut",
        "motion",
        "composition",
        "pacing",
        "narrative",
        "consistency",
    ]
    # Tag for the dual-pass aggregator. "macro" = thumbnail critic,
    # "effects" = full-video motion-graphics critic. Optional for
    # backwards-compatibility with cached plans on disk.
    source: Literal["macro", "effects"] | None = None


class CritiqueMutationOut(BaseModel):
    id: str
    weakness_ids: list[str] = []
    target: str
    # `from`/`to` are unconstrained (str/dict/int/None depending on the
    # target) so we keep them as plain dicts on the wire.
    from_: object | None = Field(default=None, alias="from")
    to: object | None = None
    reason: str = ""
    cost: Literal["free", "render", "veo"]
    estimated_seconds: int
    # Tag for the dual-pass aggregator (see CritiqueWeaknessOut.source).
    source: Literal["macro", "effects"] | None = None

    model_config = {"populate_by_name": True}


class CritiqueOut(BaseModel):
    storyboard_id: str
    video_url: str
    summary: str
    weaknesses: list[CritiqueWeaknessOut] = []
    mutations: list[CritiqueMutationOut] = []
    # Set when the multimodal call degraded (no thumbnails extracted, no
    # Gemini key, JSON parse failure, etc). Plan is still returned so
    # the UI can show the failure and let the user dismiss it.
    error: str | None = None


@router.post("/critique", response_model=CritiqueOut)
async def post_critique(body: CritiqueIn) -> CritiqueOut:
    """Run the multimodal critic against a rendered video. PLAN-ONLY —
    never mutates the storyboard. The user picks which mutations to
    apply via /improve."""
    bus.emit(
        Events.VIDEO_CRITIQUING,
        {
            "storyboard_id": body.storyboard_id,
            "video_url": body.video_url,
            "frame_count": len(body.frames),
        },
    )

    frames_payload = [f.model_dump() for f in body.frames]

    # Run BOTH passes in parallel. Macro critic uses thumbnails (existing
    # behaviour); effects critic uses Gemini's native video input. The
    # aggregator below tags each weakness/mutation with its source so the
    # UI can label them and the user can filter.
    async def _safe_macro() -> dict:
        try:
            return await critique_video(
                storyboard_id=body.storyboard_id,
                video_url=body.video_url,
                frames=frames_payload,
            )
        except Exception as e:
            log.exception("video.critique macro pass failed: %s", e)
            return {
                "summary": "Macro critic unavailable — see backend logs.",
                "weaknesses": [],
                "mutations": [],
                "error": str(e)[:240],
            }

    async def _safe_effects() -> dict:
        try:
            return await critique_effects_in_motion(
                storyboard_id=body.storyboard_id,
                video_url=body.video_url,
                frames=frames_payload,
            )
        except Exception as e:
            log.exception("video.critique effects pass failed: %s", e)
            return {
                "summary": "",
                "weaknesses": [],
                "mutations": [],
                "error": str(e)[:240],
            }

    macro, effects = await asyncio.gather(_safe_macro(), _safe_effects())

    # Aggregate both passes. Tag every weakness + mutation with its source
    # so the modal can show a [macro] / [effects] chip and filter by pass.
    macro_summary = (macro.get("summary") or "").strip()
    effects_summary = (effects.get("summary") or "").strip()
    combined_summary = " ".join(s for s in [macro_summary, effects_summary] if s)

    weaknesses_combined: list[dict] = [
        {**w, "source": "macro"} for w in (macro.get("weaknesses") or [])
    ] + [
        {**w, "source": "effects"} for w in (effects.get("weaknesses") or [])
    ]
    mutations_combined: list[dict] = [
        {**m, "source": "macro"} for m in (macro.get("mutations") or [])
    ] + [
        {**m, "source": "effects"} for m in (effects.get("mutations") or [])
    ]

    # Surface either pass's error via a single field — concatenate when
    # both fired so the UI can show both reasons.
    err_parts = [
        f"macro: {macro['error']}" for _ in [0] if macro.get("error")
    ] + [
        f"effects: {effects['error']}" for _ in [0] if effects.get("error")
    ]
    error_combined = "; ".join(err_parts) or None

    out_payload = {
        "storyboard_id": body.storyboard_id,
        "video_url": body.video_url,
        "summary": combined_summary,
        "weaknesses": weaknesses_combined,
        "mutations": [
            # Pydantic alias for `from` is `from_` — pre-rename on the
            # wire so the model accepts the LLM's natural output.
            {**m, "from_": m.get("from")}
            for m in mutations_combined
        ],
        "error": error_combined,
    }

    bus.emit(
        Events.VIDEO_CRITIQUED,
        {
            "storyboard_id": body.storyboard_id,
            "weakness_count": len(weaknesses_combined),
            "mutation_count": len(mutations_combined),
            "summary": combined_summary,
            "error": error_combined,
        },
    )
    bus.emit(
        Events.VIDEO_IMPROVEMENT_PROPOSED,
        {
            "storyboard_id": body.storyboard_id,
            "mutations": [
                {
                    "id": m.get("id"),
                    "target": m.get("target"),
                    "cost": m.get("cost"),
                    "estimated_seconds": m.get("estimated_seconds"),
                }
                for m in mutations_combined
            ],
        },
    )

    return CritiqueOut(**out_payload)


# ── /improve ─────────────────────────────────────────────────────────────
# Apply the user's approved subset of mutations: re-fire Veo for any
# `frame.X.prompt`/`frame.X.motion` mutations (parallel + 1s stagger
# like the frontend's generateAllScenes), then re-render through
# Remotion, then snapshot the result as a new version.


class ImproveIn(BaseModel):
    storyboard_id: str = Field(..., min_length=1)
    approved_mutation_ids: list[str] = Field(..., min_length=1)
    # The full plan output of /critique. We need the mutation definitions
    # (target, from, to) — sending only the IDs would force a re-call.
    full_plan: dict


class ImproveOut(BaseModel):
    storyboard_id: str
    version_number: int
    video_url: str
    duration_ms: int
    refired_frame_ids: list[str] = []
    applied_mutation_ids: list[str] = []


# Mirrors the frontend's generateAllScenes 1s submit stagger so we don't
# self-DDoS Google's submit endpoint. Each scene then renders independently.
_SCENE_REFIRE_STAGGER_S = 1.0


# Same stagger story for transition bridges — see the comment above. The
# bridge endpoint shares the underlying Veo submit channel with scene-gen,
# so without spacing we'd hit the same 503 retry storm.
_BRIDGE_GEN_STAGGER_S = 1.0


async def _render_one_bridge(
    *,
    storyboard_id: str,
    pair_id: str,
    from_id: str,
    to_id: str,
    motion_hint: str,
    from_frame: dict,
    to_frame: dict,
    brand: dict,
    aspect: str,
) -> tuple[str, str | None, str | None]:
    """Generate a single Veo motion bridge between two frames.

    Returns (pair_id, clip_url_or_None, error_message_or_None).

    Strategy mirrors the /render bridge pipeline:
      1. Resolve the from-side image (last frame of clip OR keyframe).
      2. Resolve the to-side image (keyframe OR clip).
      3. Call render_transition_clip().
    Failures are returned, never raised — the caller downgrades the pair
    to ``match_cut`` so the render still produces something.
    """
    # Pick the from-side image. Prefer last frame of an existing clip
    # (better motion match than a keyframe); fall back to keyframe if
    # extraction fails or no clip exists.
    from_clip_url = from_frame.get("clip_url")
    from_image_url: str | None = None
    if from_clip_url:
        try:
            from_image_url = await extract_last_frame_to_storage(
                mp4_url=from_clip_url,
                storyboard_id=storyboard_id,
                frame_label=pair_id,
            )
        except Exception as e:
            log.warning(
                "improve.bridge: pair %s last-frame extract crashed (%s) — "
                "falling back to keyframe",
                pair_id, e,
            )
            from_image_url = None
    if from_image_url is None:
        from_image_url = from_frame.get("image_url") or from_clip_url
    if not from_image_url:
        return pair_id, None, "from-side image unavailable"

    # To-side: prefer the keyframe (Veo expects a still); fall back to clip.
    to_image_url = to_frame.get("image_url") or to_frame.get("clip_url")
    if not to_image_url:
        return pair_id, None, "to-side image unavailable"

    def _emit_retry(info: dict, _pair=pair_id) -> None:
        bus.emit(
            Events.VIDEO_SCENE_RETRYING,
            {
                "storyboard_id": storyboard_id,
                "pair_id": _pair,
                "phase": info["phase"],
                "attempt": info["attempt"],
                "max_attempts": info["max_attempts"],
                "delay_s": info["delay_s"],
                "reason": info["reason"],
            },
        )

    bus.emit(
        Events.VIDEO_TRANSITION_GENERATING,
        {
            "storyboard_id": storyboard_id,
            "pair_id": pair_id,
            "from_id": from_id,
            "to_id": to_id,
            "motion_hint": motion_hint,
        },
    )

    try:
        clip_url = await render_transition_clip(
            from_frame_url=from_image_url,
            to_frame_url=to_image_url,
            motion_hint=motion_hint,
            brand=brand or {},
            storyboard_id=storyboard_id,
            pair_id=pair_id,
            on_retry=_emit_retry,
            aspect=aspect,
        )
    except Exception as e:
        log.warning(
            "improve.bridge: pair %s render_transition_clip failed: %s",
            pair_id, e,
        )
        bus.emit(
            Events.VIDEO_TRANSITION_FAILED,
            {
                "storyboard_id": storyboard_id,
                "pair_id": pair_id,
                "error": str(e)[:400],
            },
        )
        return pair_id, None, str(e)[:240]

    bus.emit(
        Events.VIDEO_TRANSITION_GENERATED,
        {
            "storyboard_id": storyboard_id,
            "pair_id": pair_id,
            "from_id": from_id,
            "to_id": to_id,
            "clip_url": clip_url,
        },
    )
    return pair_id, clip_url, None


def _collect_pending_bridges(
    storyboard: dict,
    frames: list[dict],
) -> list[dict]:
    """Walk the post-mutation storyboard's transition_overrides for any
    pair flagged ``style="veo_bridge"`` AND missing a ``clip_url``.

    Each result entry shape:
      {
        "pair_id": "f0_f1",
        "from_id": "f0",
        "to_id": "f1",
        "from_frame": <frame dict>,
        "to_frame": <frame dict>,
        "motion_hint": <str | None>,
      }

    Pairs whose endpoints can't be located in `frames` are skipped (the
    LLM may have proposed a bridge for a pair the user later removed).
    """
    overrides = storyboard.get("transition_overrides") or {}
    if not isinstance(overrides, dict):
        return []

    by_id: dict[str, dict] = {
        f.get("id"): f
        for f in frames
        if isinstance(f, dict) and f.get("id")
    }

    pending: list[dict] = []
    for pair_id, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        style = (ov.get("style") or "").strip().lower()
        if style != "veo_bridge":
            continue
        # Skip pairs that already have a rendered clip_url. Only re-fire
        # when the upgrade introduced one.
        if ov.get("clip_url"):
            continue
        # Pair IDs are formatted "<from_id>_<to_id>". Split on the last
        # underscore so frame ids with embedded underscores still resolve.
        if "_" not in pair_id:
            continue
        # Find the canonical (from, to) by matching against frame ids in the
        # current frames list. We accept the first split that maps both
        # halves to known frames — this handles ids like "f_added_abc_f1".
        from_id, to_id = "", ""
        underscore_positions = [
            i for i, ch in enumerate(pair_id) if ch == "_"
        ]
        for pos in underscore_positions:
            left = pair_id[:pos]
            right = pair_id[pos + 1 :]
            if left in by_id and right in by_id:
                from_id, to_id = left, right
                break
        if not from_id or not to_id:
            log.info(
                "improve.bridge: pair %s endpoints not found in frames — skipping",
                pair_id,
            )
            continue
        pending.append(
            {
                "pair_id": pair_id,
                "from_id": from_id,
                "to_id": to_id,
                "from_frame": by_id[from_id],
                "to_frame": by_id[to_id],
                "motion_hint": ov.get("motion_hint")
                or ov.get("reason")
                or "",
            }
        )
    return pending


async def _generate_pending_bridges(
    storyboard_id: str,
    storyboard: dict,
    frames: list[dict],
    brand: dict,
    aspect: str,
) -> list[tuple[str, str | None, str | None]]:
    """Render every pending Veo bridge in parallel (with the same 1s
    submit stagger we use for scene refires).

    Mutates ``storyboard["transition_overrides"]`` in place: on success
    the pair's ``clip_url`` is set; on failure the pair's ``style`` is
    downgraded to ``match_cut`` so the renderer still has a path forward.

    Returns the raw (pair_id, clip_url, err) tuples for caller logging.
    """
    pending = _collect_pending_bridges(storyboard, frames)
    if not pending:
        return []

    log.info(
        "improve.bridge: generating %s Veo motion bridges in parallel",
        len(pending),
    )

    async def _staggered() -> list[tuple[str, str | None, str | None]]:
        tasks: list[asyncio.Task] = []
        for i, pb in enumerate(pending):
            tasks.append(
                asyncio.create_task(
                    _render_one_bridge(
                        storyboard_id=storyboard_id,
                        pair_id=pb["pair_id"],
                        from_id=pb["from_id"],
                        to_id=pb["to_id"],
                        motion_hint=pb["motion_hint"],
                        from_frame=pb["from_frame"],
                        to_frame=pb["to_frame"],
                        brand=brand,
                        aspect=aspect,
                    )
                )
            )
            if i < len(pending) - 1:
                await asyncio.sleep(_BRIDGE_GEN_STAGGER_S)
        return await asyncio.gather(*tasks)

    results = await _staggered()

    overrides = storyboard.get("transition_overrides") or {}
    for pair_id, clip_url, err in results:
        ov = dict(overrides.get(pair_id) or {})
        if clip_url and not err:
            ov["clip_url"] = clip_url
        else:
            # Downgrade the failed bridge to match_cut so render still works.
            ov["style"] = "match_cut"
            ov["clip_url"] = None
            ov["reason"] = (ov.get("reason") or "") + (
                f" [downgraded: bridge gen failed: {(err or 'unknown')[:120]}]"
            )
        overrides[pair_id] = ov
    storyboard["transition_overrides"] = overrides
    return results


async def _refire_one_scene(
    *,
    storyboard_id: str,
    frame: dict,
    aspect: str,
    brand: dict,
    quality: str,
) -> tuple[str, str | None, str | None]:
    """Re-fire Veo for one frame after a prompt/motion mutation. Returns
    (frame_id, new_clip_url_or_None, error_message_or_None)."""
    fid = frame.get("id")
    if not fid:
        return "", None, "frame missing id"

    cast_refs_raw = frame.get("cast_refs") or []
    refs = cast_registry.resolve(storyboard_id, cast_refs_raw)
    cinematic_brief = cast_registry.get_brief(storyboard_id)
    duration_ms = int(frame.get("duration_ms") or 2500)
    duration_s = max(4, min(8, round(duration_ms / 1000)))

    def _emit_retry(info: dict) -> None:
        bus.emit(
            Events.VIDEO_SCENE_RETRYING,
            {
                "storyboard_id": storyboard_id,
                "frame_id": fid,
                "phase": info["phase"],
                "attempt": info["attempt"],
                "max_attempts": info["max_attempts"],
                "delay_s": info["delay_s"],
                "reason": info["reason"],
            },
        )

    bus.emit(
        Events.VIDEO_SCENE_GENERATING,
        {
            "storyboard_id": storyboard_id,
            "frame_id": fid,
            "cast_refs": list(cast_refs_raw),
            "duration_ms": duration_ms,
            "quality": quality,
            "from_keyframe": bool(frame.get("image_url")),
        },
    )

    try:
        mp4_bytes = await generate_scene(
            brand=brand,
            scene_prompt=str(frame.get("prompt") or ""),
            aspect=aspect,
            duration_s=duration_s,
            cast_refs=refs,
            motion=str(frame.get("motion") or ""),
            quality="fast",  # improvement re-fires are always fast tier
            keyframe_url=frame.get("image_url"),
            cinematic_brief=cinematic_brief,
            on_retry=_emit_retry,
        )
    except Exception as e:
        log.warning(
            "improve: scene re-fire failed for frame=%s: %s", fid, e
        )
        return fid, None, str(e)[:240]

    if not mp4_bytes:
        return fid, None, "Veo returned no clip"

    # Use a versioned key so the new clip doesn't clobber the v1 mp4 in
    # storage (the prior version snapshot still references it).
    import time as _t
    suffix = int(_t.time())
    key = f"videos/{storyboard_id}/scenes/{fid}_{suffix}.mp4"
    try:
        storage = get_storage()
        await storage.put(key, mp4_bytes, "video/mp4")
        url = await storage.get_url(key)
    except Exception as e:
        log.exception("improve: scene store failed for frame=%s: %s", fid, e)
        return fid, None, f"store failed: {str(e)[:200]}"

    bus.emit(
        Events.VIDEO_SCENE_GENERATED,
        {
            "storyboard_id": storyboard_id,
            "frame_id": fid,
            "clip_url": url,
            "aspect": aspect,
            "cast_refs": list(cast_refs_raw),
            "duration_ms": duration_ms,
            "quality": "fast",
            "from_keyframe": bool(frame.get("image_url")),
        },
    )
    return fid, url, None


@router.post("/improve", response_model=ImproveOut)
async def post_improve(body: ImproveIn) -> ImproveOut:
    """Apply approved mutations and produce a new version.

    Pipeline:
      1. Apply mutations to a fresh storyboard snapshot (in-memory).
      2. Re-fire Veo in parallel (1s stagger) for any mutations that
         changed `frame.X.prompt` or `frame.X.motion`.
      3. Persist the updated frames on the storyboard row.
      4. Re-render through Remotion.
      5. Append a new version snapshot (v2, v3, ...).
    """
    import asyncio as _asyncio

    sb_full = cast_registry.get_full_storyboard(body.storyboard_id)
    if sb_full is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown storyboard {body.storyboard_id}",
        )

    bus.emit(
        Events.VIDEO_IMPROVING_STARTED,
        {
            "storyboard_id": body.storyboard_id,
            "mutation_count": len(body.approved_mutation_ids),
        },
    )

    # Step 1 — apply mutations.
    try:
        new_sb, refire_ids = await apply_mutations(
            storyboard_id=body.storyboard_id,
            base_storyboard=sb_full,
            approved_mutation_ids=body.approved_mutation_ids,
            full_plan=body.full_plan,
        )
    except Exception as e:
        log.exception("video.improve apply failed: %s", e)
        bus.emit(
            Events.VIDEO_IMPROVEMENT_FAILED,
            {
                "storyboard_id": body.storyboard_id,
                "phase": "apply",
                "error": str(e)[:240],
            },
        )
        raise HTTPException(
            status_code=502, detail=f"apply mutations failed: {e}"
        ) from e

    new_frames: list[dict] = list(new_sb.get("frames") or [])
    aspect = sb_full.get("aspect") or "9:16"
    title_card = sb_full.get("title_card")
    end_card = sb_full.get("end_card")

    # Step 2 — re-fire Veo for any frames whose prompt/motion changed.
    if refire_ids:
        brand = _load_brand_for_frame() or {}
        # Build the per-frame target list (post-mutation snapshot) so the
        # new prompt/motion is what Veo sees.
        targets: list[dict] = [
            f for f in new_frames if isinstance(f, dict) and f.get("id") in refire_ids
        ]

        async def _staggered() -> list[tuple[str, str | None, str | None]]:
            tasks: list[_asyncio.Task] = []
            for i, frame in enumerate(targets):
                tasks.append(
                    _asyncio.create_task(
                        _refire_one_scene(
                            storyboard_id=body.storyboard_id,
                            frame=frame,
                            aspect=aspect,
                            brand=brand,
                            quality="fast",
                        )
                    )
                )
                if i < len(targets) - 1:
                    await _asyncio.sleep(_SCENE_REFIRE_STAGGER_S)
            return await _asyncio.gather(*tasks)

        results = await _staggered()
        # Apply new clip URLs onto the new_frames list. Failures keep the
        # prior clip_url so the render still has SOMETHING to composite.
        url_by_fid: dict[str, str] = {
            fid: url for fid, url, _err in results if url
        }
        errors = [(fid, err) for fid, _url, err in results if err]
        if url_by_fid:
            for i, f in enumerate(new_frames):
                if isinstance(f, dict) and f.get("id") in url_by_fid:
                    new_frames[i] = {**f, "clip_url": url_by_fid[f["id"]]}
            new_sb["frames"] = new_frames
        if errors:
            log.warning(
                "video.improve: %s/%s refires failed — proceeding with prior clips: %s",
                len(errors),
                len(targets),
                errors,
            )

    # Step 3a — generate Veo motion bridges for any transition that was
    # upgraded to "veo_bridge" by an approved mutation. We do this BEFORE
    # persisting frames so a bridge failure can downgrade the override
    # back to match_cut on the in-memory storyboard. Bridges run in
    # parallel with a 1s submit stagger (same pattern as scene refires).
    brand_for_bridges = _load_brand_for_frame() or {}
    try:
        bridge_results = await _generate_pending_bridges(
            storyboard_id=body.storyboard_id,
            storyboard=new_sb,
            frames=new_frames,
            brand=brand_for_bridges,
            aspect=aspect,
        )
    except Exception as e:
        # Defensive: per-bridge failures are caught inside the helper, so
        # this only fires on a truly unexpected error in the orchestration
        # itself. Log and continue — we'd rather render without bridges
        # than fail the whole improve cycle.
        log.warning("video.improve: bridge orchestration crashed: %s", e)
        bridge_results = []
    bridge_failures = [r for r in bridge_results if r[2]]
    if bridge_failures:
        log.warning(
            "video.improve: %s/%s bridges failed — downgraded to match_cut: %s",
            len(bridge_failures),
            len(bridge_results),
            [(p, e) for p, _u, e in bridge_failures],
        )

    # Step 3 — persist the updated frames so the version snapshot we take
    # next is consistent with what the editor sees.
    try:
        cast_registry.replace_frames(body.storyboard_id, new_frames)
    except Exception as e:
        log.warning("video.improve: replace_frames failed: %s", e)

    # Step 4 — re-render through Remotion.
    bus.emit(
        Events.VIDEO_VERSION_RENDERING,
        {
            "storyboard_id": body.storyboard_id,
            "frame_count": len(new_frames),
        },
    )

    brand_for_render = _load_brand_for_render()
    frames_payload: list[dict] = []
    for f in new_frames:
        if not isinstance(f, dict):
            continue
        frames_payload.append(
            {
                "kind": f.get("kind") or "live_action",
                "clip_url": f.get("clip_url"),
                "image_url": f.get("image_url"),
                "caption": str(f.get("caption") or ""),
                "duration_ms": int(f.get("duration_ms") or 2400),
                "focal_zone": f.get("focal_zone") or "mc",
                "effects": f.get("effects") or [],
                "template": f.get("template"),
                "template_params": f.get("template_params"),
            }
        )
    title_payload = (
        {"text": title_card.get("text")} if isinstance(title_card, dict) and title_card.get("text") else None
    )
    end_payload = (
        {
            "headline": (end_card or {}).get("headline", ""),
            "cta": (end_card or {}).get("cta", ""),
        }
        if isinstance(end_card, dict)
        else None
    )

    # Build the transitions list from the storyboard's transition_overrides.
    # Any pair the user/critic touched (bridge upgrade OR style flip) lands
    # here; pairs we don't know about default to match_cut at render time.
    transitions_payload: list[dict] = []
    overrides = new_sb.get("transition_overrides") or {}
    for pair_id, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        if "_" not in pair_id:
            continue
        # Robust split — first underscore wins for canonical "<from>_<to>".
        from_id, _, to_id = pair_id.partition("_")
        transitions_payload.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "style": ov.get("style") or "match_cut",
                "reason": ov.get("reason") or "",
                "motion_hint": ov.get("motion_hint"),
                "clip_url": ov.get("clip_url"),
            }
        )

    props = build_props(
        aspect,
        frames_payload,
        brand_for_render,
        title_card=title_payload,
        end_card=end_payload,
        # Carry over any bridge clips + style overrides the user approved.
        # We still skip the AI planner here (predictable latency); the
        # planner only fires on a fresh /render call.
        transitions=transitions_payload,
    )

    new_video_id = str(uuid4())
    try:
        mp4_bytes, total_duration_ms = await render_video(props)
    except RemotionNotInstalledError as e:
        bus.emit(
            Events.VIDEO_IMPROVEMENT_FAILED,
            {
                "storyboard_id": body.storyboard_id,
                "phase": "render",
                "error": e.reason,
            },
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "remotion not installed", "stderr": (e.stderr or e.reason)[-1200:]},
        ) from e
    except Exception as e:
        log.exception("video.improve render failed: %s", e)
        bus.emit(
            Events.VIDEO_IMPROVEMENT_FAILED,
            {
                "storyboard_id": body.storyboard_id,
                "phase": "render",
                "error": str(e)[:240],
            },
        )
        raise HTTPException(status_code=502, detail=f"render failed: {e}") from e

    key = f"videos/{new_video_id}/output.mp4"
    try:
        storage = get_storage()
        await storage.put(key, mp4_bytes, "video/mp4")
        new_video_url = await storage.get_url(key)
    except Exception as e:
        log.exception("video.improve store failed: %s", e)
        bus.emit(
            Events.VIDEO_IMPROVEMENT_FAILED,
            {
                "storyboard_id": body.storyboard_id,
                "phase": "store",
                "error": str(e)[:240],
            },
        )
        raise HTTPException(status_code=502, detail=f"store failed: {e}") from e

    # Update the storyboard row's "current" pointer too — the v(n+1) is
    # now the live render the rest of the UI shows by default.
    cast_registry.set_render(
        body.storyboard_id,
        video_id=new_video_id,
        video_url=new_video_url,
        duration_ms=total_duration_ms,
    )

    # Step 5 — append the new version snapshot.
    version_number = record_version(
        body.storyboard_id,
        frames=new_frames,
        video_url=new_video_url,
        critique=body.full_plan,
        applied_mutations=body.approved_mutation_ids,
        aspect=aspect,
        title_card=title_card if isinstance(title_card, dict) else None,
        end_card=end_card if isinstance(end_card, dict) else None,
    )

    bus.emit(
        Events.VIDEO_VERSION_RENDERED,
        {
            "storyboard_id": body.storyboard_id,
            "version_number": version_number,
            "video_url": new_video_url,
            "duration_ms": total_duration_ms,
            "refired_frame_ids": refire_ids,
            "applied_mutation_ids": body.approved_mutation_ids,
        },
    )

    return ImproveOut(
        storyboard_id=body.storyboard_id,
        version_number=version_number,
        video_url=new_video_url,
        duration_ms=total_duration_ms,
        refired_frame_ids=refire_ids,
        applied_mutation_ids=body.approved_mutation_ids,
    )


# ── /version/{n} ─────────────────────────────────────────────────────────
# Load any historical version's full snapshot for inspection in the editor.


class VersionOut(BaseModel):
    storyboard_id: str
    version_number: int
    video_url: str | None = None
    frames: list[dict] = []
    aspect: Aspect | None = None
    title_card: dict | None = None
    end_card: dict | None = None
    critique: dict | None = None
    applied_mutations: list[str] = []
    created_at: str | None = None


@router.get(
    "/storyboard/{storyboard_id}/version/{version_number}",
    response_model=VersionOut,
)
async def get_storyboard_version(
    storyboard_id: str, version_number: int
) -> VersionOut:
    v = get_version(storyboard_id, version_number)
    if v is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"version {version_number} not found for "
                f"storyboard {storyboard_id}"
            ),
        )
    return VersionOut(
        storyboard_id=storyboard_id,
        version_number=int(v.get("version_number") or version_number),
        video_url=v.get("video_url"),
        frames=list(v.get("frames") or []),
        aspect=v.get("aspect"),
        title_card=v.get("title_card") if isinstance(v.get("title_card"), dict) else None,
        end_card=v.get("end_card") if isinstance(v.get("end_card"), dict) else None,
        critique=v.get("critique") if isinstance(v.get("critique"), dict) else None,
        applied_mutations=list(v.get("applied_mutations") or []),
        created_at=v.get("created_at"),
    )


@router.get("/storyboard/{storyboard_id}/versions")
async def get_storyboard_versions(storyboard_id: str) -> list[dict]:
    """Lightweight version index — does not echo full frame snapshots.
    The frontend uses this to render a version-picker chip strip; it
    fetches the full snapshot for one version on demand."""
    return list_versions(storyboard_id)
