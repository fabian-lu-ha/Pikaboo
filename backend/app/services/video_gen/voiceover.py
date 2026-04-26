"""Voiceover layer for the marketing-video surface.

Two-stage pipeline that runs *after* Remotion has rendered the silent mp4:

  1. Gemini TTS reads the planner-authored script with a built-in voice
     (Charon, Kore, Puck, ...) and a `voice_persona` style directive
     prepended as a prefix instruction. Returns 24kHz PCM mono.
  2. ffmpeg muxes the WAV-wrapped TTS audio onto the rendered mp4. The
     result is a sibling artifact — the silent original stays in storage so
     the user can compare or fall back.

The TTS model is configurable via `settings.gemini_tts_model` so we can
follow the preview model lineage without code changes.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

log = logging.getLogger(__name__)

_client: genai.Client | None = None

# Gemini TTS native sample rate is 24kHz mono PCM 16-bit. We never resample
# — ffmpeg re-encodes to AAC at mux time and matching the source rate is
# always cheaper than touching the samples.
TTS_SAMPLE_RATE_HZ = 24_000
TTS_SAMPLE_WIDTH_BYTES = 2  # 16-bit
TTS_CHANNELS = 1


class VoiceoverGenError(RuntimeError):
    """Raised when voiceover gen or muxing fails. Message is user-safe."""


def _get_client() -> genai.Client | None:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            return None
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _build_tts_prompt(script: str, voice_persona: str) -> str:
    """Embed the persona as a Gemini-TTS style directive.

    Gemini TTS treats text before the first colon as a control instruction
    ("Say cheerfully: ...") and reads only what follows. Stripping any colons
    out of the script itself prevents it from being interpreted as a second
    directive boundary.
    """
    persona = (voice_persona or "").strip()
    clean = (script or "").strip().replace(":", ",")
    if persona:
        return f"Say {persona}: {clean}"
    return clean


def _extract_audio_bytes(response: Any) -> bytes | None:
    """Pull the first inline audio part from a Gemini response."""
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
            if data and ("audio" in mime or mime.startswith("audio/")):
                return data
    return None


def _pcm_to_wav(
    pcm: bytes,
    sample_rate: int = TTS_SAMPLE_RATE_HZ,
    channels: int = TTS_CHANNELS,
    sample_width: int = TTS_SAMPLE_WIDTH_BYTES,
) -> bytes:
    """Wrap raw PCM in a minimal WAV container so ffmpeg can read it."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def generate_tts_audio(
    script: str,
    voice_persona: str,
    voice_name: str,
) -> bytes:
    """Render the script to a WAV blob via Gemini TTS.

    Raises VoiceoverGenError on any failure path (no API key, empty script,
    no audio in response, SDK error). The returned bytes are a complete WAV
    file ready to feed into ffmpeg.
    """
    if not script.strip():
        raise VoiceoverGenError("voiceover script is empty")

    client = _get_client()
    if client is None:
        raise VoiceoverGenError("GEMINI_API_KEY is not configured")

    prompt = _build_tts_prompt(script, voice_persona)

    try:
        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name,
                )
            )
        )
    except (AttributeError, TypeError) as e:
        raise VoiceoverGenError(f"TTS SDK shape mismatch: {e}") from e

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
    )

    log.info(
        "voiceover gen: model=%s voice=%s persona=%r words=%s",
        settings.gemini_tts_model,
        voice_name,
        (voice_persona or "")[:60],
        len(script.split()),
    )
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_tts_model,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        log.warning("voiceover gen: API call failed: %s", e)
        raise VoiceoverGenError(f"Gemini TTS call failed: {e}") from e

    pcm = _extract_audio_bytes(response)
    if pcm is None:
        raise VoiceoverGenError("Gemini TTS returned no audio part")

    return _pcm_to_wav(pcm)


