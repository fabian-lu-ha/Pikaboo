"""Single-keyframe generator for the marketing-video surface.

Reuses the multi-image input pattern from `app.services.agent.image_gen` so
keyframes inherit brand-photographer fidelity (the brand's uploaded assets
are passed as visual references). Differs from agent.image_gen in two ways:

  - There's no channel context — only an aspect ratio (1:1, 16:9, 9:16).
  - The anti-prompt is HARDENED to forbid baked-in text. Captions are
    overlaid by Remotion at composite time; baked-in text would double up.

We do NOT modify or import from `app.services.agent.image_gen` — we inline
the small set of helpers we need so the agent module stays untouched.
"""

from __future__ import annotations

import logging
from base64 import b64decode
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.services.brand_book import format_for_prompt as _format_pic_for_prompt
from app.services.brand_book import load_pic
from app.services.video_gen.cast import CastRef


def _pic_block(brand: dict) -> str:
    """Resolve the brand's PIC.md and render it as a prompt prefix block.

    Returns an empty string when no PIC has been generated yet — every
    image-gen path stays functional even before the picture book exists.
    """
    bid = str((brand or {}).get("id") or "").strip()
    if not bid:
        return ""
    return _format_pic_for_prompt(load_pic(bid))

log = logging.getLogger(__name__)

_client: genai.Client | None = None

VALID_ASPECTS: tuple[str, ...] = ("1:1", "16:9", "9:16")

# Hardened anti-prompt — caller specified the exact wording. It must be the
# last beat of the prompt so it dominates if the model wavers.
_NO_TEXT_ANTI_PROMPT = (
    "ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO CAPTIONS, NO SUBTITLES, "
    "NO TYPOGRAPHY, NO WATERMARKS, NO LOGOS RENDERED INTO THE IMAGE. The "
    "frame must be pure visual — text is overlaid by a separate compositing layer."
)

# Universal slop-suppression mirrored from agent.image_gen so keyframes don't
# regress to AI-stock-photo aesthetics.
_UNIVERSAL_ANTI_PROMPT = (
    "Critical: this is a keyframe in a marketing video, not a website "
    "screenshot. Do NOT include UI elements (buttons, navigation bars, "
    "dropdowns, search bars, form inputs, sliders, modal dialogs, scroll "
    "indicators, browser chrome). Do NOT use rainbow gradients, shiny chrome "
    "3D, generic AI-stock-photo aesthetics, stock corporate handshakes, "
    "fake-creator AI faces. The frame should look like an in-house brand "
    "photographer/designer captured it for a flagship campaign."
)

# For ingredient sheets only — keeps reference sheets neutral so they lock
# identity without bleeding compositional/lighting baggage into the frames
# that condition on them.
_NEUTRAL_SHEET_ANTI_PROMPT = (
    "Reference-sheet style only. No environmental drama, no extreme camera "
    "angles, no scene narrative, no other subjects in frame, no atmospheric "
    "haze, no motion blur. The sheet's purpose is to lock visual identity "
    "for downstream compositing — keep it neutral, isolated, and clean."
)


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _build_prompt(brand: dict, prompt: str, aspect: str) -> str:
    name = brand.get("name") or "the brand"
    palette = (brand.get("palette") or [])[:4]
    palette_str = ", ".join(palette) if palette else ""

    style = brand.get("style_profile") or {}
    mood = style.get("mood") or ""
    composition = style.get("composition") or ""
    photo_vs_illust = style.get("photographic_vs_illustrated") or ""
    distinctive_marks = style.get("distinctive_marks") or []

    aspect_label = {
        "16:9": "landscape",
        "9:16": "vertical",
        "1:1": "square",
    }.get(aspect, "landscape")

    parts: list[str] = []
    pic = _pic_block(brand)
    if pic:
        parts.append(pic)
    parts.extend(
        [
            f"Generate a {aspect_label} marketing-video keyframe for {name}.",
            f"Subject: {prompt[:1800]}",
        ]
    )
    if palette_str:
        parts.append(
            f"Use the brand palette as the primary colors (in this order of "
            f"weight): {palette_str}."
        )
    if mood:
        parts.append(f"Mood: {mood}")
    if photo_vs_illust:
        parts.append(f"Treatment: {photo_vs_illust}")
    if composition:
        parts.append(f"Composition: {composition}")
    if distinctive_marks:
        parts.append(
            f"Visual signatures to keep: {'; '.join(distinctive_marks[:3])}."
        )

    # Reference brands: borrow palette accents only (mirrors agent.image_gen).
    refs = brand.get("reference_brands") or []
    ref_palette_hex: list[str] = []
    ref_names: list[str] = []
    for r in refs[:2]:
        rname = (r.get("name") or "").strip()
        if rname:
            ref_names.append(rname)
        for hx in (r.get("palette") or [])[:3]:
            if isinstance(hx, str) and hx not in ref_palette_hex and hx not in palette:
                ref_palette_hex.append(hx)
    if ref_names:
        parts.append(
            f"Reference brands for visual energy (do not copy logos / names): "
            f"{', '.join(ref_names)}."
        )
    if ref_palette_hex:
        parts.append(
            f"Acceptable accent colors borrowed from references "
            f"(use sparingly): {', '.join(ref_palette_hex[:4])}."
        )

    parts.append(_UNIVERSAL_ANTI_PROMPT)
    parts.append(_NO_TEXT_ANTI_PROMPT)
    return " ".join(parts)


