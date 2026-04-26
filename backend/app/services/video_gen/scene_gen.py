"""Per-scene video clip generator via Veo 3.1.

This replaces the previous still-keyframe approach (`frame_gen.generate_video_frame`)
for the production path: each storyboard frame becomes a 2-8 second video
clip rendered by Veo, conditioned on a cast canonical image so characters
and products stay consistent across clips.

Veo is a long-running operation — generation typically takes 30-90s per
clip. This module:
  - builds the prompt (motion direction + cast references named explicitly)
  - loads the primary cast canonical as a subject-reference image
  - submits to Veo via google.genai
  - polls the operation handle until done or timeout
  - downloads the resulting mp4 bytes

The hardened no-text anti-prompt mirrored from frame_gen still applies —
Remotion overlays all titles/captions on top of the rendered clips.
"""

from __future__ import annotations

import asyncio
import logging
import random
from base64 import b64decode
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from google import genai
from google.genai import types

from app.config import settings
from app.services.brand_book import format_for_prompt as _format_pic_for_prompt
from app.services.brand_book import load_pic
from app.services.video_gen.cast import CastRef


def _pic_block(brand: dict) -> str:
    """Resolve the brand's PIC.md into a prompt prefix block. Empty string
    when no PIC has been generated yet — Veo prompts stay valid either way."""
    bid = str((brand or {}).get("id") or "").strip()
    if not bid:
        return ""
    return _format_pic_for_prompt(load_pic(bid))

VeoQuality = Literal["fast", "quality"]
RetryPhase = Literal["submit", "poll"]
# Callback signature: receives a dict with keys phase, attempt, max_attempts,
# delay_s, reason. Used to surface retry progress to event consumers (UI).
RetryCallback = Callable[[dict], None]

log = logging.getLogger(__name__)

_client: genai.Client | None = None

# Veo natively renders 16:9 and 9:16. Square (1:1) requests fall back to
# 9:16 — the compositor crops to square downstream if needed.
VALID_VEO_ASPECTS: tuple[str, ...] = ("16:9", "9:16")

# Veo 3 enforces a 4-second minimum (and 8-second maximum) per clip.
# Storyboard frames may request shorter shows — Remotion truncates the
# rendered clip to the storyboard's `duration_ms` at composite time, so we
# pay for 4s of Veo footage but only display what the planner asked for.
DEFAULT_DURATION_S = 5
MIN_DURATION_S = 4
MAX_DURATION_S = 8

POLL_INTERVAL_S = 3  # 5 → 3: detect Veo completion ~2s sooner per clip
# 5-minute ceiling per scene. Empirical data from E2E run (Apr 2026, 6
# scenes fired with 1s stagger):
#   60s, 180s, 180s, 180s, 240s, BLACK-HOLED
# The slowest real render finished at 240s, so 180s was too tight (would
# have killed a real-but-slow op). 300s captures the long tail of real
# renders and fails black-holed ops in 5 min instead of the previous 8 min
# 480s. Once it fails the user re-animates that one frame manually — a
# fresh op almost always succeeds.
POLL_TIMEOUT_S = 300

# Retry policy for transient Veo 5xx (UNAVAILABLE / DEADLINE_EXCEEDED). The
# operation itself is usually fine — backoff and try again. Total worst-case
# wait across all retries (without jitter): 1+2+4+8 = 15s.
MAX_TRANSIENT_RETRIES = 4
RETRY_BACKOFF_BASE_S = 1.0
# ±25% jitter so 6 simultaneously-503'd scenes don't all retry at exactly
# t+1s and re-collide on the same Google quota slot. Each scene now waits
# a slightly different interval, decorrelating the retry herd.
RETRY_JITTER_RATIO = 0.25


class SceneGenError(RuntimeError):
    """Raised when scene generation fails. The message is suitable for
    surfacing to the API consumer (concise, no stack info)."""


# Veo accepts a separate `negative_prompt` param — that's the proper home
# for "don't do this" directives. The Veo 3.1 prompting guide is explicit:
# the main prompt should be positive direction (cinematography + subject +
# action + context + style); negatives go in negative_prompt, where they're
# attended to as exclusions rather than competing with the positive scene
# description. We split our anti-DOs accordingly.

