"""AI-decided inter-scene transitions for the marketing-video composer.

Two surfaces:

  - ``plan_transitions(scenes, brand, cinematic_brief)``: an LLM editor decides
    one of {"veo_bridge", "match_cut", "crossfade"} for each adjacent scene
    pair. Most pairs should land on match_cut — that's how Apple/W+K cut.
  - ``render_transition_clip(...)``: when the planner says veo_bridge, this
    fires Veo's first-and-last-frame-to-video and returns a 4s mp4 URL the
    Remotion compositor can interleave between the two scene clips.

Architectural notes:
  * We reuse scene_gen's hardened Veo plumbing (negative prompt, retry
    helper, error summarizer, client init) instead of forking it. The Veo
    503/504 retry policy is identical — bridges share the same backend
    pressure as scenes.
  * For v1 the LLM gets text-only context (per-scene prompt + motion +
    last-shot description). Extracting actual frames per pair to send to
    the planner is overkill — six text descriptions are cheaper and the
    decision quality holds.
  * Bridges always render at the cheapest tier (``settings.veo_fast_model``)
    — they're 4s of decorative interpolation, not hero shots.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from base64 import b64decode
from pathlib import Path
from typing import Any, Literal

from google.genai import types

from app.config import settings
from app.providers.factory import get_storage
from app.services.llm.client import chat_json
from app.services.video_gen.scene_gen import (
    DEFAULT_DURATION_S,  # noqa: F401  (kept for callers that read defaults)
    POLL_INTERVAL_S,
    POLL_TIMEOUT_S,
    RetryCallback,
    SceneGenError,
    _NEGATIVE_PROMPT,
    _POSITIVE_DISCIPLINE,
    _retry_transient,
    _summarize_veo_error,
    get_veo_client,
)

log = logging.getLogger(__name__)

TransitionStyle = Literal["veo_bridge", "match_cut", "crossfade"]
VALID_STYLES: tuple[str, ...] = ("veo_bridge", "match_cut", "crossfade")
DEFAULT_STYLE: TransitionStyle = "match_cut"

# Bridges are short by design — interpolate, don't tell a story.
TRANSITION_DURATION_S = 4

# Veo natively renders 16:9 / 9:16; downstream cropper handles 1:1.
_VEO_NATIVE_ASPECTS: tuple[str, ...] = ("16:9", "9:16")

# Default motion prompt when the LLM doesn't supply one. Generic enough that
# Veo just smoothly interpolates between the two locked frames.
_DEFAULT_MOTION_HINT = (
    "Smooth, intentional motion bridge — interpolate naturally from the "
    "first frame to the last frame, preserving subject identity and lighting"
)

# ── ffmpeg helpers ────────────────────────────────────────────────────────


def _resolve_local_mp4_path(mp4_url: str) -> Path | None:
    """Map an /api/storage/... URL (or a fully-qualified one with our
    server_base_url prefix) onto the local backend storage_dir.

    Bridges are only meaningful in local mode for now — Supabase storage
    requires a download round-trip we haven't wired in. Returns None when
    we can't resolve to a local file.
    """
    if not mp4_url:
        return None
    base = settings.server_base_url.rstrip("/")
    rel: str | None = None
    if mp4_url.startswith("/api/storage/"):
        rel = mp4_url.removeprefix("/api/storage/")
    elif mp4_url.startswith(f"{base}/api/storage/"):
        rel = mp4_url.removeprefix(f"{base}/api/storage/")
    elif mp4_url.startswith("http://") or mp4_url.startswith("https://"):
        # Fully-qualified URL we don't recognise — out of scope for v1.
        return None
    else:
        rel = mp4_url

    if settings.deploy_mode != "local":
        return None
    p = Path(settings.storage_dir) / rel
    if not p.exists() or not p.is_file():
        return None
    return p


# Veo-emitted mp4s vary in keyframe density — a 40ms seek before EOF lands
# in a P-frame gap on some renders, producing an empty output. We try a
# small window first (cheap when it works) and widen to capture a real
# keyframe on misses. The actual extracted frame is still the last decoded
# frame in the seek window — i.e. very close to true EOF.
_SSEOF_LADDER_S: tuple[float, ...] = (0.04, 0.5, 1.5, 3.0)


async def _extract_last_frame(mp4_url: str, out_path: Path) -> Path | None:
    """Extract the LAST frame of an mp4 as a PNG via ffmpeg.

    Walks a ladder of ``-sseof`` values from tight (-40ms) to loose (-3s)
    so we still get a frame even when the mp4's keyframe density is sparse.
    Each rung re-runs ffmpeg with a slightly earlier seek anchor; the
    decoder still walks forward from there to the end of the file, so the
    extracted frame is always near-EOF in practice.

    Returns the PNG path on success, or None when every rung fails (the
    caller should downgrade the bridge decision to ``match_cut``).
    """
    src = _resolve_local_mp4_path(mp4_url)
    if src is None:
        log.info("transitions: cannot resolve mp4 to local path: %s", mp4_url)
        return None
    last_tail = ""
    last_rc: int | None = None
    for sseof in _SSEOF_LADDER_S:
        # Wipe any previous-rung empty output so the size check is meaningful.
        try:
            if out_path.exists():
                out_path.unlink()
        except OSError:
            pass
        cmd = [
            "/opt/homebrew/bin/ffmpeg",
            "-y",
            "-sseof",
            f"-{sseof}",
            "-i",
            str(src),
            "-update",
            "1",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        except FileNotFoundError as e:
            log.warning("transitions: ffmpeg not on PATH: %s", e)
            return None
        except asyncio.TimeoutError:
            log.warning(
                "transitions: ffmpeg extraction timed out (sseof=%s) for %s",
                sseof, mp4_url,
            )
            continue
        last_rc = proc.returncode
        last_tail = stderr.decode("utf-8", errors="replace")[-400:]
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return out_path
    log.warning(
        "transitions: ffmpeg extract gave up after %s rungs rc=%s tail=%s",
        len(_SSEOF_LADDER_S), last_rc, last_tail,
    )
    return None


# ── image loading (mirrors scene_gen._load_asset_bytes) ───────────────────


def _load_image_for_veo(url: str) -> tuple[bytes, str] | None:
    """Resolve a stored image URL (or data URI) to (bytes, mime).

    Same shape and behaviour as scene_gen._load_asset_bytes — kept local
    so transitions doesn't grow a back-channel into scene_gen's privates."""
    if not url:
        return None
    if url.startswith("data:"):
        try:
            head, b64 = url.split(",", 1)
            mime = head.split(";")[0].removeprefix("data:") or "image/png"
            return b64decode(b64), mime
        except Exception:
            return None

    base = settings.server_base_url.rstrip("/")
    rel: str | None = None
    if url.startswith("/api/storage/"):
        rel = url.removeprefix("/api/storage/")
    elif url.startswith(f"{base}/api/storage/"):
        rel = url.removeprefix(f"{base}/api/storage/")
    if rel is None:
        return None
    if settings.deploy_mode != "local":
        return None
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


def _bytes_to_veo_image(data: bytes, mime: str) -> Any | None:
    """Wrap raw bytes into a types.Image (or Part fallback) for Veo."""
    try:
        return types.Image(image_bytes=data, mime_type=mime)
    except (AttributeError, TypeError):
        try:
            return types.Part.from_bytes(data=data, mime_type=mime)
        except Exception:
            return None


# ── LLM planner ───────────────────────────────────────────────────────────


_PLANNER_SYSTEM = (
    "You are a film editor planning transitions for a 6-scene marketing "
    "video. For each adjacent pair (i, i+1), decide ONE of:\n"
    "  - \"veo_bridge\": insert a 4s motion clip that interpolates from "
    "scene i's last frame to scene i+1's first frame. Use ONLY when the "
    "two frames share a clear motion path (same subject moving across, "
    "same setting, related objects). Provide motion_hint describing what "
    "should move.\n"
    "  - \"match_cut\": hard cut, no transition. Use for INTENTIONAL cuts "
    "— different subject, different setting, time jumps. This is what 70% "
    "of Apple/Wieden+Kennedy commercials use.\n"
    "  - \"crossfade\": soft 12-frame opacity blend. Use for similar mood "
    "or palette pairs that don't share motion.\n"
    "Be a strict editor — most pairs should be match_cut. veo_bridge ONLY "
    "when it adds real continuity value.\n\n"
    "Output JSON: "
    "{\"transitions\": ["
    "{\"from_id\": \"...\", \"to_id\": \"...\", \"style\": \"...\", "
    "\"reason\": \"...\", \"motion_hint\": \"...\"}, ..."
    "]} with EXACTLY len(scenes)-1 entries in input order."
)

# Documentation-only — chat_json is invoked with force_no_schema=True so
# this schema is not sent to Gemini 3 Pro (whose stricter validator rejects
# slightly oddball schemas). Kept here as a human-readable contract.
_PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "transitions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_id": {"type": "string"},
                    "to_id": {"type": "string"},
                    "style": {"type": "string", "enum": list(VALID_STYLES)},
                    "reason": {"type": "string"},
                    "motion_hint": {"type": "string"},
                },
                "required": ["from_id", "to_id", "style"],
            },
        },
    },
    "required": ["transitions"],
}


def _format_scene_summary(idx: int, scene: dict) -> str:
    """One-line-ish text description per scene for the planner. Avoid
    dumping URLs — those waste tokens; the planner cares about content."""
    fid = scene.get("frame_id") or scene.get("id") or f"scene_{idx}"
    prompt = (scene.get("prompt") or scene.get("scene_prompt") or "").strip()
    motion = (scene.get("motion") or "").strip()
    caption = (scene.get("caption") or "").strip()
    parts = [f"Scene {idx} [id={fid}]"]
    if caption:
        parts.append(f"caption: \"{caption[:120]}\"")
    if prompt:
        parts.append(f"prompt: {prompt[:400]}")
    if motion:
        parts.append(f"motion: {motion[:240]}")
    return " | ".join(parts)


def _build_planner_user_message(
    scenes: list[dict],
    brand: dict,
    cinematic_brief: dict,
) -> str:
    name = (brand or {}).get("name") or "the brand"
    mood = (((brand or {}).get("style_profile") or {}).get("mood")) or ""
    pacing = (cinematic_brief or {}).get("pacing") or ""
    refs = (cinematic_brief or {}).get("reference_films") or ""

    header_lines = [
        f"Brand: {name}",
    ]
    if mood:
        header_lines.append(f"Brand mood: {mood[:200]}")
    if pacing:
        header_lines.append(f"Director's pacing: {pacing[:200]}")
    if refs:
        header_lines.append(f"Reference films: {refs[:240]}")

    scene_lines = [
        _format_scene_summary(i, s) for i, s in enumerate(scenes)
    ]

    pair_lines: list[str] = []
    for i in range(len(scenes) - 1):
        a = scenes[i]
        b = scenes[i + 1]
        a_id = a.get("frame_id") or a.get("id") or f"scene_{i}"
        b_id = b.get("frame_id") or b.get("id") or f"scene_{i + 1}"
        pair_lines.append(f"  - pair {i}: from_id={a_id} → to_id={b_id}")

    return (
        "\n".join(header_lines)
        + "\n\nScenes (in order):\n"
        + "\n".join(scene_lines)
        + f"\n\nDecide a transition for each of the {len(scenes) - 1} "
        + "adjacent pairs. Use the from_id/to_id values exactly as listed:\n"
        + "\n".join(pair_lines)
        + "\n\nReturn JSON in the documented shape."
    )


def _coerce_decision(
    raw: dict,
    fallback_from: str,
    fallback_to: str,
) -> dict:
    """Normalise one LLM decision into the public dict shape. Anything we
    can't make sense of falls back to a safe ``match_cut`` — bad LLM output
    should never break the render."""
    style = str(raw.get("style") or "").strip().lower()
    if style not in VALID_STYLES:
        log.info(
            "transitions: unknown style %r in decision; falling back to %s",
            style, DEFAULT_STYLE,
        )
        style = DEFAULT_STYLE

    from_id = str(raw.get("from_id") or fallback_from)
    to_id = str(raw.get("to_id") or fallback_to)
    reason = str(raw.get("reason") or "").strip()
    motion_hint_raw = raw.get("motion_hint")
    motion_hint = (
        str(motion_hint_raw).strip() if isinstance(motion_hint_raw, str) else None
    )
    if style == "veo_bridge" and not motion_hint:
        # The planner skipped the hint — synthesise a generic one rather
        # than downgrading to match_cut. Veo will still get an image-pair
        # to interpolate, just without specific direction.
        motion_hint = _DEFAULT_MOTION_HINT
    return {
        "from_id": from_id,
        "to_id": to_id,
        "style": style,
        "reason": reason,
        "motion_hint": motion_hint,
    }


async def plan_transitions(
    scenes: list[dict],
    brand: dict,
    cinematic_brief: dict,
) -> list[dict]:
    """Decide one transition per adjacent scene pair.

    Returns ``len(scenes) - 1`` dicts, each shaped like:
      ``{"from_id": str, "to_id": str, "style": "veo_bridge"|"match_cut"|
        "crossfade", "reason": str, "motion_hint": str | None}``

    For 0 or 1 scene we return an empty list. On LLM failure we degrade to
    all-match_cut (the safe default) — a render with no fancy transitions
    is still a render; failing the whole pipeline because the planner
    hiccuped would be a bad UX trade.
    """
    if not scenes or len(scenes) < 2:
        return []

    # Pre-compute fallback ids per pair so we can emit a fully-shaped
    # response even when the LLM round-trip fails.
    pair_ids: list[tuple[str, str]] = []
    for i in range(len(scenes) - 1):
        a = scenes[i]
        b = scenes[i + 1]
        pair_ids.append(
            (
                str(a.get("frame_id") or a.get("id") or f"scene_{i}"),
                str(b.get("frame_id") or b.get("id") or f"scene_{i + 1}"),
            )
        )

    user_msg = _build_planner_user_message(scenes, brand or {}, cinematic_brief or {})
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    try:
        raw = await chat_json(
            messages,
            schema=_PLANNER_SCHEMA,
            model=settings.gemini_planning_model,
            force_no_schema=True,
        )
    except Exception as e:
        log.warning(
            "transitions: planner LLM failed (%s) — defaulting to all match_cut",
            e,
        )
        return [
            {
                "from_id": fa,
                "to_id": fb,
                "style": DEFAULT_STYLE,
                "reason": f"planner unavailable: {e}",
                "motion_hint": None,
            }
            for fa, fb in pair_ids
        ]

    items_raw = raw.get("transitions") if isinstance(raw, dict) else None
    if not isinstance(items_raw, list):
        log.warning(
            "transitions: planner returned non-list payload (%s) — defaulting",
            type(items_raw).__name__,
        )
        items_raw = []

    decisions: list[dict] = []
    for i, (fa, fb) in enumerate(pair_ids):
        item = items_raw[i] if i < len(items_raw) and isinstance(items_raw[i], dict) else {}
        decisions.append(_coerce_decision(item, fa, fb))

    # Force the from/to ids to align with the actual pair order even if the
    # LLM scrambled them. Reasoning: the LLM's free-text reason can drift,
    # but the pair indices are non-negotiable.
    aligned: list[dict] = []
    for i, ((fa, fb), d) in enumerate(zip(pair_ids, decisions)):
        aligned.append({**d, "from_id": fa, "to_id": fb})

    log.info(
        "transitions: planned %s pairs, styles=%s",
        len(aligned),
        json.dumps([d["style"] for d in aligned]),
    )
    return aligned


# ── Veo bridge renderer ───────────────────────────────────────────────────


def _resolve_aspect(aspect: str | None) -> str:
    if aspect in _VEO_NATIVE_ASPECTS:
        return aspect  # type: ignore[return-value]
    return "9:16"


async def _download_video_bytes(client: Any, video_obj: Any) -> bytes | None:
    """Same extraction shape as scene_gen._download_video_bytes — duplicated
    here to avoid expanding scene_gen's public surface for one helper."""
    inline = getattr(video_obj, "video_bytes", None) or getattr(
        video_obj, "data", None
    )
    if isinstance(inline, bytes):
        return inline

    nested = getattr(video_obj, "video", None)
    if nested is not None:
        inline = getattr(nested, "video_bytes", None) or getattr(
            nested, "data", None
        )
        if isinstance(inline, bytes):
            return inline
        try:
            blob = await client.aio.files.download(file=nested)
        except Exception as e:
            log.warning("transitions: files.download failed: %s", e)
            blob = None
        if isinstance(blob, bytes):
            return blob
        if blob is not None:
            data = getattr(blob, "video_bytes", None) or getattr(
                blob, "data", None
            )
            if isinstance(data, bytes):
                return data
    return None


