"""Inpaint + sketch-to-image via Gemini nano-banana-pro multi-image input.

Gemini does NOT expose a native mask/inpaint endpoint. The trick that works
empirically is:

  1. Take the source image.
  2. Composite a vivid magenta overlay (60% opacity) over the masked region
     onto a copy of the source.
  3. Send (source, highlighted_copy) to the model with a prompt that says
     "regenerate ONLY the magenta-highlighted region; keep the rest pixel-
     identical." The model treats the magenta as an unmistakable spatial cue.

For sketch-to-image we send just the user's sketch as a single conditioning
image with a prompt that frames it as layout-only.

Both paths inherit brand context (palette, mood, anti-prompts) from the same
snapshot frame_gen uses, so the edits look like they came from the same
brand photographer that made the keyframe.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

from app.config import settings

log = logging.getLogger(__name__)

_client: genai.Client | None = None

VALID_ASPECTS: tuple[str, ...] = ("1:1", "16:9", "9:16")

# Mirrored from frame_gen so edits don't regress in style relative to the
# original keyframes they're derived from.
_UNIVERSAL_ANTI_PROMPT = (
    "Critical: this is a marketing-grade still, not a website screenshot. "
    "Do NOT include UI elements (buttons, navigation bars, dropdowns, "
    "search bars, form inputs, sliders, modal dialogs, scroll indicators, "
    "browser chrome). Do NOT use rainbow gradients, shiny chrome 3D, "
    "generic AI-stock-photo aesthetics, fake-creator AI faces, or "
    "watermarks. The image should look like an in-house brand photographer/"
    "designer made it."
)

_NO_TEXT_ANTI_PROMPT = (
    "ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO CAPTIONS, NO TYPOGRAPHY, "
    "NO WATERMARKS, NO LOGOS RENDERED INTO THE IMAGE."
)

# Magenta is chosen for the inpaint cue because it almost never appears in
# brand keyframes (where palettes lean editorial/neutral), so the model
# unambiguously reads it as "instruction, not content."
_HIGHLIGHT_RGBA: tuple[int, int, int, int] = (255, 0, 220, 153)  # ~60% alpha


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _brand_block(brand: dict | None) -> str:
    """Compact brand-context paragraph appended to edit prompts.

    Pulls in the brand picture book (PIC.md) when available — image edits
    must obey the same evergreen visual identity as fresh keyframes so the
    inpainted region doesn't drift off-style. Falls back to the legacy
    style_profile digest when no PIC.md has been generated yet.
    """
    if not brand:
        return ""

    # Prefer PIC.md when present — it's the canonical visual identity
    # source. The format_for_prompt helper strips markdown chrome and caps
    # length for prompt budgets.
    from app.services.brand_book import (
        format_for_prompt as _pic_format,
    )
    from app.services.brand_book import load_pic as _load_pic

    bid = str(brand.get("id") or "").strip()
    pic_block = _pic_format(_load_pic(bid)) if bid else ""
    if pic_block:
        return pic_block

    # Legacy fallback path — used during the first image-edit call before
    # PIC.md has been generated. The composer kicks off automatically on
    # the first /api/brand/pic GET.
    name = brand.get("name") or "the brand"
    palette = (brand.get("palette") or [])[:4]
    palette_str = ", ".join(palette) if palette else ""
    style = brand.get("style_profile") or {}
    mood = style.get("mood") or ""
    photo_vs_illust = style.get("photographic_vs_illustrated") or ""

    parts: list[str] = [f"Brand context: {name}."]
    if palette_str:
        parts.append(f"Palette to honour: {palette_str}.")
    if mood:
        parts.append(f"Mood: {mood}.")
    if photo_vs_illust:
        parts.append(f"Treatment: {photo_vs_illust}.")
    return " ".join(parts)


def _composite_highlight(
    source_bytes: bytes, mask_bytes: bytes
) -> tuple[bytes, tuple[int, int]]:
    """Paint the masked region of `source_bytes` magenta @ ~60% alpha.

    Returns (highlighted_png_bytes, (width, height)). The mask is expected
    as an RGBA PNG where the alpha channel marks the user's brush strokes
    (alpha > 0 = "change this pixel"). If dimensions don't match the source,
    the mask is resized with NEAREST so brush edges stay crisp.
    """
    src = Image.open(io.BytesIO(source_bytes)).convert("RGBA")
    mask = Image.open(io.BytesIO(mask_bytes)).convert("RGBA")
    if mask.size != src.size:
        mask = mask.resize(src.size, Image.NEAREST)

    # Use the mask's alpha channel as the hit-map. Fully transparent pixels
    # are untouched; anything else becomes magenta-highlighted.
    alpha = mask.split()[3]

    overlay = Image.new("RGBA", src.size, _HIGHLIGHT_RGBA)
    highlighted = src.copy()
    highlighted.paste(overlay, (0, 0), alpha)

    buf = io.BytesIO()
    highlighted.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue(), src.size


def _decode_data_url(data_url: str) -> tuple[bytes, str] | None:
    """data:<mime>;base64,<payload> → (bytes, mime). Returns None on parse fail."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        head, b64 = data_url.split(",", 1)
        mime = head[5:].split(";")[0] or "image/png"
        from base64 import b64decode

        return b64decode(b64), mime
    except Exception:
        return None