# Positive aesthetic anchor — directs the LOOK.
_POSITIVE_STYLE_ANCHOR = (
    "Netflix- and Apple-commercial-grade cinematography. Treat this as a "
    "hero shot from a flagship spot — real cinema glass, intentional "
    "framing, professional motion. The clip must look like live-action "
    "captured by a brand cinematographer."
)

# Inverted negative prompt — every "do not X" rewritten as a positive
# direction the model can act on. Goes into the main prompt body for ALL
# models, because Veo 3.1 preview variants reject the negative_prompt field
# (so we lose nothing by also putting these as positives) and Veo 3.0 just
# gets the discipline reinforced from two channels (belt + suspenders).
#
# Each line directs toward the desired behavior, not away from undesired —
# generative models attend to *positive* directions far more reliably than
# they suppress negative ones, especially when the negative_prompt slot is
# unavailable.
_POSITIVE_DISCIPLINE = (
    "Discipline this shot must obey: "
    "(1) Pure visual scene — all typography lives in the post-compositor "
    "layer, never rendered into the footage itself. The clip carries no "
    "captions, no subtitles, no logos baked into the image, no on-screen "
    "UI, no browser chrome, no HUD overlays. "
    "(2) Every person who appears is fully in frame from the first "
    "moment — no body parts (hands, fingers, arms, shoulders) enter from "
    "any edge during the shot. The cast list is locked at frame one. "
    "(3) Camera moves are professional-grade only: dolly, push-in, pan, "
    "slider, gimbal, or locked-off tripod. Smooth, intentional motion at "
    "human scale — gimbal-grade stability throughout, no micro-shake, no "
    "AI wobble, no jittery handheld tremor. No phone-camera interactions, "
    "no pinch-zoom moves, no someone-holds-a-phone framing. "
    "(4) Natural anatomy on every visible body part — full hands with five "
    "fingers each, properly formed faces, real limbs. "
    "(5) The first frame defines every person, prop, surface, and "
    "environmental element in this shot. Veo's job is to add MOTION to "
    "what's already there, not to introduce new visual elements. No new "
    "people appear, no new objects appear, the room does not change. "
    "(6) Natural color science, real-world materials, hand-composed "
    "framing. The grade is honest film-stock — Kodak Portra-style "
    "midtones, lifted shadows, real cinema-glass falloff — never AI-stock-"
    "photo gloss, never rainbow gradients, never shiny chrome 3D, never "
    "stock-corporate handshakes."
)

# Models that accept the `negative_prompt` field on GenerateVideosConfig.
# Veo 3.0 (both standard and fast) accepts it; Veo 3.1 preview variants
# (incl. lite) reject it with HTTP 400 — we just verified empirically. So
# negative_prompt is OPT-IN per model name. When unsupported, the negative
# directives stay in our positive prompt as a fallback (less effective but
# better than a 400 error).
def _model_supports_negative_prompt(model: str) -> bool:
    return model.startswith("veo-3.0-")


# All exclusions live here, passed via GenerateVideosConfig.negative_prompt
# (when the model supports it — see _model_supports_negative_prompt).
# Veo 3 negative_prompt is most effective with concrete, named failure modes.
_NEGATIVE_PROMPT = (
    "text, letters, words, captions, subtitles, typography, watermarks, "
    "logos rendered into the video, baked-in title cards, on-screen UI, "
    "buttons, navigation bars, browser chrome, HUD overlays; "
    "offscreen hand, finger, arm, or appendage entering frame from any "
    "edge; phone-style pinch zoom, smartphone-camera interaction, "
    "someone-holds-a-phone framing, finger-pinch zoom; "
    "glove-puppet or floating-hand artifacts; "
    "invented characters, props, surfaces, or environmental elements that "
    "aren't visible in the first frame; new people appearing, new objects "
    "appearing, the room changing; "
    "rainbow gradients, shiny chrome 3D, generic AI-stock-photo gloss, "
    "stock corporate handshakes, fake-creator AI faces; "
    "jittery handheld tremor, shaky cam, AI-video wobble"
)

