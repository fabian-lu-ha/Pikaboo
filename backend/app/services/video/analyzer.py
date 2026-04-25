"""Video downloader + Gemini analyzer.

For every Post that *looks like* a short-form video (TikTok always, YouTube
Shorts/watch, Instagram Reels), we:

  1. Download the underlying mp4 via yt-dlp into a temp file (sync library —
     wrapped in `asyncio.to_thread`).
  2. Send the file to `gemini-3-flash-preview` with a structured-output
     prompt. Inline `Part.from_bytes` for <20MB; File API otherwise. Gemini
     natively transcribes audio + samples frames at 1 fps, so a single call
     yields both the transcript and visual analysis (no separate
     screenshot/frame-extract step needed).
  3. Return a populated `VideoAnalysis`. Any failure → log warning + return
     `None`. We never raise on this best-effort path.

Caps (per project constraints):
  - At most ONE analysis call per video.
  - Skip videos longer than `MAX_DURATION_SECONDS` (probe duration first; if
    yt-dlp can't tell us the duration up front we still cap output via the
    prompt, but we don't trim the file).
  - Caller (orchestrator) is responsible for capping how many posts per
    brand we run through `attach_analysis` (5 max per brand).

Public surface used by `app.services.onboarding.orchestrator`:
  - `is_video_post(post) -> bool`
  - `analyze_post(post) -> VideoAnalysis | None`
  - `attach_analysis(post) -> Post`   (mutates + returns)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from google import genai
from google.genai import types

from app.config import settings
from app.services.social import Post

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tunables
# ──────────────────────────────────────────────────────────────────────────────
MAX_DURATION_SECONDS = 60
INLINE_MAX_BYTES = 20 * 1024 * 1024  # Gemini docs: <20MB → inline; ≥ → File API.
DOWNLOAD_TIMEOUT_SECONDS = 60
GEMINI_TIMEOUT_SECONDS = 90
FILES_API_POLL_INTERVAL = 2.0
FILES_API_POLL_BUDGET = 60.0

# yt-dlp format selector: prefer ≤720p mp4 to keep payloads small + uniform.
_YTDLP_FORMAT = "mp4[height<=720]/best[height<=720]/best"

# Video-bearing URL patterns. We err on the side of "yes, try it" because
# yt-dlp will simply fail and we'll log + return None — no hard cost.
_VIDEO_HOSTS = (
    "tiktok.com",
    "vm.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "instagram.com",
    "www.instagram.com",
)
_IG_VIDEO_PATH_RE = re.compile(r"^/(reel|reels|tv)/", re.IGNORECASE)
_YT_VIDEO_PATH_RE = re.compile(r"^/(shorts/|watch$|watch/)", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# Public dataclass
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class VideoAnalysis:
    transcript: str
    key_moments: list[dict] = field(default_factory=list)
    visual_summary: str = ""
    content_summary: str = ""
    style_observations: list[str] = field(default_factory=list)
    duration_seconds: float | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────────
def is_video_post(post: Post) -> bool:
    """Heuristic: does this post have a fetchable video?

    Decision rules:
      - tiktok platform → always yes (every public post is a video).
      - youtube platform → always yes (we only fetch videos there).
      - instagram with `/reel/` or `/tv/` URL → yes; `/p/` URLs may be image
        carousels — we still say yes and let yt-dlp confirm/deny, because
        IG sometimes serves video posts under `/p/` shortcodes.
      - any URL whose host is in `_VIDEO_HOSTS` and whose path matches a
        known video pattern → yes.
      - anything else → no.
    """
    if post is None or not post.url:
        return False

    platform = (post.platform or "").lower()
    if platform == "tiktok":
        return True
    if platform == "youtube":
        return True

    try:
        parsed = urlparse(post.url)
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    if host not in _VIDEO_HOSTS:
        return False

    path = parsed.path or "/"

    if "youtube" in host or host == "youtu.be":
        if host == "youtu.be":
            return True
        return bool(_YT_VIDEO_PATH_RE.match(path)) or path.startswith("/shorts/")

    if "instagram" in host:
        return bool(_IG_VIDEO_PATH_RE.match(path)) or path.startswith("/p/")

    if "tiktok" in host:
        return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# yt-dlp download (sync — must run in a thread)
# ──────────────────────────────────────────────────────────────────────────────
def _ytdlp_download_sync(url: str, target_dir: str) -> tuple[str, dict] | None:
    """Download `url` to `target_dir` with yt-dlp. Returns (path, info) or None."""
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as e:
        log.warning("video analyze: yt-dlp not installed: %s", e)
        return None

    out_template = os.path.join(target_dir, "video.%(ext)s")
    opts: dict[str, Any] = {
        "format": _YTDLP_FORMAT,
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "retries": 1,
        "fragment_retries": 1,
        "socket_timeout": DOWNLOAD_TIMEOUT_SECONDS,
        # Skip live streams / DRM / age-gated content gracefully.
        "skip_download_archive": True,
        # Keep the audio track (we need it for transcription).
        "keepvideo": False,
        # Reasonable client identification — TikTok/IG sometimes 403 the default UA.
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None

            # Duration cap — skip long videos to keep Gemini cost bounded.
            duration = info.get("duration")
            if isinstance(duration, (int, float)) and duration > MAX_DURATION_SECONDS:
                log.info(
                    "video analyze: skipping %s (duration %.0fs > %ds cap)",
                    url, duration, MAX_DURATION_SECONDS,
                )
                return None

            # Resolve actual on-disk path. yt-dlp's prepare_filename returns
            # the pre-postprocessor path; for mp4 selectors that's the final
            # file. If a postprocessor extension swap happened (rare with our
            # selector), fall back to scanning the directory.
            path = ydl.prepare_filename(info)
            if not path or not os.path.exists(path):
                files = [
                    os.path.join(target_dir, n)
                    for n in os.listdir(target_dir)
                    if not n.startswith(".")
                ]
                if not files:
                    return None
                path = max(files, key=os.path.getsize)

            return path, info
    except DownloadError as e:
        log.warning("video analyze: yt-dlp DownloadError for %s: %s", url, e)
        return None
    except Exception as e:
        log.warning("video analyze: yt-dlp unexpected error for %s: %s", url, e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Gemini call
# ──────────────────────────────────────────────────────────────────────────────
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "transcript": {
            "type": "string",
            "description": (
                "Clean transcript of the spoken audio. Empty string if there "
                "is no spoken audio (e.g. music-only video)."
            ),
        },
        "key_moments": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "timestamp_seconds": {"type": "number"},
                    "description": {"type": "string"},
                },
                "required": ["timestamp_seconds", "description"],
            },
        },
        "visual_summary": {
            "type": "string",
            "description": "One sentence describing what is visually shown.",
        },
        "content_summary": {
            "type": "string",
            "description": "One sentence describing what the video is about.",
        },
        "style_observations": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {"type": "string"},
        },
    },
    "required": [
        "transcript",
        "key_moments",
        "visual_summary",
        "content_summary",
        "style_observations",
    ],
}


def _build_prompt(post: Post) -> str:
    caption = (post.caption or "").strip().replace("\n", " ")
    if len(caption) > 400:
        caption = caption[:400] + "…"
    platform = post.platform or "social"
    return (
        f"You are a video content analyst for a brand-marketing AI. "
        f"Given this short-form video post (caption: \"{caption}\", "
        f"platform: \"{platform}\"), return strictly a JSON object matching "
        f"the response schema with:\n"
        f"  - transcript: a clean transcript of the spoken audio "
        f"(empty string if no speech).\n"
        f"  - key_moments: 3-5 key visual moments with their timestamps in "
        f"seconds (floats), each with a short description.\n"
        f"  - visual_summary: one sentence describing what is visually shown.\n"
        f"  - content_summary: one sentence describing what the video is about.\n"
        f"  - style_observations: 3-5 short observations about camera, pacing, "
        f"lighting, set, on-screen text, and recurring motifs. Be specific.\n"
        f"If the video is unclear, return short generic strings rather than refusing."
    )


_genai_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _genai_client = genai.Client(api_key=settings.gemini_api_key)
    return _genai_client


def _strip_additional_properties(schema: Any) -> Any:
    """Same pattern as app.services.llm.client — Gemini response_schema rejects
    `additionalProperties`."""
    if isinstance(schema, dict):
        return {
            k: _strip_additional_properties(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_strip_additional_properties(item) for item in schema]
    return schema


async def _wait_for_file_active(client: genai.Client, name: str) -> bool:
    """Poll the File API until the uploaded video transitions out of PROCESSING."""
    deadline = time.monotonic() + FILES_API_POLL_BUDGET
    while time.monotonic() < deadline:
        try:
            f = await client.aio.files.get(name=name)
        except Exception as e:
            log.warning("video analyze: files.get(%s) failed: %s", name, e)
            return False
        state = getattr(f, "state", None)
        state_name = getattr(state, "name", str(state) if state else "")
        if state_name == "ACTIVE":
            return True
        if state_name == "FAILED":
            log.warning("video analyze: file %s entered FAILED state", name)
            return False
        await asyncio.sleep(FILES_API_POLL_INTERVAL)
    log.warning("video analyze: file %s never reached ACTIVE within budget", name)
    return False


async def _gemini_analyze(
    path: str, post: Post, duration_seconds: float | None
) -> VideoAnalysis | None:
    try:
        client = _get_client()
    except RuntimeError as e:
        log.warning("video analyze: %s", e)
        return None

    prompt = _build_prompt(post)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_strip_additional_properties(_RESPONSE_SCHEMA),
    )

    try:
        size = os.path.getsize(path)
    except OSError as e:
        log.warning("video analyze: stat %s failed: %s", path, e)
        return None

    uploaded_name: str | None = None
    try:
        if size < INLINE_MAX_BYTES:
            with open(path, "rb") as f:
                video_bytes = f.read()
            video_part = types.Part.from_bytes(
                data=video_bytes, mime_type="video/mp4"
            )
            contents: list[Any] = [video_part, prompt]
        else:
            uploaded = await client.aio.files.upload(
                file=path,
                config=types.UploadFileConfig(mime_type="video/mp4"),
            )
            uploaded_name = getattr(uploaded, "name", None)
            if uploaded_name and not await _wait_for_file_active(
                client, uploaded_name
            ):
                return None
            contents = [uploaded, prompt]

        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=contents,
                config=config,
            ),
            timeout=GEMINI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning("video analyze: Gemini call timed out for %s", post.url)
        return None
    except Exception as e:
        log.warning("video analyze: Gemini call failed for %s: %s", post.url, e)
        return None
    finally:
        if uploaded_name:
            try:
                await client.aio.files.delete(name=uploaded_name)
            except Exception as e:
                log.debug(
                    "video analyze: failed to delete uploaded file %s: %s",
                    uploaded_name, e,
                )

    raw = getattr(response, "text", None)
    if not raw:
        log.warning("video analyze: empty Gemini response for %s", post.url)
        return None

    try:
        import json
        data = json.loads(raw)
    except Exception as e:
        log.warning("video analyze: bad JSON from Gemini for %s: %s", post.url, e)
        return None

    return _to_analysis(data, duration_seconds)


def _to_analysis(data: dict, duration_seconds: float | None) -> VideoAnalysis:
    """Coerce loose model output into the strict dataclass shape."""
    transcript = data.get("transcript") or ""
    if not isinstance(transcript, str):
        transcript = str(transcript)

    raw_moments = data.get("key_moments") or []
    moments: list[dict] = []
    if isinstance(raw_moments, list):
        for m in raw_moments:
            if not isinstance(m, dict):
                continue
            ts = m.get("timestamp_seconds")
            try:
                ts_f = float(ts) if ts is not None else 0.0
            except (TypeError, ValueError):
                ts_f = 0.0
            desc = m.get("description") or ""
            if not isinstance(desc, str):
                desc = str(desc)
            moments.append({"timestamp_seconds": ts_f, "description": desc})

    visual = data.get("visual_summary") or ""
    if not isinstance(visual, str):
        visual = str(visual)

    content = data.get("content_summary") or ""
    if not isinstance(content, str):
        content = str(content)

    raw_style = data.get("style_observations") or []
    style: list[str] = []
    if isinstance(raw_style, list):
        for s in raw_style:
            if isinstance(s, str) and s.strip():
                style.append(s.strip())

    return VideoAnalysis(
        transcript=transcript,
        key_moments=moments,
        visual_summary=visual,
        content_summary=content,
        style_observations=style,
        duration_seconds=duration_seconds,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public entrypoints
# ──────────────────────────────────────────────────────────────────────────────
async def analyze_post(post: Post) -> VideoAnalysis | None:
    """Analyze a single video post end-to-end.

    Returns `None` on any non-fatal failure (not a video, download blocked,
    duration over cap, Gemini error, etc). Never raises.
    """
    if not is_video_post(post):
        return None
    if not post.url:
        return None

    tmpdir: tempfile.TemporaryDirectory | None = None
    try:
        tmpdir = tempfile.TemporaryDirectory(prefix="brand_autopilot_video_")
        result = await asyncio.to_thread(
            _ytdlp_download_sync, post.url, tmpdir.name
        )
        if result is None:
            return None
        path, info = result

        # Re-check size after download — the format selector might have
        # picked something larger than expected.
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -1
        if size <= 0:
            log.warning("video analyze: empty download for %s", post.url)
            return None

        duration = info.get("duration") if isinstance(info, dict) else None
        duration_seconds = (
            float(duration) if isinstance(duration, (int, float)) else None
        )

        return await _gemini_analyze(path, post, duration_seconds)
    except Exception as e:
        # Final safety net — best-effort.
        log.warning("video analyze: unexpected error for %s: %s", post.url, e)
        return None
    finally:
        if tmpdir is not None:
            try:
                tmpdir.cleanup()
            except Exception as e:
                log.debug("video analyze: temp cleanup failed: %s", e)


async def attach_analysis(post: Post) -> Post:
    """Run `analyze_post` and mutate `post.video_analysis` in place.

    Designed for use with `asyncio.gather`:

        posts = await asyncio.gather(*(attach_analysis(p) for p in posts))
    """
    try:
        result = await analyze_post(post)
    except Exception as e:
        log.warning("video analyze: attach_analysis swallowed %s: %s", post.url, e)
        result = None
    if result is not None:
        post.video_analysis = asdict(result)
    return post