def _extract_image_bytes(response: Any) -> bytes | None:
    """Pull the first inline image part out of a Gemini response."""
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


def _aspect_config(aspect: str) -> dict[str, Any]:
    cfg: dict[str, Any] = {"response_modalities": ["IMAGE", "TEXT"]}
    try:
        cfg["image_config"] = types.ImageConfig(aspect_ratio=aspect)
    except (AttributeError, TypeError):
        cfg["image_config"] = {"aspect_ratio": aspect}
    return cfg


# ── Inpaint ──────────────────────────────────────────────────────────────


def _build_inpaint_prompt(brand: dict | None, user_request: str) -> str:
    parts: list[str] = [
        "You are editing an existing marketing-grade image.",
        (
            "The first image is the ORIGINAL. The second image is the same "
            "original with a vivid magenta region painted over the area the "
            "user wants changed. That magenta region is an instruction, not "
            "content — it does NOT appear in the desired output."
        ),
        (
            "Regenerate ONLY the magenta-highlighted region. Replace it with: "
            f"{user_request[:1500]}"
        ),
        (
            "Outside the highlighted region the output MUST be pixel-identical "
            "to the original — same composition, lighting, palette, subjects, "
            "framing, grain. Match seam edges so the new region blends "
            "naturally into the surrounding original."
        ),
        "Output the FULL edited image at the same dimensions as the original.",
    ]
    block = _brand_block(brand)
    if block:
        parts.append(block)
    parts.append(_UNIVERSAL_ANTI_PROMPT)
    parts.append(_NO_TEXT_ANTI_PROMPT)
    return " ".join(parts)


async def inpaint_image(
    brand: dict | None,
    source_bytes: bytes,
    mask_bytes: bytes,
    prompt: str,
    aspect: str = "16:9",
) -> bytes | None:
    """Regenerate the masked region of `source_bytes` per `prompt`.

    Returns new image bytes, or None if the model didn't produce one.
    Raises ValueError on bad inputs (unknown aspect, undecodable image).
    """
    if aspect not in VALID_ASPECTS:
        raise ValueError(f"aspect must be one of {VALID_ASPECTS}, got {aspect!r}")

    client = _get_client()
    if client is None:
        log.warning("inpaint: no GEMINI_API_KEY")
        return None

    try:
        highlighted, _size = _composite_highlight(source_bytes, mask_bytes)
    except Exception as e:
        raise ValueError(f"failed to composite mask onto source: {e}") from e

    full_prompt = _build_inpaint_prompt(brand, prompt)

    contents: list[Any] = [
        full_prompt,
        types.Part.from_bytes(data=source_bytes, mime_type="image/png"),
        types.Part.from_bytes(data=highlighted, mime_type="image/png"),
    ]

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=contents,
            config=types.GenerateContentConfig(**_aspect_config(aspect)),
        )
    except Exception as e:
        log.warning("inpaint: API call failed: %s", e)
        return None

    image = _extract_image_bytes(response)
    if image is None:
        log.warning("inpaint: no image part in response")
    return image


# ── Sketch → image ───────────────────────────────────────────────────────


def _build_sketch_prompt(brand: dict | None, user_request: str) -> str:
    parts: list[str] = [
        (
            "Render the attached rough hand-drawn sketch as a polished, "
            "marketing-grade still."
        ),
        (
            "The sketch defines LAYOUT and KEY SHAPES only — treat strokes as "
            "compositional guides, not literal pixels. Replace the sketch's "
            "lines with photographically (or illustratively, per brand "
            "treatment) realised forms."
        ),
        f"Subject / scene: {user_request[:1500]}",
    ]
    block = _brand_block(brand)
    if block:
        parts.append(block)
    parts.append(_UNIVERSAL_ANTI_PROMPT)
    parts.append(_NO_TEXT_ANTI_PROMPT)
    return " ".join(parts)


async def sketch_to_image(
    brand: dict | None,
    sketch_bytes: bytes,
    prompt: str,
    aspect: str = "16:9",
) -> bytes | None:
    """Generate a fresh image conditioned on a user-drawn sketch."""
    if aspect not in VALID_ASPECTS:
        raise ValueError(f"aspect must be one of {VALID_ASPECTS}, got {aspect!r}")

    client = _get_client()
    if client is None:
        log.warning("sketch→image: no GEMINI_API_KEY")
        return None

    full_prompt = _build_sketch_prompt(brand, prompt)
    contents: list[Any] = [
        full_prompt,
        types.Part.from_bytes(data=sketch_bytes, mime_type="image/png"),
    ]

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=contents,
            config=types.GenerateContentConfig(**_aspect_config(aspect)),
        )
    except Exception as e:
        log.warning("sketch→image: API call failed: %s", e)
        return None

    image = _extract_image_bytes(response)
    if image is None:
        log.warning("sketch→image: no image part in response")
    return image


# Re-export the helpers the API layer needs without re-importing from inside
# api modules (keeps the dependency direction clean).
def decode_data_url(data_url: str) -> tuple[bytes, str] | None:
    return _decode_data_url(data_url)