def _load_asset_bytes(asset_url: str | None) -> tuple[bytes, str] | None:
    """Resolve a stored asset URL to raw bytes for multi-image input.

    Mirrors `agent.image_gen._load_asset_bytes` — only local-mode storage and
    data: URIs are supported here. Supabase asset refs would need a fetch.
    """
    if not asset_url:
        return None
    if asset_url.startswith("data:"):
        try:
            head, b64 = asset_url.split(",", 1)
            mime = head.split(";")[0].removeprefix("data:") or "image/png"
            return b64decode(b64), mime
        except Exception:
            return None
    if settings.deploy_mode != "local":
        return None
    if not asset_url.startswith("/api/storage/"):
        return None
    rel = asset_url.removeprefix("/api/storage/")
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


def _asset_parts(brand: dict, max_refs: int = 2) -> list[Any]:
    """Up to N brand assets as reference image parts."""
    assets: list[str] = list(brand.get("assets") or [])
    out: list[Any] = []
    for url in assets[:max_refs]:
        loaded = _load_asset_bytes(url)
        if loaded is None:
            continue
        data, mime = loaded
        if len(data) > 5 * 1024 * 1024:
            continue
        out.append(types.Part.from_bytes(data=data, mime_type=mime))
    return out


def _extract_image_bytes(response: Any) -> bytes | None:
    """Pull the first inline image from a Gemini response, or None."""
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            data = getattr(inline, "data", None)
            mime = getattr(inline, "mime_type", "") or ""
            if data and mime.startswith("image/"):
                return data
    return None


# ── Ingredient sheets ────────────────────────────────────────────────────
# Each cast member resolves to a single canonical "ingredient" image. For
# brand_asset bindings the canonical is the uploaded asset URL (no gen).
# For needs_generation bindings, we generate a neutral reference sheet
# here that locks identity without compositional baggage.

# 1:1 sheets for character/prop/product so they crop cleanly into any aspect;
# 16:9 for settings so the establishing shot has room.
_INGREDIENT_ASPECT: dict[str, str] = {
    "character": "1:1",
    "setting": "16:9",
    "prop": "1:1",
    "product": "1:1",
}