def _format_brief(brief: dict | None) -> str:
    """Render the director's cinematic brief as a single block of text to
    prepend to every Veo prompt. Keeps each field on its own labeled line
    so Veo can attend to lensing, lighting, and grade independently."""
    if not brief or not isinstance(brief, dict):
        return ""
    parts: list[str] = []
    refs = (brief.get("reference_films") or "").strip()
    lensing = (brief.get("lensing") or "").strip()
    lighting = (brief.get("lighting") or "").strip()
    grade = (brief.get("palette_grade") or "").strip()
    pacing = (brief.get("pacing") or "").strip()
    do_not = (brief.get("do_not") or "").strip()
    if refs:
        parts.append(f"Reference films (match this look): {refs[:500]}")
    if lensing:
        parts.append(f"Lensing: {lensing[:300]}")
    if lighting:
        parts.append(f"Lighting: {lighting[:300]}")
    if grade:
        parts.append(f"Palette / grade: {grade[:300]}")
    if pacing:
        parts.append(f"Pacing: {pacing[:240]}")
    if do_not:
        parts.append(f"Do not (per director): {do_not[:600]}")
    if not parts:
        return ""
    return "DIRECTOR'S BRIEF — every shot inherits this look. " + " ".join(parts)


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        # The Veo preview tier on the Gemini API often needs 50-90s just to
        # ACCEPT a submission when Google's backend is congested. The SDK's
        # default ~60s HTTP deadline trips before that, surfacing as
        # "Deadline expired before operation could complete" — a 503 our
        # retry layer then re-fires, compounding the wait. A 3-minute HTTP
        # timeout absorbs the slow submits without inducing a retry storm.
        # Polling .get() inherits this same generous timeout.
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=180_000),
        )
    return _client


# Public alias so sibling modules (transitions.py) can share the same
# memoised, long-timeout Veo client without forking the init logic.
get_veo_client = _get_client


