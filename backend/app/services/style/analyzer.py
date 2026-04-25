"""Brand visual-style analyzer.

Calls Gemini multi-image vision in a single request, returns a structured
``StyleProfile`` describing the brand's visuals. Best-effort: any failure
(quota, malformed response, transport error) yields ``None`` and a logged
warning — never raises.

API patterns are based on the 2026 google-genai SDK:
- ``contents`` accepts a flat list mixing strings and ``types.Part`` objects;
  the SDK collapses them into a single user-role ``Content``.
- Inline image bytes go through ``types.Part.from_bytes(data=..., mime_type=...)``.
- Total inline request size is capped at 20MB across all parts (text + bytes).
- Structured output via ``response_mime_type='application/json'`` +
  ``response_schema``. Gemini's JSON-Schema dialect rejects ``additionalProperties``,
  so we strip it (mirroring ``app.services.llm.client``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_IMAGES = 8
"""Cap on images per call. Gemini accepts more, but we keep latency + cost
predictable, and the prompt stays focused. We keep the *most recent* images
when more are supplied (drop oldest)."""

MAX_IMAGE_BYTES = 1_000_000
"""Per-image size guard (1MB). Gemini's hard cap is the 20MB total-request
budget; we conservatively skip images bigger than 1MB rather than try to
re-encode/downscale here (that would pull in Pillow, which we don't need
for a hackathon ship). The caller is expected to feed reasonably-sized
screenshots."""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class StyleProfile:
    palette_character: str
    composition: str
    mood: str
    typography_feel: str
    photographic_vs_illustrated: str
    distinctive_marks: list[str]
    generation_guidance: list[str]


# Gemini response schema — same dialect rules as our other prompts:
# no ``additionalProperties`` (the SDK rejects it). Required fields enforce
# the dataclass shape so ``StyleProfile(**data)`` is safe.
STYLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "palette_character": {"type": "string"},
        "composition": {"type": "string"},
        "mood": {"type": "string"},
        "typography_feel": {"type": "string"},
        "photographic_vs_illustrated": {"type": "string"},
        "distinctive_marks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "generation_guidance": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "palette_character",
        "composition",
        "mood",
        "typography_feel",
        "photographic_vs_illustrated",
        "distinctive_marks",
        "generation_guidance",
    ],
}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_client: genai.Client | None = None


def _client_or_none() -> genai.Client | None:
    """Return a genai client, or ``None`` if no API key is configured.

    Replicates the small init from ``app.services.llm.client`` so this
    module stays cleanly decoupled (no underscore-private import).
    """
    global _client
    if _client is not None:
        return _client
    if not settings.gemini_api_key:
        log.warning("style.analyze_style: GEMINI_API_KEY not set; skipping")
        return None
    _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _sniff_mime(data: bytes) -> str:
    """Best-effort MIME sniff from magic bytes.

    Gemini accepts image/jpeg, image/png, image/webp, image/gif, image/heic,
    image/heif. We fall back to JPEG for unknown types — the model is tolerant
    and most screenshots are JPEG/PNG anyway.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _select_images(image_bytes_list: list[bytes]) -> list[bytes]:
    """Cap count, drop oversized, preserving order of the kept slice."""
    # Drop oldest if over MAX_IMAGES.
    candidates = image_bytes_list[-MAX_IMAGES:] if len(image_bytes_list) > MAX_IMAGES else list(image_bytes_list)
    kept: list[bytes] = []
    for i, b in enumerate(candidates):
        if not b:
            continue
        if len(b) > MAX_IMAGE_BYTES:
            log.warning(
                "style.analyze_style: skipping image %d (%d bytes > %d cap)",
                i,
                len(b),
                MAX_IMAGE_BYTES,
            )
            continue
        kept.append(b)
    return kept