async def mux_audio_into_video(
    video_bytes: bytes,
    audio_bytes: bytes,
) -> bytes:
    """Combine the rendered mp4 with the TTS WAV via ffmpeg.

    Encodes audio to AAC at 192k (mp4-friendly) and copies the video stream
    so we don't re-encode it.

    Output duration always equals the VIDEO duration:
      - If the voiceover is shorter, we apad the audio with silence so we
        don't truncate the visuals (the original `-shortest` flag did the
        wrong thing here — Gemini TTS read times vary and shorter-than-
        video narrations would have stolen seconds of footage).
      - If the voiceover is longer, `-shortest` (driven by the padded but
        video-length-bounded streams below) trims the trailing audio.

    `apad` pads the audio stream indefinitely with silence; combined with
    `-shortest`, the output ends when the video ends.
    """
    with TemporaryDirectory(prefix="voiceover_") as td:
        tdp = Path(td)
        v = tdp / "in.mp4"
        a = tdp / "in.wav"
        o = tdp / "out.mp4"
        v.write_bytes(video_bytes)
        a.write_bytes(audio_bytes)

        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-i", str(v),
            "-i", str(a),
            "-filter_complex", "[1:a]apad[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(o),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            tail = (stderr or b"").decode("utf-8", errors="replace")[-800:]
            raise VoiceoverGenError(f"ffmpeg mux failed: {tail or 'unknown'}")
        if not o.exists():
            raise VoiceoverGenError("ffmpeg produced no output")
        return o.read_bytes()


# ---------------------------------------------------------------------------
# Per-touch campaign voice+video render
# ---------------------------------------------------------------------------
#
# Distinct from the Remotion-mux pipeline above. This is the on-demand path
# the 1:1 campaign storyboard calls when the user clicks Play on a video
# touch: render the per-customer voiceover for that touch and persist a
# ``VideoRender`` row keyed by ``(customer_id:campaign_id:touch_id)`` so
# re-clicks return the cached artifact rather than burning another TTS call.
#
# Falls back to the default Gemini voice (``settings.gemini_tts_default_voice``
# if defined, else "Charon") when the brand's fine-tuned voice model isn't
# ready. Never blocks on the voice-finetune workstream.

import os
from sqlalchemy.orm import Session

from app.db import models
from app.events.bus import bus
from app.events.types import Events


_VOICEOVER_CACHE_DIR = Path(
    os.environ.get("VOICEOVER_CACHE_DIR")
    or "/tmp/brand_autopilot_voiceovers"
)


def _default_voice_name() -> str:
    return getattr(settings, "gemini_tts_default_voice", None) or "Charon"


def _cache_key(customer_id: str, campaign_id: str, touch_id: str) -> str:
    return f"{customer_id}:{campaign_id}:{touch_id}"


def _ensure_cache_dir() -> Path:
    _VOICEOVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _VOICEOVER_CACHE_DIR


def _serialize_render(row: "models.VideoRender") -> dict:
    return {
        "render_id": row.id,
        "cache_key": row.cache_key,
        "voice_model_id": row.voice_model_id,
        "audio_url": row.audio_url,
        "video_url": row.video_url,
        "status": row.status,
        "error": row.error,
        "script_text": row.script_text,
    }


