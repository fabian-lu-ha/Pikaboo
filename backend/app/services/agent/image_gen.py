"""Channel-aware image generation via Gemini's nano-banana-pro model.

Conditions the image on:
  - the brand's captured palette (top 4)
  - the brand's mood + composition + photographic_vs_illustrated +
    distinctive_marks (NOT generation_guidance / radii / shadows / button_tokens —
    those are web-rendering instructions and bleed UI artifacts into the image)
  - the channel's aspect (passed via image_config.aspect_ratio, snapped to a
    nano-banana-supported ratio when the display aspect isn't supported)
  - the channel's role + composition note (banner vs square vs feed-image idiom)
  - the channel's anti-patterns (channel-specific AI-slop tells, fed into a
    targeted negative-prompt block)
  - up to 2 uploaded brand assets passed as visual reference parts
    (multi-image input on nano-banana-pro), so generated imagery looks like
    the brand's actual photography rather than generic AI-art

DENY-LIST (do not inject into image prompts — see docs/CHANNEL_PLAYBOOK.md §6):
  - style_profile.generation_guidance     (web-rendering only)
  - identity.radii / shadows / button_tokens / components  (UI specs)
"""

from __future__ import annotations

import logging
from base64 import b64decode
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.services.agent.channels import Channel

log = logging.getLogger(__name__)

_client: genai.Client | None = None

# Universal anti-prompt block — appended to every image prompt regardless of
# channel. Targets the failure modes we actually see.
_UNIVERSAL_ANTI_PROMPT = (
    "Critical: this is social-media feed content, not a website screenshot. "
    "Do NOT include UI elements (buttons, navigation bars, dropdowns, search "
    "bars, form inputs, sliders, modal dialogs, scroll indicators, browser "
    "chrome). Do NOT render text as a CTA pill. Do NOT use rainbow gradients, "
    "shiny chrome 3D, generic AI-stock-photo aesthetics, stock corporate "
    "handshakes, fake-creator AI faces, or watermarks. The image should look "
    "like an in-house brand photographer/designer made it for this specific channel."
)


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _build_prompt(
    brand: dict, channel: Channel, user_request: str
) -> str:
    name = brand.get("name") or "the brand"
    palette = (brand.get("palette") or [])[:4]
    palette_str = ", ".join(palette) if palette else ""

    # SAFE allow-list from style_profile (see docs/CHANNEL_PLAYBOOK.md §6).
    style = brand.get("style_profile") or {}
    mood = style.get("mood") or ""
    composition = style.get("composition") or ""
    photo_vs_illust = style.get("photographic_vs_illustrated") or ""
    distinctive_marks = style.get("distinctive_marks") or []

    img = channel.image
    aspect_label = img.aspect_label if img else "landscape"
    role = img.role if img else "feed image"

    parts: list[str] = [
        f"Create a {aspect_label} {role} for {name}.",
        f"Subject: {user_request[:240]}",
    ]
    if channel.image_composition_note:
        parts.append(f"Channel composition: {channel.image_composition_note}")
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
            f"Visual signatures to keep: "
            f"{'; '.join(distinctive_marks[:3])}."
        )

    # Reference brands the user picked — borrow palette accents and style cues
    # without copying. Fed as inspiration alongside the brand's own palette so
    # the output reads as "your brand, but with the energy of [reference]".
    refs = brand.get("reference_brands") or []
    ref_palette_hex: list[str] = []
    ref_names: list[str] = []
    for r in refs[:2]:
        name = (r.get("name") or "").strip()
        if name:
            ref_names.append(name)
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

    # Image-side anti-patterns from the channel registry — pulls in tells that
    # are specific to this surface (e.g. "no rendered LEARN MORE button" on IG).
    if channel.anti_patterns:
        parts.append(
            f"For {channel.label} specifically, AVOID: "
            + "; ".join(channel.anti_patterns)
            + "."
        )
    parts.append(_UNIVERSAL_ANTI_PROMPT)
    return " ".join(parts)


def _load_asset_bytes(asset_url: str | None) -> tuple[bytes, str] | None:
    """Resolve a stored asset URL to raw bytes for multi-image input.
    Currently only supports local-mode storage (the /api/storage/... URLs).
    Returns (bytes, mime_type) or None.
    """
    if not asset_url or settings.deploy_mode != "local":
        return None
    if asset_url.startswith("data:"):
        try:
            head, b64 = asset_url.split(",", 1)
            mime = head.split(";")[0].removeprefix("data:") or "image/png"
            return b64decode(b64), mime
        except Exception:
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
    """Take up to N brand-uploaded assets as reference image parts.

    nano-banana-pro accepts up to 14 reference images per request; we cap
    aggressively at 2 because more refs dilute the channel composition prompt.
    """
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


async def generate_channel_image(
    brand: dict, channel: Channel, user_request: str
) -> bytes | None:
    """Generate one image for one channel. Returns image bytes or None."""
    client = _get_client()
    if client is None:
        log.warning("image gen: no GEMINI_API_KEY")
        return None

    prompt = _build_prompt(brand, channel, user_request)
    asset_refs = _asset_parts(brand)

    contents: list[Any] = [prompt, *asset_refs]
    gen_aspect = channel.image.gen_aspect if channel.image else "16:9"

    config_kwargs: dict[str, Any] = {
        "response_modalities": ["IMAGE", "TEXT"],
    }
    # image_config.aspect_ratio is the canonical way to control output aspect
    # on nano-banana-pro. The text prompt alone is unreliable at constraining
    # ratio — the API param is authoritative.
    try:
        config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=gen_aspect)
    except (AttributeError, TypeError):
        # Older google-genai versions don't expose ImageConfig — fall back to
        # a plain dict; the SDK accepts both shapes.
        config_kwargs["image_config"] = {"aspect_ratio": gen_aspect}

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        log.warning(
            "image gen %s: API call failed: %s", channel.id, e
        )
        return None

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
    log.warning("image gen %s: no image part in response", channel.id)
    return None