def _build_ingredient_prompt(brand: dict, cast_member: dict) -> str:
    """Prompt for a single canonical ingredient sheet.

    Three shapes by kind:
      - character: neutral character reference sheet (3/4 view, soft lighting,
        plain background, full outfit visible).
      - setting: establishing-shot interior reference (no people, no signage).
      - prop / product: isolated product reference (centered, neutral bg,
        no text on packaging).

    All three append the universal slop-suppression and the hardened
    no-text anti-prompts so even ingredient sheets are pure visual.
    """
    name = brand.get("name") or "the brand"
    palette = (brand.get("palette") or [])[:3]
    palette_str = ", ".join(palette) if palette else ""
    style = brand.get("style_profile") or {}
    photo_vs_illust = style.get("photographic_vs_illustrated") or ""

    kind = (cast_member.get("kind") or "character").lower()
    description = (cast_member.get("description") or "").strip()
    pose_hint = (cast_member.get("neutral_pose_hint") or "").strip()

    parts: list[str] = []
    # Ingredient sheets must inherit the brand picture book even though
    # they're neutral references — the *identity* the sheet locks needs to
    # match the rest of the visual language. The neutral-sheet anti-prompt
    # below still strips environmental drama after the PIC has set tone.
    pic = _pic_block(brand)
    if pic:
        parts.append(pic)

    if kind == "character":
        parts.extend(
            [
                f"Generate a neutral character reference sheet for a {name} "
                f"marketing video.",
                "Three-quarter view, eye-level, soft even ambient light, "
                "plain medium-gray background, full upper body and outfit "
                "visible, neutral relaxed expression, isolated subject, "
                "studio reference photography style.",
            ]
        )
        if description:
            parts.append(f"Subject: {description[:1000]}")
        if pose_hint:
            parts.append(f"Pose guidance: {pose_hint[:400]}")
    elif kind == "setting":
        parts.extend(
            [
                f"Generate an establishing-shot interior reference for a "
                f"{name} marketing video.",
                "Eye-level wide-angle, ambient soft light, no people in "
                "frame, no signage of any kind, no menu boards, no "
                "chalkboards, no labeled equipment. Isolated environment "
                "for downstream compositing.",
            ]
        )
        if description:
            parts.append(f"Location: {description[:1000]}")
    else:
        # prop / product — synthesized only (brand-bound products bypass this)
        parts.extend(
            [
                f"Generate an isolated product reference for a {name} "
                f"marketing video.",
                "Centered subject, plain neutral background, soft three-"
                "point lighting, no text on packaging, no labels, full "
                "silhouette visible, no hands, no environmental context.",
            ]
        )
        if description:
            parts.append(f"Subject: {description[:1000]}")

    if palette_str:
        parts.append(
            f"Tonal palette consistent with the brand "
            f"(use sparingly): {palette_str}."
        )
    if photo_vs_illust:
        parts.append(f"Treatment: {photo_vs_illust}")

    parts.append(_UNIVERSAL_ANTI_PROMPT)
    parts.append(_NEUTRAL_SHEET_ANTI_PROMPT)
    parts.append(_NO_TEXT_ANTI_PROMPT)
    return " ".join(parts)


async def generate_ingredient(
    brand: dict, cast_member: dict
) -> bytes | None:
    """Generate a single canonical ingredient sheet. Returns image bytes or None.

    Kind controls aspect (1:1 for character/prop/product, 16:9 for setting)
    and prompt shape. Brand assets are passed as a *single* mood ref — we
    don't want brand assets dominating ingredient identity.
    """
    client = _get_client()
    if client is None:
        log.warning("ingredient gen: no GEMINI_API_KEY")
        return None

    kind = (cast_member.get("kind") or "character").lower()
    aspect = _INGREDIENT_ASPECT.get(kind, "1:1")

    full_prompt = _build_ingredient_prompt(brand, cast_member)
    asset_refs = _asset_parts(brand, max_refs=1)  # single mood ref only

    contents: list[Any] = [full_prompt, *asset_refs]

    config_kwargs: dict[str, Any] = {
        "response_modalities": ["IMAGE", "TEXT"],
    }
    try:
        config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=aspect)
    except (AttributeError, TypeError):
        config_kwargs["image_config"] = {"aspect_ratio": aspect}

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        log.warning("ingredient gen: API call failed: %s", e)
        return None

    image = _extract_image_bytes(response)
    if image is None:
        log.warning("ingredient gen: no image part in response")
    return image