async def render_for_touch(db: Session, touch_id: str) -> dict:
    """Render (or return cached) voice+video artifact for one campaign touch.

    Idempotent: identical ``(customer_id, campaign_id, touch_id)`` triples
    return the same row. Voiceover-only renders (no muxed mp4) are still
    valid output — ``video_url`` is None when no base video template exists
    for the touch yet, but ``audio_url`` is always set on success.
    """
    touch = db.get(models.CampaignTouch, touch_id)
    if touch is None:
        raise ValueError(f"campaign_touch {touch_id} not found")
    if touch.kind != "video":
        raise ValueError(
            f"touch {touch_id} kind={touch.kind!r}, only video touches "
            "render here"
        )

    campaign = db.get(models.Campaign, touch.campaign_id)
    if campaign is None:
        raise ValueError(f"campaign {touch.campaign_id} not found")
    if campaign.target_kind != "customer":
        raise ValueError(
            "render_for_touch only supports customer-target campaigns; "
            "segment campaigns use templated copy with merge tags."
        )
    customer_id = campaign.target_id
    customer = db.get(models.Customer, customer_id)
    if customer is None:
        raise ValueError(f"customer {customer_id} not found")
    brand = db.get(models.Brand, campaign.brand_id)
    if brand is None:
        raise ValueError(f"brand {campaign.brand_id} not found")

    cache_key = _cache_key(customer_id, campaign.id, touch.id)

    existing = (
        db.query(models.VideoRender)
        .filter(models.VideoRender.cache_key == cache_key)
        .one_or_none()
    )
    if existing is not None and existing.status == "ready":
        return _serialize_render(existing)
    if existing is not None and existing.status == "rendering":
        return _serialize_render(existing)

    script_text = str(
        (touch.content_json or {}).get("voiceover_script") or ""
    ).strip()
    if not script_text:
        raise ValueError(
            f"touch {touch_id} has no voiceover_script in content_json"
        )

    # Voice selection: brand fine-tune wins if ready, else default Gemini voice.
    voice_ready = (
        brand.voice_model_status == "ready"
        and bool(brand.voice_model_id)
    )
    voice_model_id = brand.voice_model_id if voice_ready else None
    voice_name = (
        brand.voice_model_id
        if voice_ready
        else _default_voice_name()
    )
    voice_persona = (
        (brand.voice_profile or {}).get("tone")
        or "warmly and conversationally"
    )

    if existing is None:
        row = models.VideoRender(
            brand_id=brand.id,
            customer_id=customer_id,
            campaign_id=campaign.id,
            touch_id=touch.id,
            cache_key=cache_key,
            voice_model_id=voice_model_id,
            script_text=script_text,
            status="rendering",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    else:
        row = existing
        row.status = "rendering"
        row.error = None
        row.voice_model_id = voice_model_id
        row.script_text = script_text
        db.commit()
        db.refresh(row)

    bus.emit(
        Events.CAMPAIGN_VIDEO_RENDERING,
        {
            "brand_id": brand.id,
            "campaign_id": campaign.id,
            "touch_id": touch.id,
            "render_id": row.id,
            "cache_key": cache_key,
            "voice_model_id": voice_model_id,
        },
    )

    try:
        wav_bytes = await generate_tts_audio(
            script=script_text,
            voice_persona=voice_persona,
            voice_name=voice_name,
        )
    except VoiceoverGenError as e:
        row.status = "failed"
        row.error = str(e)
        db.commit()
        bus.emit(
            Events.CAMPAIGN_VIDEO_RENDER_FAILED,
            {
                "brand_id": brand.id,
                "campaign_id": campaign.id,
                "touch_id": touch.id,
                "render_id": row.id,
                "error": str(e),
            },
        )
        return _serialize_render(row)

    cache_dir = _ensure_cache_dir()
    audio_path = cache_dir / f"{cache_key}.wav"
    audio_path.write_bytes(wav_bytes)
    audio_url = f"file://{audio_path}"

    # Base-video mux is left for a later milestone — once a per-brand or per-
    # touch base template exists we'll call mux_audio_into_video here. For
    # now the audio-only artifact is a complete output the storyboard can
    # play through an <audio> element.
    video_url: str | None = None

    row.audio_url = audio_url
    row.video_url = video_url
    row.status = "ready"
    db.commit()
    db.refresh(row)

    bus.emit(
        Events.CAMPAIGN_VIDEO_RENDERED,
        {
            "brand_id": brand.id,
            "campaign_id": campaign.id,
            "touch_id": touch.id,
            "render_id": row.id,
            "cache_key": cache_key,
            "voice_model_id": voice_model_id,
            "audio_url": audio_url,
            "video_url": video_url,
        },
    )

    # Stamp the cache key on the touch so the API's serializer surfaces it.
    if touch.render_cache_key != cache_key:
        touch.render_cache_key = cache_key
        db.commit()

    return _serialize_render(row)
