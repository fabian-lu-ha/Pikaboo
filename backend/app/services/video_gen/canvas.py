"""Stylized canvas generator for the canvas_kinetic design template.

A canvas is a single nano-banana-pro illustration that serves as the
backdrop for kinetic typography overlaid by Remotion. It's the third
creative pathway alongside Veo's live-action shots and the pure-CSS
design templates: when neither a real-world cinema clip nor a flat
graphic feels right, a canvas gives us a hero abstract beat (concept
art, exploded-view product, cosmic abstraction) that the typography
layer can then punch through.

The image is INTENTIONALLY non-photoreal — abstract / illustrated /
concept-art / stylized — so it pairs with the typography layer rather
than competing with it. We instruct nano-banana to produce a clean
composition with negative space for text overlays.

Canvas generation runs at /render time only (NOT at /suggest), so the
storyboard suggest path stays fast — only frames that actually need a
canvas pay the 5-15s nano-banana hop.
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.providers.factory import get_storage
from app.services.brand_book import format_for_prompt as _format_pic_for_prompt
from app.services.brand_book import load_pic
from app.services.video_gen.frame_gen import _extract_image_bytes

log = logging.getLogger(__name__)


_VALID_ASPECTS: tuple[str, ...] = ("16:9", "9:16", "1:1")


def _aspect_resolution(aspect: str) -> str:
    """Human-readable resolution hint we paste into the prompt.

    nano-banana-pro doesn't always honour the ImageConfig aspect knob
    cleanly when text-direction conflicts; restating the resolution in the
    prompt body gives us a second nudge.
    """
    return {
        "16:9": "1920x1080",
        "9:16": "1080x1920",
        "1:1": "1080x1080",
    }.get(aspect, "1920x1080")


def _aspect_label(aspect: str) -> str:
    return {
        "16:9": "landscape",
        "9:16": "vertical",
        "1:1": "square",
    }.get(aspect, "landscape")


_client: genai.Client | None = None


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


# Canvas-specific anti-prompts. Slightly different from frame_gen — we want
# a stylized illustration (not a keyframe), so the universal slop block
# would over-correct. We still hard-block baked-in text since the typography
# is overlaid by Remotion.
_NO_TEXT_ANTI_PROMPT = (
    "ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO CAPTIONS, NO SUBTITLES, "
    "NO TYPOGRAPHY, NO WATERMARKS, NO LOGOS RENDERED INTO THE IMAGE. The "
    "frame must be pure illustration — text is added by a separate "
    "compositing layer on top."
)

_CANVAS_ANTI_PROMPT = (
    "Critical: this is a stylized illustrated backdrop for a kinetic-"
    "typography overlay, not a photograph. Avoid stock-photo aesthetics, "
    "shutterstock-grade composition, and AI-generic 3D renders. No UI "
    "elements, no browser chrome, no app screenshots. The composition must "
    "leave generous negative space (~40% of the frame) so the typography "
    "layer reads cleanly on top — do not fill every pixel; design the "
    "negative space intentionally."
)


def _build_canvas_prompt(brand: dict, canvas_prompt: str, aspect: str) -> str:
    """Compose the full nano-banana prompt for a stylized canvas.

    The canvas inherits brand palette + style mood so it fits the
    cinematic_brief grade, but is rendered in an illustrated/concept-art
    treatment regardless of the brand's photo_vs_illustrated default
    (the canvas is explicitly the illustrated pathway).
    """
    name = (brand or {}).get("name") or "the brand"
    palette = ((brand or {}).get("palette") or [])[:3]
    palette_str = ", ".join(palette) if palette else ""

    style = (brand or {}).get("style_profile") or {}
    mood = style.get("mood") or ""
    distinctive_marks = style.get("distinctive_marks") or []

    parts: list[str] = []

    # Inject the brand picture book at the top so the canvas inherits the
    # evergreen identity. The book sets palette/mood/voice; the canvas
    # prompt below describes the specific scene.
    bid = str((brand or {}).get("id") or "").strip()
    if bid:
        pic = _format_pic_for_prompt(load_pic(bid))
        if pic:
            parts.append(pic)

    parts.append(
        f"Generate a {_aspect_label(aspect)} stylized illustrated backdrop "
        f"for a {name} marketing video — a kinetic-typography canvas."
    )
    parts.append(f"Subject: {(canvas_prompt or '').strip()[:1600]}")

    parts.append(
        "Treatment: stylized illustration / concept art aesthetic — NOT "
        "photorealistic. Think editorial illustration, designed concept "
        "frame, motion-graphics keyframe. Abstract, intentional composition "
        "with generous negative space for text overlays. Designed, not "
        "captured."
    )

    if palette_str:
        parts.append(
            f"Use the brand palette as the dominant colors (in this weight "
            f"order): {palette_str}."
        )
    if mood:
        parts.append(f"Mood: {mood}.")
    if distinctive_marks:
        parts.append(
            f"Visual signatures the brand is known for "
            f"(borrow sparingly): {'; '.join(distinctive_marks[:3])}."
        )

    parts.append(
        f"Aspect: {aspect}. Target resolution: {_aspect_resolution(aspect)}."
    )

    parts.append(_CANVAS_ANTI_PROMPT)
    parts.append(_NO_TEXT_ANTI_PROMPT)
    return " ".join(parts)


async def generate_canvas(
    brand: dict,
    canvas_prompt: str,
    aspect: str,
    storyboard_id: str,
    frame_id: str,
) -> str | None:
    """Generate a stylized illustrated canvas and store it.

    Args:
        brand: brand snapshot (palette, style_profile, id) for prompt
            augmentation. May be a partial dict — all reads are defensive.
        canvas_prompt: 1-2 sentence description of the intended backdrop,
            authored by the LLM at /suggest time.
        aspect: one of '16:9' | '9:16' | '1:1'. Drives both the
            ImageConfig knob and the resolution hint baked into the prompt.
        storyboard_id: storyboard scope used in the storage key.
        frame_id: frame-level id used in the storage key.

    Returns:
        The /api/storage/... URL of the stored PNG, or None on failure
        (no API key, model error, no image part, storage error). Callers
        treat None as "fall back to brand gradient" — the renderer wires
        canvas_url=None through to the Remotion side which renders a
        gradient placeholder.
    """
    if aspect not in _VALID_ASPECTS:
        log.warning("canvas gen: unsupported aspect %r — defaulting to 16:9", aspect)
        aspect = "16:9"

    if not (canvas_prompt or "").strip():
        log.warning("canvas gen: empty canvas_prompt — skipping")
        return None

    client = _get_client()
    if client is None:
        log.warning("canvas gen: no GEMINI_API_KEY")
        return None

    full_prompt = _build_canvas_prompt(brand or {}, canvas_prompt, aspect)

    config_kwargs: dict[str, Any] = {
        "response_modalities": ["IMAGE", "TEXT"],
    }
    try:
        config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=aspect)
    except (AttributeError, TypeError):
        # Older google-genai shapes accept a plain dict — fall back rather
        # than crashing, since the prompt itself also restates the aspect.
        config_kwargs["image_config"] = {"aspect_ratio": aspect}

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=[full_prompt],
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        log.warning("canvas gen: API call failed: %s", e)
        return None

    image_bytes = _extract_image_bytes(response)
    if image_bytes is None:
        log.warning("canvas gen: no image part in response")
        return None

    key = f"videos/{storyboard_id}/canvases/{frame_id}.png"
    try:
        storage = get_storage()
        await storage.put(key, image_bytes, "image/png")
        url = await storage.get_url(key)
    except Exception as e:
        log.warning("canvas gen: storage put failed: %s", e)
        return None

    log.info(
        "canvas gen: stored %s/%s (%d bytes) at %s",
        storyboard_id, frame_id, len(image_bytes), url,
    )
    return url