async def render_transition_clip(
    from_frame_url: str,
    to_frame_url: str,
    motion_hint: str,
    brand: dict,
    storyboard_id: str,
    pair_id: str,
    on_retry: RetryCallback | None = None,
    aspect: str = "9:16",
) -> str:
    """Generate a 4s Veo bridge clip via first-and-last-frame-to-video.

    Stores the clip as ``videos/{storyboard_id}/transitions/{pair_id}.mp4``
    and returns the storage URL the renderer can hand to Remotion.

    Raises SceneGenError on any unrecoverable failure — caller is expected
    to catch and downgrade the decision to ``match_cut`` rather than
    failing the whole render.
    """
    if not from_frame_url or not to_frame_url:
        raise SceneGenError("transition requires both from_frame_url and to_frame_url")

    client = get_veo_client()
    if client is None:
        raise SceneGenError("GEMINI_API_KEY is not configured")

    first_loaded = _load_image_for_veo(from_frame_url)
    last_loaded = _load_image_for_veo(to_frame_url)
    if first_loaded is None or last_loaded is None:
        raise SceneGenError(
            "transition frame images could not be loaded "
            f"(from={bool(first_loaded)}, to={bool(last_loaded)})"
        )

    first_image = _bytes_to_veo_image(*first_loaded)
    last_image = _bytes_to_veo_image(*last_loaded)
    if first_image is None or last_image is None:
        raise SceneGenError("transition images could not be wrapped for Veo")

    aspect_resolved = _resolve_aspect(aspect)

    # Veo first/last config. negative_prompt is gated by model — Veo 3.0
    # accepts it, Veo 3.1 preview variants (incl. lite which we use for
    # bridges by default) reject with HTTP 400. See
    # scene_gen._model_supports_negative_prompt.
    from app.services.video_gen.scene_gen import _model_supports_negative_prompt
    config_kwargs: dict[str, Any] = {
        "aspect_ratio": aspect_resolved,
        "duration_seconds": TRANSITION_DURATION_S,
        "number_of_videos": 1,
        "last_frame": last_image,
    }
    if _model_supports_negative_prompt(settings.veo_fast_model):
        config_kwargs["negative_prompt"] = _NEGATIVE_PROMPT
    config = types.GenerateVideosConfig(**config_kwargs)

    prompt = (motion_hint or "").strip() or _DEFAULT_MOTION_HINT
    brand_name = (brand or {}).get("name") or "the brand"
    full_prompt = (
        f"4-second motion bridge between two locked frames in a {brand_name} "
        f"marketing video. {prompt}. Preserve subject identity, lighting, "
        f"and palette across the whole clip — no new people, props, or "
        f"scenery beyond what's visible in the first and last frames. "
        f"{_POSITIVE_DISCIPLINE}"
    )

    submit_kwargs: dict[str, Any] = {
        "model": settings.veo_fast_model,
        "prompt": full_prompt,
        "image": first_image,
        "config": config,
    }

    log.info(
        "transitions: bridge submit storyboard=%s pair=%s aspect=%s",
        storyboard_id, pair_id, aspect_resolved,
    )

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
            "transitions: bridge submit failed after %s retries: %s",
            submit_retries, e,
        )
        raise SceneGenError(
            f"{_summarize_veo_error(e)} (after {submit_retries} retries)"
        ) from e

    while not getattr(op, "done", False):
        if elapsed >= POLL_TIMEOUT_S:
            raise SceneGenError(
                f"Veo bridge exceeded {POLL_TIMEOUT_S}s timeout "
                f"(after {submit_retries} submit retries, "
                f"{poll_retries} poll retries)"
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
            raise SceneGenError(
                f"Veo bridge poll failed after {poll_retries} retries: "
                f"{_summarize_veo_error(e)}"
            ) from e

    op_error = getattr(op, "error", None)
    if op_error is not None:
        msg = str(getattr(op_error, "message", op_error) or "Veo bridge failed")
        raise SceneGenError(f"Veo bridge failed: {msg}")

    response = getattr(op, "response", None) or getattr(op, "result", None)
    if response is None:
        raise SceneGenError("Veo bridge finished without a response payload")

    videos = (
        getattr(response, "generated_videos", None)
        or getattr(response, "videos", None)
        or []
    )
    if not videos:
        raise SceneGenError("Veo bridge returned no videos")

    mp4 = await _download_video_bytes(client, videos[0])
    if mp4 is None:
        raise SceneGenError("Veo bridge returned a video reference but bytes could not be extracted")

    key = f"videos/{storyboard_id}/transitions/{pair_id}.mp4"
    storage = get_storage()
    await storage.put(key, mp4, "video/mp4")
    url = await storage.get_url(key)
    log.info(
        "transitions: bridge complete storyboard=%s pair=%s elapsed=%ss",
        storyboard_id, pair_id, elapsed,
    )
    return url


# ── helpers exposed for the API route ─────────────────────────────────────


async def extract_last_frame_to_storage(
    mp4_url: str,
    storyboard_id: str,
    frame_label: str,
) -> str | None:
    """Convenience: extract the last frame of an mp4 and persist it to
    storage so we can pass an HTTP URL to render_transition_clip without
    plumbing raw bytes through the API layer.

    Returns the storage URL, or None if extraction failed (caller should
    skip the bridge and downgrade to match_cut).
    """
    if not mp4_url:
        return None
    with tempfile.TemporaryDirectory(prefix="bautopilot_lastframe_") as tmp:
        out = Path(tmp) / "last.png"
        got = await _extract_last_frame(mp4_url, out)
        if got is None:
            return None
        try:
            data = out.read_bytes()
        except OSError:
            return None
    if not data:
        return None
    key = f"videos/{storyboard_id}/transitions/{frame_label}_last.png"
    storage = get_storage()
    await storage.put(key, data, "image/png")
    return await storage.get_url(key)