def _strip_unsupported(schema: Any) -> Any:
    """Strip keys Gemini's response_schema dialect rejects (additionalProperties)."""
    if isinstance(schema, dict):
        return {
            k: _strip_unsupported(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_strip_unsupported(item) for item in schema]
    return schema


def _build_prompt(brand_name: str, palette: list[str]) -> str:
    palette_str = ", ".join(palette) if palette else "(unspecified)"
    return (
        f"You are a brand visual analyst. Given these screenshots and product "
        f"images of the brand `{brand_name}` whose color palette is "
        f"`{palette_str}`, describe the visual style in structured form.\n\n"
        f"Be SPECIFIC — mention concrete visual details you can actually see "
        f"(layout patterns, recurring shapes, photo treatments, type weight, "
        f"whitespace habits, iconography, motion implied by composition). "
        f"Avoid generic adjectives like 'modern', 'clean', 'professional' "
        f"unless you back them with a concrete observation.\n\n"
        f"Fields:\n"
        f"- palette_character: 1-2 sentences on how the colors are USED "
        f"(not just listed) — dominance, accents, contrast strategy.\n"
        f"- composition: how images are typically composed (grid, "
        f"hero+supporting, full-bleed photography, asymmetric, etc.).\n"
        f"- mood: the tone/feeling the visuals project.\n"
        f"- typography_feel: the type vibe — even if you're inferring from "
        f"screenshots, name weights, contrast (serif/sans/mono), density.\n"
        f"- photographic_vs_illustrated: which dominates and how the two "
        f"interact, with concrete examples.\n"
        f"- distinctive_marks: 3-6 specific visual signatures that make this "
        f"brand recognizable (e.g., 'oversized rounded buttons with 4px "
        f"black borders', 'duotone product photography in cyan/magenta').\n"
        f"- generation_guidance: 3-5 short imperatives (one short sentence "
        f"each) that an image-generation model should follow to render new "
        f"assets in this brand's style. Concrete, actionable, no fluff."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze_style(
    image_bytes_list: list[bytes],
    brand_name: str,
    palette: list[str],
) -> StyleProfile | None:
    """Analyze a brand's visual style from a set of images.

    Best-effort: returns ``None`` on any failure or if there are no usable
    images. Never raises.
    """
    if not image_bytes_list:
        log.warning("style.analyze_style: no images supplied")
        return None

    client = _client_or_none()
    if client is None:
        return None

    images = _select_images(image_bytes_list)
    if not images:
        log.warning("style.analyze_style: no images survived size/cap filter")
        return None

    prompt = _build_prompt(brand_name, palette)

    # contents = [text prompt, image1, image2, ...]
    # The SDK collapses this flat list into a single user-role Content.
    contents: list[Any] = [prompt]
    for b in images:
        contents.append(types.Part.from_bytes(data=b, mime_type=_sniff_mime(b)))

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_strip_unsupported(STYLE_SCHEMA),
    )

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=config,
        )
    except Exception as e:  # noqa: BLE001 - best-effort by contract
        log.warning(
            "style.analyze_style: Gemini call failed for %r: %s",
            brand_name,
            e,
        )
        return None

    raw = getattr(response, "text", None)
    if not raw:
        log.warning("style.analyze_style: empty response for %r", brand_name)
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning(
            "style.analyze_style: non-JSON response for %r: %s",
            brand_name,
            e,
        )
        return None

    try:
        return StyleProfile(
            palette_character=str(data.get("palette_character", "")),
            composition=str(data.get("composition", "")),
            mood=str(data.get("mood", "")),
            typography_feel=str(data.get("typography_feel", "")),
            photographic_vs_illustrated=str(
                data.get("photographic_vs_illustrated", "")
            ),
            distinctive_marks=[str(x) for x in (data.get("distinctive_marks") or [])],
            generation_guidance=[
                str(x) for x in (data.get("generation_guidance") or [])
            ],
        )
    except Exception as e:  # noqa: BLE001 - shape mismatch -> degrade gracefully
        log.warning(
            "style.analyze_style: could not coerce response for %r: %s",
            brand_name,
            e,
        )
        return None