def _build_frame_prompt_with_refs(
    brand: dict,
    prompt: str,
    aspect: str,
    cast_refs: list[CastRef],
) -> str:
    """Like _build_prompt, but inserts a labeled-references block before the
    anti-prompts. The block names each reference and what it locks so the
    image model treats them as identity locks rather than poses to copy."""
    base = _build_prompt(brand, prompt, aspect)

    if not cast_refs:
        return base

    # _build_prompt always ends with universal + no_text anti-prompts; pull
    # them off so we can inject the refs block ahead of them and re-attach.
    sentinel = " " + _UNIVERSAL_ANTI_PROMPT
    head, _, _tail = base.partition(sentinel)
    head = head.rstrip()

    ref_lines: list[str] = [
        "Reference images attached are CANONICAL identity locks for this "
        "scene. They lock identity ONLY — pose, expression, camera angle, "
        "and lighting come from the scene description above.",
    ]
    for idx, ref in enumerate(cast_refs):
        n = idx + 1
        kind = (ref.get("kind") or "character") if isinstance(ref, dict) else "character"
        rid = ref.get("id") if isinstance(ref, dict) else f"ref{n}"
        desc = (ref.get("description") or "").strip() if isinstance(ref, dict) else ""
        if kind == "character":
            ref_lines.append(
                f"- Reference {n} [CHAR:{rid}]: this is the canonical "
                f"appearance of {desc or 'the character'}. Maintain face, "
                f"hair color and style, body type, and wardrobe IDENTICALLY. "
                f"Use the new pose, expression, and angle described in the "
                f"scene above."
            )
        elif kind == "setting":
            ref_lines.append(
                f"- Reference {n} [SETTING:{rid}]: this is the canonical "
                f"location ({desc or 'the setting'}). Match the interior "
                f"style, key furniture, and overall lighting palette. Do "
                f"not invent new architectural elements."
            )
        else:
            ref_lines.append(
                f"- Reference {n} [{kind.upper()}:{rid}]: this is the "
                f"canonical {desc or kind}. Maintain shape, color, and "
                f"material; place per the scene description above."
            )
    ref_lines.append(
        "Brand assets that follow (if any) are mood/aesthetic baselines "
        "only — borrow palette and energy, do not copy their compositions."
    )

    return (
        f"{head} {' '.join(ref_lines)} "
        f"{_UNIVERSAL_ANTI_PROMPT} {_NO_TEXT_ANTI_PROMPT}"
    )


async def generate_video_frame(
    brand: dict,
    prompt: str,
    aspect: str,
    cast_refs: list[CastRef] | None = None,
) -> bytes | None:
    """Generate one keyframe. Returns raw image bytes or None on failure.

    When cast_refs is non-empty, the cast canonicals are passed as multi-
    image input ALONGSIDE brand assets, with the prompt explicitly naming
    each canonical as an identity lock for a specific entity. Cast refs
    come first in the contents list (Gemini weighs earlier refs higher);
    brand assets follow as mood baseline, capped so the total stays ≤ 5
    image inputs to avoid conditioning dilution.

    Caller is responsible for storing + URL'ing the result.
    """
    if aspect not in VALID_ASPECTS:
        raise ValueError(f"aspect must be one of {VALID_ASPECTS}, got {aspect!r}")

    client = _get_client()
    if client is None:
        log.warning("video frame gen: no GEMINI_API_KEY")
        return None

    refs: list[CastRef] = list(cast_refs or [])
    if refs:
        full_prompt = _build_frame_prompt_with_refs(brand, prompt, aspect, refs)
    else:
        full_prompt = _build_prompt(brand, prompt, aspect)

    contents: list[Any] = [full_prompt]

    # Cast canonicals first — these are the identity locks.
    cast_image_parts: list[Any] = []
    for ref in refs:
        url = ref.get("canonical_url") if isinstance(ref, dict) else None
        if not url:
            continue
        loaded = _load_asset_bytes(url)
        if loaded is None:
            continue
        data, mime = loaded
        if len(data) > 5 * 1024 * 1024:
            continue
        cast_image_parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    contents.extend(cast_image_parts)

    # Brand asset cap: leave room for cast refs — total ≤ 5 image parts.
    remaining = max(0, 5 - len(cast_image_parts))
    if remaining:
        brand_parts = _asset_parts(brand, max_refs=min(2, remaining))
        contents.extend(brand_parts)

    config_kwargs: dict[str, Any] = {
        "response_modalities": ["IMAGE", "TEXT"],
    }
    # image_config.aspect_ratio is the canonical knob; text alone is unreliable.
    try:
        config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=aspect)
    except (AttributeError, TypeError):
        config_kwargs["image_config"] = {"aspect_ratio": aspect}

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        log.warning("video frame gen: API call failed: %s", e)
        return None

    image = _extract_image_bytes(response)
    if image is None:
        log.warning("video frame gen: no image part in response")
    return image