def _load_asset_bytes(asset_url: str | None) -> tuple[bytes, str] | None:
    """Resolve a stored asset URL to raw bytes for subject-reference input.

    Mirrors frame_gen._load_asset_bytes — local-mode storage and data: URIs.
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
    }.get(suffix, "image/png")
    try:
        return p.read_bytes(), mime
    except OSError:
        return None


def _build_scene_prompt(
    brand: dict,
    scene_prompt: str,
    motion: str,
    cast_refs: list[CastRef],
    has_keyframe: bool = False,
    cinematic_brief: dict | None = None,
) -> str:
    """Veo prompt — two shapes depending on whether a keyframe anchors the shot.

    With a keyframe (image-to-video flow):
      The keyframe IS the composition — same characters, same lighting, same
      framing. Veo's job is to add motion, not invent visuals. So the prompt
      focuses on what MOVES and how the camera responds.

    Without a keyframe (legacy text-to-video flow):
      The prompt has to describe the full scene + cast + motion. Cast
      canonical refs are passed separately as multi-image input.

    `cinematic_brief` (when provided) is the director's overall film
    direction. It's prepended to every shot so the auteur look is unified
    across all clips instead of being reinvented per frame.
    """
    name = brand.get("name") or "the brand"
    style = brand.get("style_profile") or {}
    mood = style.get("mood") or ""
    brief_block = _format_brief(cinematic_brief)
    # PIC.md sits ABOVE the cinematic_brief — it's the brand-level evergreen
    # identity, the brief is the per-storyboard director's vision. Order:
    # brand picture book → director's brief → shot specifics.
    pic_block = _pic_block(brand)

    if has_keyframe:
        # Image-to-video: prompt is motion-first. The first-frame image
        # locks composition/cast/lighting; we only direct what changes.
        parts: list[str] = []
        if pic_block:
            parts.append(pic_block)
        if brief_block:
            parts.append(brief_block)
        parts.extend(
            [
                f"Animate this still frame as a scene from a {name} marketing video.",
                (
                    f"The first frame is the locked composition — "
                    f"keep all subjects, framing, lighting, and color palette "
                    f"IDENTICAL to the reference. Do NOT introduce new people, "
                    f"objects, or scenery."
                ),
            ]
        )
        if motion:
            parts.append(f"Motion direction: {motion[:600]}.")
        else:
            parts.append(
                "Motion: a slow, intentional dolly-in or locked-off frame "
                "with subtle ambient breath only — no zoom, no hand-held."
            )
        # Scene context as flavor only.
        if scene_prompt:
            parts.append(f"Scene context (already shown in the keyframe): {scene_prompt[:400]}.")
        if mood:
            parts.append(f"Mood: {mood}.")
        parts.append(_POSITIVE_STYLE_ANCHOR)
        parts.append(_POSITIVE_DISCIPLINE)
        return " ".join(parts)

    # Text-to-video fallback (no keyframe). Need full scene description.
    palette = (brand.get("palette") or [])[:3]
    palette_str = ", ".join(palette) if palette else ""
    photo_vs_illust = style.get("photographic_vs_illustrated") or ""

    parts = []
    if pic_block:
        parts.append(pic_block)
    if brief_block:
        parts.append(brief_block)
    parts.extend(
        [
            f"A scene from a {name} marketing video.",
            f"Action: {scene_prompt[:1600]}",
        ]
    )
    if motion:
        parts.append(f"Camera and motion: {motion[:400]}.")
    if mood:
        parts.append(f"Mood: {mood}.")
    if photo_vs_illust:
        parts.append(f"Treatment: {photo_vs_illust}.")
    if palette_str:
        parts.append(f"Color palette: {palette_str}.")

    if cast_refs:
        ref_lines: list[str] = []
        for idx, ref in enumerate(cast_refs):
            if not isinstance(ref, dict):
                continue
            n = idx + 1
            kind = ref.get("kind") or "character"
            rid = ref.get("id") or f"ref{n}"
            desc = (ref.get("description") or "").strip()
            if kind == "character":
                ref_lines.append(
                    f"Reference {n} [{rid}] is the canonical appearance of "
                    f"{desc or 'the protagonist'} — keep face, hair, body type, "
                    f"and wardrobe identical across the clip. Use the new motion "
                    f"described above; the reference locks identity only."
                )
            elif kind == "setting":
                ref_lines.append(
                    f"Reference {n} [{rid}] is the canonical location "
                    f"({desc or 'the setting'}) — match interior style, key "
                    f"furniture, and overall lighting palette."
                )
            else:
                ref_lines.append(
                    f"Reference {n} [{rid}] is the canonical {kind} "
                    f"({desc or 'the prop'}) — keep its shape, color, and material."
                )
        if ref_lines:
            parts.append(" ".join(ref_lines))

    parts.append(_POSITIVE_STYLE_ANCHOR)
    return " ".join(parts)


def _keyframe_to_veo_image(keyframe_url: str | None) -> Any | None:
    """Load a keyframe URL into a Veo first-frame Image part.

    Falls back to None on any failure — caller decides whether to fall
    back to cast-canonical-as-first-frame.
    """
    if not keyframe_url:
        return None
    loaded = _load_asset_bytes(keyframe_url)
    if loaded is None:
        log.warning("scene gen: keyframe_url could not be loaded: %s", keyframe_url)
        return None
    data, mime = loaded
    try:
        return types.Image(image_bytes=data, mime_type=mime)
    except (AttributeError, TypeError):
        try:
            return types.Part.from_bytes(data=data, mime_type=mime)
        except Exception:
            return None


def _resolve_aspect(aspect: str) -> str:
    if aspect in VALID_VEO_ASPECTS:
        return aspect
    log.info(
        "scene gen: aspect %s not Veo-native; falling back to 9:16", aspect
    )
    return "9:16"


def _primary_subject_image(cast_refs: list[CastRef]) -> Any | None:
    """Pick the first cast canonical with loadable bytes as Veo's subject ref.

    Veo SDK currently accepts a single first-frame / subject image per call
    in stable; multi-subject is preview. We pick the first character-typed
    ref if available, else the first ref of any kind.
    """
    ordered: list[CastRef] = []
    chars = [r for r in cast_refs if isinstance(r, dict) and r.get("kind") == "character"]
    others = [r for r in cast_refs if isinstance(r, dict) and r.get("kind") != "character"]
    ordered.extend(chars)
    ordered.extend(others)

    for ref in ordered:
        url = ref.get("canonical_url") if isinstance(ref, dict) else None
        if not url:
            continue
        loaded = _load_asset_bytes(url)
        if loaded is None:
            continue
        data, mime = loaded
        try:
            return types.Image(image_bytes=data, mime_type=mime)
        except (AttributeError, TypeError):
            try:
                # SDK variant: Image takes a Part-like blob
                return types.Part.from_bytes(data=data, mime_type=mime)
            except Exception:
                return None
    return None


def _is_transient_veo_error(exc: Exception) -> bool:
    """503 UNAVAILABLE / 504 DEADLINE_EXCEEDED are Google's "try again" signals.

    The Veo SDK formats both as text-prefixed errors (e.g. "503 UNAVAILABLE.
    {...}"), and the dict payload's message is usually one of "The service
    is currently unavailable" or "Deadline expired before operation could
    complete". All of these are safe to retry — the operation either never
    started (submit-side) or is still running on Google's side (poll-side).
    """
    msg = str(exc)
    if "503" in msg or "UNAVAILABLE" in msg:
        return True
    if "504" in msg or "DEADLINE_EXCEEDED" in msg:
        return True
    if "Deadline expired" in msg:
        return True
    return False


async def _retry_transient(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    label: RetryPhase,
    on_retry: RetryCallback | None = None,
) -> tuple[Any, int]:
    """Run a coroutine, retrying transient Veo 5xx with exponential backoff.

    The factory is called fresh on each attempt so we get a new awaitable
    each retry (you can't await the same coroutine twice).

    Returns (result, attempts_made). attempts_made is 0 on first-try success;
    each retry increments it. Raises the last exception after MAX_TRANSIENT_RETRIES,
    or any non-transient exception immediately.
    """
    attempts = 0
    while True:
        try:
            result = await coro_factory()
            return result, attempts
        except Exception as e:
            if not _is_transient_veo_error(e):
                raise
            if attempts >= MAX_TRANSIENT_RETRIES:
                log.warning(
                    "scene gen: %s gave up after %s transient retries: %s",
                    label, attempts, _summarize_veo_error(e),
                )
                raise
            attempts += 1
            base_delay = RETRY_BACKOFF_BASE_S * (2 ** (attempts - 1))
            # Jitter ±RETRY_JITTER_RATIO so concurrent retries don't sync up.
            jitter = base_delay * RETRY_JITTER_RATIO
            delay = base_delay + random.uniform(-jitter, jitter)
            reason = _summarize_veo_error(e)
            log.warning(
                "scene gen: %s transient 5xx — retry %s/%s in %.1fs: %s",
                label, attempts, MAX_TRANSIENT_RETRIES, delay, reason,
            )
            if on_retry is not None:
                try:
                    on_retry(
                        {
                            "phase": label,
                            "attempt": attempts,
                            "max_attempts": MAX_TRANSIENT_RETRIES,
                            "delay_s": delay,
                            "reason": reason,
                        }
                    )
                except Exception:
                    log.exception("scene gen: on_retry callback raised")
            await asyncio.sleep(delay)


def _resolve_veo_model(quality: VeoQuality) -> str:
    """Pick the Veo model identifier for the requested quality tier.

    Fast: ~30-45s per clip, lower fidelity, cheaper — best for iteration.
    Quality: ~60-90s per clip, hero-render fidelity — best for finals.
    """
    if quality == "quality":
        return settings.veo_quality_model
    return settings.veo_fast_model


async def generate_scene(
    brand: dict,
    scene_prompt: str,
    aspect: str,
    duration_s: int,
    cast_refs: list[CastRef] | None = None,
    motion: str = "",
    quality: VeoQuality = "fast",
    keyframe_url: str | None = None,
    cinematic_brief: dict | None = None,
    on_retry: RetryCallback | None = None,
) -> bytes | None:
    """Generate one scene clip via Veo. Returns mp4 bytes or None.

    `keyframe_url` (preferred): a pre-rendered still keyframe URL — Veo runs
    in image-to-video mode using this as the first frame. Composition, cast,
    and lighting are locked by the keyframe; Veo just adds motion. This is
    the canonical "two-phase" pipeline: prompt → keyframe → keyframe+motion → clip.

    Falls back to text-to-video with cast-canonical-as-first-frame when no
    keyframe is provided.

    `quality` selects the Veo model:
      - "fast": veo_fast_model (default — best for iteration)
      - "quality": veo_quality_model (hero-render — slower, more expensive)

    `on_retry` is invoked once per transient-5xx retry with a dict payload
    so callers can surface attempt counts to the UI. It does NOT control
    retry policy — that's owned by `_retry_transient`.

    Caller is responsible for storing the bytes and URL'ing them. Concurrency
    is uncapped — every storyboard frame fires in parallel. The retry
    helper still absorbs transient 503s the parallelism may cause.
    """
    requested_s = int(duration_s)
    duration_s = max(MIN_DURATION_S, min(MAX_DURATION_S, requested_s))
    if duration_s != requested_s:
        log.info(
            "scene gen: duration clamped %ss → %ss (Veo accepts %s-%ss)",
            requested_s, duration_s, MIN_DURATION_S, MAX_DURATION_S,
        )
    aspect = _resolve_aspect(aspect)
    model = _resolve_veo_model(quality)

    client = _get_client()
    if client is None:
        log.warning("scene gen: no GEMINI_API_KEY")
        raise SceneGenError("GEMINI_API_KEY is not configured")

    refs: list[CastRef] = list(cast_refs or [])

    # Prefer the keyframe as Veo's first frame (image-to-video). Fall back
    # to the first cast canonical only when no keyframe was provided.
    primary_image = _keyframe_to_veo_image(keyframe_url)
    has_keyframe = primary_image is not None
    if not has_keyframe:
        primary_image = _primary_subject_image(refs)

    full_prompt = _build_scene_prompt(
        brand,
        scene_prompt,
        motion,
        refs,
        has_keyframe=has_keyframe,
        cinematic_brief=cinematic_brief,
    )

    config_kwargs: dict[str, Any] = {
        "aspect_ratio": aspect,
        "duration_seconds": duration_s,
        "number_of_videos": 1,
    }
    # Per the Veo 3 prompting guide, negative directives belong here — not
    # in the main prompt. Veo 3.0 supports the field; Veo 3.1 preview
    # variants reject it. Gate on model so we don't 400 on the lite/fast
    # preview path. When unsupported, the negatives stay in the positive
    # prompt fallback (handled by _build_scene_prompt's anti-prompt block).
    if _model_supports_negative_prompt(model):
        config_kwargs["negative_prompt"] = _NEGATIVE_PROMPT
    # We let Veo apply its regional default for person_generation. Earlier
    # versions of this code passed "allow_all" but current Veo API rejects
    # that value (use "allow_adult" / "dont_allow" if you need to override).
    config = types.GenerateVideosConfig(**config_kwargs)

    log.info(
        "scene gen: model=%s quality=%s aspect=%s duration=%ss keyframe=%s",
        model,
        quality,
        aspect,
        duration_s,
        bool(has_keyframe),
    )
    submit_kwargs: dict[str, Any] = {
        "model": model,
        "prompt": full_prompt,
        "config": config,
    }
    if primary_image is not None:
        submit_kwargs["image"] = primary_image

    submit_retries = 0
    poll_retries = 0
    elapsed = 0

    try:
        op, submit_retries = await _retry_transient(
            lambda: client.aio.models.generate_videos(**submit_kwargs),
            label="submit",
            on_retry=on_retry,
        )
    except Exception as e:
        log.warning(
            "scene gen: API submit failed after %s retries: %s",
            submit_retries, e,
        )
        raise SceneGenError(
            f"{_summarize_veo_error(e)} (after {submit_retries} retries)"
        ) from e

    if submit_retries:
        log.info(
            "scene gen: submit succeeded after %s transient retries",
            submit_retries,
        )

    while not getattr(op, "done", False):
        if elapsed >= POLL_TIMEOUT_S:
            log.warning(
                "scene gen: poll timeout after %ss (submit_retries=%s, poll_retries=%s)",
                elapsed, submit_retries, poll_retries,
            )
            raise SceneGenError(
                f"Veo render exceeded {POLL_TIMEOUT_S}s timeout "
                f"(after {submit_retries} submit retries, {poll_retries} poll retries)"
            )
        await asyncio.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S
        try:
            op, poll_attempts = await _retry_transient(
                lambda: client.aio.operations.get(op),
                label="poll",
                on_retry=on_retry,
            )
            poll_retries += poll_attempts
        except Exception as e:
            log.warning(
                "scene gen: poll failed at %ss after %s poll retries: %s",
                elapsed, poll_retries, e,
            )
            raise SceneGenError(
                f"Veo poll failed after {poll_retries} retries: "
                f"{_summarize_veo_error(e)}"
            ) from e

    # Operation finished — surface either an error or extract the video.
    op_error = getattr(op, "error", None)
    if op_error is not None:
        msg = str(getattr(op_error, "message", op_error) or "Veo render failed")
        log.warning("scene gen: operation completed with error: %s", msg)
        raise SceneGenError(f"Veo render failed: {msg}")

    response = getattr(op, "response", None)
    if response is None:
        # Some SDK versions surface the result on .result
        response = getattr(op, "result", None)
    if response is None:
        log.warning("scene gen: operation finished without response")
        raise SceneGenError("Veo finished without a response payload")

    videos = (
        getattr(response, "generated_videos", None)
        or getattr(response, "videos", None)
        or []
    )
    if not videos:
        log.warning("scene gen: no videos in response")
        raise SceneGenError("Veo returned no videos")

    video_obj = videos[0]
    mp4 = await _download_video_bytes(client, video_obj)
    if mp4 is None:
        raise SceneGenError("Veo returned a video reference but bytes could not be extracted")
    log.info(
        "scene gen: complete in %ss (submit_retries=%s, poll_retries=%s)",
        elapsed, submit_retries, poll_retries,
    )
    return mp4


def _summarize_veo_error(exc: Exception) -> str:
    """Produce a short, user-safe summary of a Veo SDK error. Keeps the
    400-style message visible (it's usually actionable: aspect/duration/etc)
    while trimming stack noise. Handles both JSON and Python-repr payloads
    (the SDK formats errors as `400 STATUS. {'error': {'message': ...}}`).
    """
    import ast
    import json

    msg = str(exc)
    if "{" in msg and "message" in msg:
        start = msg.index("{")
        payload_str = msg[start:]
        payload: dict | None = None
        try:
            payload = json.loads(payload_str)
        except (ValueError, TypeError):
            try:
                # SDK errors often come as Python repr (single quotes) which
                # json can't parse — ast.literal_eval handles dict literals.
                payload = ast.literal_eval(payload_str)
            except (ValueError, SyntaxError):
                payload = None
        if isinstance(payload, dict):
            inner = (
                (payload.get("error") or {}).get("message")
                if isinstance(payload.get("error"), dict)
                else None
            ) or payload.get("message")
            if isinstance(inner, str) and inner:
                return inner[:300]
    return msg[:300]


async def _download_video_bytes(
    client: genai.Client, video_obj: Any
) -> bytes | None:
    """Pull mp4 bytes from a Veo result. Different SDK versions expose
    this differently — try the most common shapes."""
    # Direct bytes on the wrapper
    inline = getattr(video_obj, "video_bytes", None) or getattr(
        video_obj, "data", None
    )
    if isinstance(inline, bytes):
        return inline

    # Nested on .video
    nested = getattr(video_obj, "video", None)
    if nested is not None:
        inline = getattr(nested, "video_bytes", None) or getattr(
            nested, "data", None
        )
        if isinstance(inline, bytes):
            return inline

        # Try the files API for a uri-only response
        try:
            blob = await client.aio.files.download(file=nested)
        except Exception as e:
            log.warning("scene gen: files.download failed: %s", e)
            blob = None
        if isinstance(blob, bytes):
            return blob
        if blob is not None:
            data = getattr(blob, "video_bytes", None) or getattr(
                blob, "data", None
            )
            if isinstance(data, bytes):
                return data

    log.warning("scene gen: could not extract mp4 bytes from response")
    return None
