"""Remotion subprocess renderer.

Spawns the standalone Remotion CLI (located at `<repo>/frontend/remotion/`)
with a JSON props blob, captures the rendered MP4, and stores it via the
configured storage provider.

We resolve the Remotion project path from this file's location: walking up
two parents from `app/services/video_gen/renderer.py` lands on the backend
root; the repo root is one level higher; then `frontend/remotion`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

# Pillow lives in requirements.txt — the import is lazy/optional only so an
# install hiccup doesn't crash the renderer entirely. When unavailable we
# fall back to the brand-palette heuristic for caption color picking.
try:
    from PIL import Image  # type: ignore

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover — defensive
    _PIL_AVAILABLE = False
    Image = None  # type: ignore

# Where the standalone Remotion project lives, relative to the backend root.
# `__file__` -> /backend/app/services/video_gen/renderer.py -> ../../../.. = repo
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = _BACKEND_ROOT.parent
REMOTION_DIR = _REPO_ROOT / "frontend" / "remotion"

# Generous timeout — Remotion warm-starts the bundler the first time, so the
# first render of the day can take 60-90s; subsequent ones are faster.
RENDER_TIMEOUT_SEC = 180

REMOTION_ENTRY = "src/index.ts"
COMPOSITION_ID = "MarketingVideo"


class RemotionNotInstalledError(RuntimeError):
    """Raised when the Remotion project / runner isn't available.

    Caller (the API route) maps this to HTTP 503 so the frontend can show
    a helpful error during dev when Agent A hasn't shipped Remotion yet.
    """

    def __init__(self, reason: str, stderr: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.stderr = stderr


def _resolve_runner() -> tuple[str, list[str]] | None:
    """Pick the JS runner that will execute Remotion.

    Tries `bunx` first (the project's preferred runner) and falls back to
    `npx`. Returns (executable, leading_argv) or None if neither is on PATH.
    """
    bun = shutil.which("bun")
    if bun:
        return bun, ["x"]
    npx = shutil.which("npx")
    if npx:
        return npx, []
    return None


def _rewrite_image_url(image_url: str) -> str:
    """Rewrite stored image URLs into something the Remotion subprocess can
    fetch.

    Headless Chromium (Remotion's renderer) BLOCKS file:// reads of arbitrary
    local paths — empirically verified during smoke testing. So we always
    route storage URLs through the running backend's HTTP listener
    (`settings.server_base_url`, default `http://localhost:8000`).

    Absolute http(s) URLs and data: URIs pass through untouched.
    """
    if not image_url:
        return image_url
    if image_url.startswith("data:"):
        return image_url
    if image_url.startswith(("http://", "https://")):
        return image_url
    if image_url.startswith("/api/storage/"):
        base = settings.server_base_url.rstrip("/")
        return f"{base}{image_url}"
    if image_url.startswith("/"):
        # Other absolute paths — assume same backend host.
        base = settings.server_base_url.rstrip("/")
        return f"{base}{image_url}"
    # Anything else — let Remotion try as-is.
    return image_url


def _font_from_identity(identity: dict | None, key: str) -> str | None:
    if not identity:
        return None
    typo = identity.get("typography") or {}
    val = typo.get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    # Some pipelines nest under "fonts".
    fonts = identity.get("fonts") or {}
    val = fonts.get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


# Valid 9-cell focal-zone codes. Anything else falls back to "mc".
_VALID_FOCAL_ZONES = {"tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"}


def _normalize_focal_zone(value: object) -> str:
    """Coerce an arbitrary input to a valid focal_zone code or 'mc'."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _VALID_FOCAL_ZONES:
            return v
    return "mc"


def _derive_caption_motion(style_profile: dict) -> str:
    """Pick a caption-motion variant from the brand's distinctive marks.

    Heuristic priorities:
      - any mark mentioning 'letter' or 'type' → 'letter-by-letter'
      - any mark mentioning 'minimal' or 'calm' → 'fade'
      - else → 'slide-up' (default)
    """
    marks = style_profile.get("distinctive_marks") or []
    if isinstance(marks, list):
        joined = " ".join(str(m).lower() for m in marks)
        if "letter" in joined or "type" in joined:
            return "letter-by-letter"
        if "minimal" in joined or "calm" in joined:
            return "fade"
    return "slide-up"


def _derive_caption_weight(typography: dict) -> int:
    """Read h1_weight from typography, clamp to a sensible heading range."""
    raw = typography.get("h1_weight")
    if isinstance(raw, (int, float)):
        w = int(raw)
        if 400 <= w <= 900:
            return w
    return 700


def _derive_caption_tracking(typography: dict) -> float:
    """Read h1_letter_spacing_em (in em), clamp to [-0.05, 0.05]."""
    raw = typography.get("h1_letter_spacing_em")
    if isinstance(raw, (int, float)):
        val = float(raw)
        if val < -0.05:
            return -0.05
        if val > 0.05:
            return 0.05
        return val
    return -0.01


def _derive_caption_all_caps(style_profile: dict) -> bool:
    """True when typography_feel hints at uppercase / all-caps display."""
    feel = style_profile.get("typography_feel")
    if isinstance(feel, str):
        f = feel.lower()
        if "all caps" in f or "uppercase" in f:
            return True
    return False


# Title-card and end-card durations in milliseconds. Title is shorter (a
# brand hook) and the end card is held longer so the CTA reads cleanly.
TITLE_CARD_DURATION_MS = 1400
END_CARD_DURATION_MS = 2000


# ── Adaptive caption color ────────────────────────────────────────────────
# Default fallbacks. Warm-white is biased for footage that trends mid-to-dark
# (most Veo output). Pure white is used when the caption sits in an unscrim'd
# zone where we want stronger contrast.
_CAPTION_WARM_WHITE = "#fff9ef"
_CAPTION_PURE_WHITE = "#ffffff"
_CAPTION_DARK = "#0b0b0c"


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    """Parse `#rrggbb` or `#rgb` into an (r,g,b) tuple. Returns None on any
    malformed input."""
    if not isinstance(hex_str, str):
        return None
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c + c for c in h)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Perceived luminance in [0, 1]. Not gamma-correct — fast heuristic
    sufficient for picking light vs dark foreground type."""
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _local_storage_path_from_url(url: str) -> Path | None:
    """Reverse the `_rewrite_image_url` mapping for local-storage URLs so we
    can open the PNG with Pillow without an HTTP round-trip. Returns None for
    remote / data: / unknown URLs."""
    if not isinstance(url, str) or not url:
        return None
    base = settings.server_base_url.rstrip("/")
    if url.startswith(base):
        url = url[len(base):]
    if not url.startswith("/api/storage/"):
        return None
    relative = url[len("/api/storage/"):]
    # Defensively strip any query/fragment.
    relative = relative.split("?", 1)[0].split("#", 1)[0]
    storage_root = Path(settings.storage_dir)
    candidate = (storage_root / relative).resolve()
    try:
        candidate.relative_to(storage_root.resolve())
    except ValueError:
        # Path tried to escape the storage dir — refuse.
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _sample_image_luminance(image_url: str | None) -> float | None:
    """Open a stored image, sample the BOTTOM third (caption-band region by
    default), and return mean perceived luminance in [0, 1]. Returns None
    when Pillow is unavailable, the URL is remote, or we can't read.

    We use the bottom third to match the most common caption placement; the
    backend doesn't know per-frame zone here so we pick the prevailing band.
    For top-anchored captions the heuristic still produces a usable answer
    because most footage shares a top/bottom luminance distribution.
    """
    if not _PIL_AVAILABLE or not image_url:
        return None
    path = _local_storage_path_from_url(image_url)
    if path is None:
        return None
    try:
        with Image.open(path) as img:  # type: ignore[union-attr]
            img = img.convert("RGB")
            w, h = img.size
            # Crop the bottom 33% for the dominant caption-band pixels.
            band = img.crop((0, int(h * 0.66), w, h))
            # Aggressive downsample — the mean is what we care about.
            band.thumbnail((64, 64))
            pixels = list(band.getdata())
    except (OSError, ValueError) as e:
        log.debug("caption color sample failed for %s: %s", image_url, e)
        return None

    if not pixels:
        return None
    total = 0.0
    for r, g, b in pixels:
        total += (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return total / len(pixels)


def _palette_luminance_estimate(brand: dict | None) -> float | None:
    """Brand-palette heuristic: average luminance of the first 1-2 palette
    swatches that represent the dominant on-screen color. Returns None if
    nothing usable."""
    if not brand:
        return None
    # Prefer the role-tagged 'background' if set — that's the canonical
    # "what color is the canvas" answer.
    palette_roles = brand.get("palette_roles") or []
    if isinstance(palette_roles, list):
        for entry in palette_roles:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").lower() == "background":
                rgb = _hex_to_rgb(str(entry.get("hex") or ""))
                if rgb:
                    return _luminance(rgb)
    palette_list = brand.get("palette") or []
    if not isinstance(palette_list, list):
        return None
    samples: list[float] = []
    for hex_str in palette_list[:3]:
        rgb = _hex_to_rgb(str(hex_str)) if isinstance(hex_str, str) else None
        if rgb:
            samples.append(_luminance(rgb))
    if not samples:
        return None
    return sum(samples) / len(samples)


def _pick_caption_color(
    frame: dict,
    brand: dict | None,
    *,
    has_scrim: bool,
) -> str:
    """Return a caption color (#hex) tuned to the frame's effective bg.

    Priority of signals:
      1. Live-action image_url — if local + Pillow available, sample pixels.
      2. Brand palette role 'text' — if explicit, use it (subject to the
         dark-on-dark guard below).
      3. Brand palette luminance heuristic.
      4. Default warm white.

    With a scrim under the caption (the bottom-edge gradient
    `from-fg/85`-style overlay), bias toward warm white — the scrim already
    handles dim baseline contrast, and warm white avoids the clinical
    pure-white look.

    Without a scrim (top-anchored caption or design-frame), pick the
    stronger color: pure white on dark bg, near-black on light bg.
    """
    sampled = _sample_image_luminance(frame.get("image_url"))
    if sampled is None:
        sampled = _palette_luminance_estimate(brand)

    # When we have no signal at all, fall back warm-white (works on most
    # mid-to-dark Veo output).
    if sampled is None:
        return _CAPTION_WARM_WHITE if has_scrim else _CAPTION_PURE_WHITE

    # Light bg → dark text is the only way to keep contrast; otherwise we
    # bias by scrim presence.
    if sampled > 0.62:
        # Bright background — use the brand 'text' role if it's actually
        # dark; otherwise the dark default.
        text_role_hex: str | None = None
        for entry in brand.get("palette_roles") or [] if brand else []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").lower() == "text":
                text_role_hex = str(entry.get("hex") or "").strip() or None
                break
        if text_role_hex:
            rgb = _hex_to_rgb(text_role_hex)
            if rgb and _luminance(rgb) < 0.55:
                return text_role_hex
        return _CAPTION_DARK

    # Dark bg branch — prefer brand text role only if it's actually light;
    # otherwise pick warm/pure white based on scrim presence.
    if brand:
        for entry in brand.get("palette_roles") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").lower() == "text":
                hex_str = str(entry.get("hex") or "").strip()
                rgb = _hex_to_rgb(hex_str)
                if rgb and _luminance(rgb) > 0.7:
                    return hex_str
                break
    return _CAPTION_WARM_WHITE if has_scrim else _CAPTION_PURE_WHITE


def build_props(
    aspect: str,
    frames: list[dict],
    brand: dict | None,
    title_card: dict | None = None,
    end_card: dict | None = None,
    transitions: list[dict] | None = None,
) -> dict:
    """Construct the JSON blob handed to Remotion via `--props`.

    Frames are normalized: `clip_url` (Veo mp4, preferred) and `image_url`
    (still fallback) are rewritten to absolute URLs Remotion can resolve.
    Only the fields the compositor needs survive (`clip_url`, `image_url`,
    `caption`, `duration_ms`, `focal_zone`). The Remotion composition
    chooses the Video element when `clip_url` is set; otherwise it falls
    back to Img with `image_url`.

    `transitions` (when supplied) is a list of per-pair decisions of length
    `len(frames) - 1` — see app/services/video_gen/transitions.py. Each
    entry is `{from_id, to_id, style, reason, motion_hint, clip_url}`
    where `clip_url` is non-None only for `style="veo_bridge"`.

    The Remotion MarketingVideo composition consumes this prop directly:
    it interleaves a `BridgeSequence` (OffthreadVideo) for each veo_bridge
    pair and uses per-frame fade-in/fade-out frame counts to honour the
    decisions on the surrounding scenes — `crossfade` keeps the 12-frame
    opacity blend, `match_cut` and `veo_bridge` suppress fades on both
    sides of the pair.
    """
    safe_brand = brand or {}
    palette = safe_brand.get("palette") or []
    palette_roles = safe_brand.get("palette_roles") or []
    identity = safe_brand.get("identity") or {}
    typography = identity.get("typography") if isinstance(identity, dict) else {}
    if not isinstance(typography, dict):
        typography = {}
    style_profile = safe_brand.get("style_profile") or {}
    if not isinstance(style_profile, dict):
        style_profile = {}

    headline_font = _font_from_identity(identity, "headline") or _font_from_identity(
        identity, "heading"
    )
    body_font = _font_from_identity(identity, "body")

    caption_motion = _derive_caption_motion(style_profile)
    caption_weight = _derive_caption_weight(typography)
    caption_tracking_em = _derive_caption_tracking(typography)
    caption_all_caps = _derive_caption_all_caps(style_profile)

    out_frames: list[dict] = []
    for f in frames:
        kind = str(f.get("kind") or "live_action").lower()
        if kind not in ("live_action", "design_sequence"):
            kind = "live_action"
        clip_raw = f.get("clip_url")
        image_raw = f.get("image_url")
        # Effects pass through as-is; Remotion validates kind at render time.
        effects_raw = f.get("effects") or []
        if not isinstance(effects_raw, list):
            effects_raw = []

        entry: dict = {
            "kind": kind,
            "clip_url": _rewrite_image_url(str(clip_raw)) if clip_raw else None,
            "image_url": _rewrite_image_url(str(image_raw)) if image_raw else None,
            "caption": str(f.get("caption") or ""),
            "duration_ms": int(f.get("duration_ms") or 2400),
            "focal_zone": _normalize_focal_zone(f.get("focal_zone")),
            "effects": effects_raw,
        }
        # Adaptive caption color — sample bg luminance per-frame so captions
        # stay legible on mid-to-dark Veo footage. Live-action frames get a
        # bottom-band scrim under the caption, so we bias toward warm-white;
        # design-sequence frames render their own contrast-managed surface,
        # so we pick the stronger color when no scrim is in play.
        has_scrim = kind == "live_action"
        # The sampler uses the rewritten URL for path lookup; pass the dict
        # version so it sees the absolute storage URL.
        entry["caption_color"] = _pick_caption_color(
            {
                "image_url": entry["image_url"],
                "clip_url": entry["clip_url"],
            },
            safe_brand,
            has_scrim=has_scrim,
        )
        if kind == "design_sequence":
            template = f.get("template")
            params = f.get("template_params") if isinstance(f.get("template_params"), dict) else {}
            # If params has an embedded image_url, rewrite to absolute (UiZoom
            # is the main consumer — its background screenshot needs to be
            # reachable from the Remotion subprocess, same as live_action urls).
            if params and isinstance(params.get("image_url"), str):
                params = {**params, "image_url": _rewrite_image_url(params["image_url"])}
            # canvas_kinetic backdrops are stored under videos/{storyboard}/
            # canvases/ — rewrite to absolute so headless Chromium can fetch
            # them, same as image_url and clip_url. canvas_prompt is metadata
            # only (the bytes have already been generated server-side); we
            # leave it untouched.
            if (
                template == "canvas_kinetic"
                and params
                and isinstance(params.get("canvas_url"), str)
            ):
                params = {**params, "canvas_url": _rewrite_image_url(params["canvas_url"])}
            entry["template"] = template
            # Mirror the discriminator inside params so Remotion's
            # SequenceRouter / discriminated union picks the right component.
            entry["params"] = {**(params or {}), "template": template}
        out_frames.append(entry)

    # Title and end card payloads. Both are pure typography rendered by
    # Remotion bookending the Series of clips — no Veo footage needed.
    title_card_out: dict | None = None
    if title_card and isinstance(title_card, dict):
        text = str(title_card.get("text") or "").strip()
        if text:
            title_card_out = {
                "text": text,
                "duration_ms": TITLE_CARD_DURATION_MS,
            }

    end_card_out: dict | None = None
    if end_card and isinstance(end_card, dict):
        headline = str(end_card.get("headline") or "").strip()
        cta = str(end_card.get("cta") or "").strip()
        if headline or cta:
            end_card_out = {
                "headline": headline,
                "cta": cta,
                "duration_ms": END_CARD_DURATION_MS,
            }

    # Normalise transitions — rewrite any veo_bridge clip_url through the
    # same HTTP base as scene clips so Remotion (headless Chromium) can
    # fetch them. Style enum is forwarded as-is; the renderer is the
    # validation point.
    out_transitions: list[dict] = []
    for t in transitions or []:
        if not isinstance(t, dict):
            continue
        clip_raw = t.get("clip_url")
        out_transitions.append(
            {
                "from_id": str(t.get("from_id") or ""),
                "to_id": str(t.get("to_id") or ""),
                "style": str(t.get("style") or "match_cut"),
                "reason": str(t.get("reason") or "")[:300],
                "motion_hint": (
                    str(t.get("motion_hint")) if t.get("motion_hint") else None
                ),
                "clip_url": _rewrite_image_url(str(clip_raw)) if clip_raw else None,
            }
        )

    return {
        "aspect": aspect,
        "brand": {
            "palette": list(palette),
            "palette_roles": list(palette_roles),
            "headline_font": headline_font,
            "body_font": body_font,
            "caption_motion": caption_motion,
            "caption_weight": caption_weight,
            "caption_tracking_em": caption_tracking_em,
            "caption_all_caps": caption_all_caps,
        },
        "frames": out_frames,
        "title_card": title_card_out,
        "end_card": end_card_out,
        "transitions": out_transitions,
    }


async def _run_subprocess(
    runner_exe: str,
    runner_lead: list[str],
    out_path: Path,
    props_json: str,
) -> tuple[int, bytes, bytes]:
    """Run Remotion CLI, returning (returncode, stdout, stderr)."""
    argv = [
        runner_exe,
        *runner_lead,
        "remotion",
        "render",
        REMOTION_ENTRY,
        COMPOSITION_ID,
        str(out_path),
        f"--props={props_json}",
    ]
    log.info("video render: spawning %s in %s", argv[0], REMOTION_DIR)
    env = os.environ.copy()
    # Remotion's renderer is happier with a clean NODE_ENV.
    env.setdefault("NODE_ENV", "production")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(REMOTION_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=RENDER_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(
            f"remotion render exceeded {RENDER_TIMEOUT_SEC}s"
        ) from None
    return (proc.returncode or 0), stdout, stderr


def _stderr_tail(stderr: bytes, max_chars: int = 1200) -> str:
    text = stderr.decode("utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return "...\n" + text[-max_chars:]


async def render_video(props: dict[str, Any]) -> tuple[bytes, int]:
    """Run Remotion and return (mp4_bytes, total_duration_ms).

    Raises:
        RemotionNotInstalledError: Remotion project missing or no runner on PATH.
        RuntimeError: render failed (non-zero exit) — `args[0]` is stderr tail.
    """
    if not REMOTION_DIR.exists():
        raise RemotionNotInstalledError(
            f"remotion project not found at {REMOTION_DIR}"
        )

    runner = _resolve_runner()
    if runner is None:
        raise RemotionNotInstalledError(
            "neither 'bun' nor 'npx' found on PATH"
        )
    runner_exe, runner_lead = runner

    total_duration_ms = sum(int(f.get("duration_ms") or 0) for f in props.get("frames", []))

    props_json = json.dumps(props, ensure_ascii=False)

    with tempfile.TemporaryDirectory(prefix="bautopilot_render_") as tmp:
        out_path = Path(tmp) / "out.mp4"
        try:
            rc, stdout, stderr = await _run_subprocess(
                runner_exe, runner_lead, out_path, props_json
            )
        except FileNotFoundError as e:
            raise RemotionNotInstalledError(
                f"runner exec failed: {e}"
            ) from e

        if rc != 0:
            tail = _stderr_tail(stderr)
            log.warning("remotion render failed rc=%s tail=%s", rc, tail[-400:])
            # If Remotion's bundler can't find the entry, surface as not-installed
            # so the caller returns 503 (more useful than 500).
            tail_lc = tail.lower()
            if (
                "cannot find module" in tail_lc
                or "no such file" in tail_lc
                or "enoent" in tail_lc
            ) and ("remotion" in tail_lc or "src/index" in tail_lc):
                raise RemotionNotInstalledError(
                    "remotion project incomplete", stderr=tail
                )
            raise RuntimeError(tail or "remotion render failed")

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError("remotion produced no output file")

        return out_path.read_bytes(), total_duration_ms
