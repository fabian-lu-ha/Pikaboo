"""Multimodal Gemini critic for the marketing-video composer.

Closes the v1 → v2 improvement loop. After Remotion produces a render,
this module:

  1. Extracts six evenly-spaced thumbnails from the rendered mp4 via
     ffmpeg (best-effort — degrades to text-only on extraction failure).
  2. Builds a multimodal Gemini call with the thumbnails as inline
     base64 images plus the storyboard JSON as text.
  3. Returns a structured plan: a list of weaknesses + a list of
     concrete mutations the UI can present as approve-or-reject
     checkboxes.

The plan is intentionally PLAN-ONLY — this module never mutates the
storyboard. The user picks which mutations to apply; the improver
module then materialises v2.

The cost classifier lives here (in code, not LLM) so the UI can show a
reliable "free / 30s render / 90s veo" badge per mutation regardless of
how the model phrased the target string.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from google.genai import types

from app.config import settings
from app.services.video_gen.scene_gen import get_veo_client

log = logging.getLogger(__name__)

# Six thumbnails balances signal vs token cost — at 360p each, six images
# are ~150-250KB total inline base64, well inside Gemini's vision budget.
_THUMBNAIL_COUNT = 6
# Tight ffmpeg timeout per thumbnail — we'd rather render a partial set
# than block the API call for ~minutes when ffmpeg goes weird.
_FFMPEG_TIMEOUT_S = 8

_FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
_FFPROBE_BIN = "/opt/homebrew/bin/ffprobe"


_SYSTEM_PROMPT = (
    "You are a senior film editor reviewing a marketing video draft. Be "
    "ruthless. Point out concrete failures: invisible captions, weak hooks, "
    "jarring cuts, on-screen text artifacts, hand-puppet anatomy, motion "
    "that signals AI generation, shots that don't sell the product, "
    "captions that fight the visual, transitions that break the rhythm. "
    "Each weakness gets exactly one mutation that fixes it. Be specific: "
    "name frame ids and transition pair ids; propose concrete prop "
    "changes (a hex color, a re-written prompt sentence, a motion verb). "
    "Output 3-7 weaknesses in priority order. Severity is 'high' for "
    "anything a viewer would notice in the first 2 seconds, 'medium' for "
    "anything that makes the video feel less premium, 'low' for polish "
    "items. Respond with valid JSON matching the requested shape exactly.\n\n"
    "STRUCTURAL CHANGES — when the storyboard's narrative arc is weak, propose\n"
    "restructuring, not just tweaking:\n\n"
    "  - frames.add: insert a missing beat. Common reasons: no hook frame\n"
    "    before the first product shot; no climax punctuation between the\n"
    "    proof and the CTA; pacing too monotone (insert a graphic\n"
    "    design_sequence beat to break up live-action). When inserting, give\n"
    "    the full frame spec — kind, prompt (or template+params for design),\n"
    "    caption, duration_ms.\n"
    "  - frames.remove: delete a frame that doesn't earn its place. If a\n"
    "    frame's content duplicates a neighbor, doesn't advance the narrative,\n"
    "    or is filler, REMOVE IT.\n"
    "  - frames.reorder: move a frame to where it belongs in the arc.\n"
    "  - frame.X.kind: swap a flat live_action shot for a design_sequence\n"
    "    (cheap graphic beat) when the live shot doesn't add visual interest.\n"
    "  - transition.X_Y.style → \"veo_bridge\": upgrade hard cuts to motion\n"
    "    bridges when the two frames share a clear motion path (chip closeup\n"
    "    → wide shot of MacBook with that chip; runner mid-stride → finish\n"
    "    line). Veo bridges are expensive but transformative.\n\n"
    "RUBRIC: for every mutation you propose, ask yourself — does this make a\n"
    "NOTICEABLE difference, or is it cosmetic? If 80%+ of your mutations are\n"
    "cosmetic (caption color, effect zone, small prompt tweaks), you're not\n"
    "being bold enough. The user will re-render — give them changes worth\n"
    "re-rendering for. Don't be precious about the existing storyboard."
)


# Mutation-cost classifier. The LLM is good at proposing what to change
# but unreliable at estimating cost; we own that mapping in code so the
# UI shows a stable badge per mutation.
def _classify_mutation_cost(
    target: str, mutation: dict | None = None
) -> tuple[str, int]:
    """Return (cost, estimated_seconds) for a mutation target string.

    Cost taxonomy:
      - "free": pure prop edit on the storyboard JSON. Re-render needed,
        but no LLM/Veo cost. Render ~30s.
      - "render": pure Remotion re-render (transition style flip without a
        Veo bridge). Same timing as free — the distinction is mostly
        semantic for the user.
      - "veo": frame.X.prompt / frame.X.motion changed, OR a structural
        change introduced a new live_action frame, OR a transition was
        upgraded to "veo_bridge". ~60-90s per Veo call; the API runs them
        in parallel + a final ~30s Remotion re-render.

    `mutation` is the full mutation dict (id, target, from, to, ...). We
    inspect `mutation.to` for branching rules — frames.add cost flips on
    `to.kind`, frame.X.kind cost flips on `to`, and transition.X_Y.style
    cost flips on `to` ("veo_bridge" is expensive, the others are cheap).
    """
    t = (target or "").strip().lower()
    parts = t.split(".")
    leaf = parts[-1] if parts else ""

    # ── structural frame ops ────────────────────────────────────────────
    # `frames.add` cost depends on the kind of frame being inserted:
    # live_action → "veo" (~90s for the Veo clip); design_sequence →
    # "free" (just a Remotion re-render, no model call).
    if t == "frames.add":
        spec = (mutation or {}).get("to") if mutation else None
        kind = ""
        if isinstance(spec, dict):
            kind = str(spec.get("kind") or "live_action").strip().lower()
        if kind == "design_sequence":
            return "free", 30
        return "veo", 90
    # `frames.remove` and `frames.reorder` are pure list edits — Remotion
    # re-renders the existing clips without re-firing anything.
    if t in ("frames.remove", "frames.reorder"):
        return "free", 30

    # `frame.X.kind` swap: live_action → design = free (no Veo); the
    # opposite swap → veo. The leaf is "kind" with parts = [frame, X, kind].
    if t.startswith("frame.") and leaf == "kind":
        new_kind_raw = (mutation or {}).get("to") if mutation else None
        new_kind = str(new_kind_raw or "").strip().lower()
        if new_kind == "design_sequence":
            return "free", 30
        # Default + live_action → must re-fire Veo for the new shot.
        return "veo", 90

    # Pure free prop edits — caption / focal zone / duration / template.
    if t.startswith("frame.") and (
        leaf == "caption"
        or leaf == "caption_color"
        or leaf == "caption_text"
        or leaf == "focal_zone"
        or leaf == "duration_ms"
        or "caption_color" in t
    ):
        return "free", 30
    # Template swap is a free edit (Remotion picks a different component).
    if t.startswith("frame.") and leaf == "template":
        return "free", 30
    # Template params are pure prop changes — Remotion re-renders only.
    if ".template_params" in t:
        return "free", 30
    # Effects array — pure prop change. Includes the array-op grammar
    # (frame.X.effects.add / frame.X.effects.remove) and per-index sub-paths
    # (frame.X.effects[i].params.zone, frame.X.effects[i].duration_ms, etc).
    if ".effects" in t or ".effects[" in t:
        return "free", 30
    # Transitions: a flip to "veo_bridge" costs ~60s (a 4s Veo bridge clip).
    # Flips to "match_cut" or "crossfade" are pure render-side edits.
    if t.startswith("transition.") and ".style" in t:
        new_style = ""
        if mutation is not None:
            new_style = str(mutation.get("to") or "").strip().lower()
        if new_style == "veo_bridge":
            return "veo", 60
        return "render", 30
    # Anything that re-prompts Veo. The default for unknown targets falls
    # here too — safer to over-estimate cost than to under-charge.
    if t.startswith("frame.") and (".prompt" in t or ".motion" in t):
        return "veo", 90
    # Unknown target — assume veo to stay honest about the worst case.
    return "veo", 90


# ── ffmpeg thumbnail extraction ───────────────────────────────────────────


def _resolve_local_mp4_path(video_url: str) -> Path | None:
    """Map a /api/storage/... URL onto a local file. Mirrors the helper
    in transitions.py so we stay consistent."""
    if not video_url:
        return None
    base = settings.server_base_url.rstrip("/")
    rel: str | None = None
    if video_url.startswith("/api/storage/"):
        rel = video_url.removeprefix("/api/storage/")
    elif video_url.startswith(f"{base}/api/storage/"):
        rel = video_url.removeprefix(f"{base}/api/storage/")
    elif video_url.startswith(("http://", "https://")):
        return None
    else:
        rel = video_url
    if settings.deploy_mode != "local":
        return None
    if rel is None:
        return None
    p = Path(settings.storage_dir) / rel
    if not p.exists() or not p.is_file():
        return None
    return p


async def _probe_duration_s(path: Path) -> float | None:
    """Use ffprobe to read mp4 duration in seconds. None on failure."""
    cmd = [
        _FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except (FileNotFoundError, asyncio.TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return None


async def _extract_thumbnail(
    path: Path, timestamp_s: float, out_path: Path
) -> Path | None:
    """Extract a single frame at `timestamp_s`. Returns the path or None."""
    cmd = [
        _FFMPEG_BIN,
        "-y",
        "-ss",
        f"{timestamp_s:.2f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        # Cap output to 720px wide so we don't blow Gemini's image budget.
        "-vf",
        "scale='min(720,iw)':-2",
        str(out_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT_S)
    except (FileNotFoundError, asyncio.TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    if not out_path.exists() or out_path.stat().st_size == 0:
        return None
    return out_path


async def _extract_thumbnails(video_url: str) -> list[bytes]:
    """Extract `_THUMBNAIL_COUNT` evenly-spaced thumbnails from the video.

    Returns the JPEG bytes for each thumbnail in temporal order. Empty
    list when the video can't be located, ffmpeg isn't on PATH, or every
    extraction fails — the caller degrades gracefully.
    """
    src = _resolve_local_mp4_path(video_url)
    if src is None:
        log.info(
            "critic: cannot resolve video to local path: %s — degrading to "
            "text-only critic",
            video_url,
        )
        return []
    duration_s = await _probe_duration_s(src)
    if duration_s is None or duration_s <= 0.5:
        log.info(
            "critic: ffprobe could not determine duration (or video too "
            "short) — degrading to text-only critic"
        )
        return []

    # Evenly-spaced timestamps. Skip the very first/last 0.1s so we don't
    # land on black frames if the editor clips with a fade.
    margin = min(0.1, duration_s * 0.05)
    span = duration_s - 2 * margin
    if span <= 0:
        return []
    timestamps = [
        margin + (span * i / (_THUMBNAIL_COUNT - 1))
        for i in range(_THUMBNAIL_COUNT)
    ]

    thumbs: list[bytes] = []
    with tempfile.TemporaryDirectory(prefix="critic_thumbs_") as tmp:
        out_dir = Path(tmp)
        for i, ts in enumerate(timestamps):
            out = out_dir / f"thumb_{i}.jpg"
            got = await _extract_thumbnail(src, ts, out)
            if got is None:
                continue
            try:
                thumbs.append(got.read_bytes())
            except OSError:
                continue
    return thumbs


# ── multimodal Gemini call ────────────────────────────────────────────────


def _shape_storyboard_for_critic(
    storyboard_id: str, frames: list[dict]
) -> str:
    """Compact JSON view of the frames that the critic actually needs to
    reason about. Strips long URLs (the model can't browse them anyway)
    while keeping captions, prompts, motion, focal zone, and effects."""
    summary: list[dict] = []
    for f in frames:
        if not isinstance(f, dict):
            continue
        summary.append(
            {
                "id": f.get("id"),
                "kind": f.get("kind", "live_action"),
                "prompt": (f.get("prompt") or "")[:600],
                "motion": (f.get("motion") or "")[:240],
                "caption": (f.get("caption") or "")[:200],
                "duration_ms": f.get("duration_ms"),
                "focal_zone": f.get("focal_zone", "mc"),
                "has_clip": bool(f.get("clip_url")),
                "has_keyframe": bool(f.get("image_url")),
                "template": f.get("template"),
                "template_params": f.get("template_params"),
                "effects": [
                    {"id": e.get("id"), "kind": e.get("kind"), "params": e.get("params") or {}}
                    for e in (f.get("effects") or [])
                    if isinstance(e, dict)
                ],
            }
        )
    return json.dumps(
        {"storyboard_id": storyboard_id, "frames": summary},
        ensure_ascii=False,
        indent=None,
    )


def _user_prompt(thumbs_count: int, frames_count: int) -> str:
    """Build the user-message portion of the multimodal call.

    Documents both the in-place mutation grammar AND the structural
    grammar (frames.add / frames.remove / frames.reorder / frame.X.kind /
    transition.X_Y.style → veo_bridge) so Gemini emits actionable targets
    when the narrative arc — not just the polish — needs work.
    """
    return (
        f"Here is a marketing video draft you must critique. The first "
        f"{thumbs_count} attachments are evenly-spaced thumbnails from the "
        f"rendered mp4 (in temporal order). After the images, the storyboard "
        f"JSON describes the {frames_count} frames that produced these "
        f"thumbnails. Read both, then output your critique strictly in this "
        f"JSON shape:\n\n"
        "{\n"
        "  \"summary\": \"1-2 sentence overall take\",\n"
        "  \"weaknesses\": [\n"
        "    {\n"
        "      \"id\": \"w0\",\n"
        "      \"frame_id\": \"f3\" | null,\n"
        "      \"transition\": \"f3_f4\" | null,\n"
        "      \"issue\": \"concrete failure description\",\n"
        "      \"severity\": \"high\" | \"medium\" | \"low\",\n"
        "      \"category\": \"contrast\" | \"cut\" | \"motion\" | "
        "\"composition\" | \"pacing\" | \"narrative\" | \"consistency\"\n"
        "    }\n"
        "  ],\n"
        "  \"mutations\": [\n"
        "    {\n"
        "      \"id\": \"m0\",\n"
        "      \"weakness_ids\": [\"w0\"],\n"
        "      \"target\": <one of the targets below>,\n"
        "      \"from\": <current value, OR an index/id ref for structural ops>,\n"
        "      \"to\": <proposed value, OR a frame spec for frames.add>,\n"
        "      \"reason\": \"one sentence justification\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "MUTATION TARGET GRAMMAR — pick one per mutation:\n\n"
        "IN-PLACE EDITS (tune an existing frame):\n"
        "  - frame.<id>.caption          — string\n"
        "  - frame.<id>.caption_color    — hex string (\"#0a0a0a\")\n"
        "  - frame.<id>.focal_zone       — tl|tc|tr|ml|mc|mr|bl|bc|br\n"
        "  - frame.<id>.duration_ms      — int\n"
        "  - frame.<id>.prompt           — full Veo prompt (re-fires Veo)\n"
        "  - frame.<id>.motion           — motion verb (re-fires Veo)\n"
        "  - frame.<id>.template         — design template name\n"
        "  - frame.<id>.template_params.<key> — sub-prop on design template\n"
        "  - frame.<id>.effects[i].params.<sub> — effects-array tweak\n"
        "  - frame.<id>.effects.add / .remove   — effects-array op\n"
        "  - transition.<from_id>_<to_id>.style — \"match_cut\" | "
        "\"crossfade\" | \"veo_bridge\"\n\n"
        "STRUCTURAL OPS (reshape the timeline):\n"
        "  - frames.add  — insert a brand-new frame.\n"
        "      `to` MUST be a full frame spec: {kind: \"live_action\" | "
        "\"design_sequence\", prompt, motion?, caption, duration_ms, "
        "focal_zone?, cast_refs?, effects?, template?, template_params?}.\n"
        "      `from` is the insertion location: an integer index, or "
        "{after: \"<existing frame id>\"}, or {before: \"<id>\"}. "
        "Omit `from` to append at the end.\n"
        "      Use this when the narrative is missing a beat — a hook before "
        "the first product shot, a climax between proof and CTA, or a "
        "graphic design_sequence to break up monotone live-action.\n"
        "  - frames.remove — delete a frame that doesn't earn its place.\n"
        "      `from` is an int index OR {id: \"<frame id>\"}. `to` is null.\n"
        "      Use when a shot duplicates a neighbor or is pure filler.\n"
        "  - frames.reorder — move a frame to a different position.\n"
        "      `from` is {id: \"<frame id>\"} (or current index); `to` is "
        "the destination index, or {after: \"<id>\"}, or {before: \"<id>\"}.\n"
        "  - frame.<id>.kind — swap a frame's pathway between live_action "
        "and design_sequence. `to` is the new kind. When swapping to "
        "live_action, pair this with a frame.<id>.prompt mutation that "
        "supplies the Veo prompt; when swapping to design_sequence, pair "
        "with frame.<id>.template and frame.<id>.template_params.<key>.\n"
        "  - transition.<from_id>_<to_id>.style → \"veo_bridge\" — generate "
        "a 4s Veo motion bridge between two adjacent frames. Use sparingly "
        "and only when the two frames share an obvious motion path (chip "
        "closeup → wide shot of laptop holding that chip; mid-stride runner "
        "→ finish line). Bridges are expensive but transformative.\n\n"
        "Each mutation MUST address one or more weaknesses by id. Mutation "
        "IDs must be stable strings like 'm0', 'm1' (the user picks a subset "
        "by id). Order weaknesses by severity desc, then by frame index. "
        "Cite exact frame ids — never invent ones not present in the "
        "EFFECTS JSON below."
    )


def _empty_plan(reason: str) -> dict:
    """Structured-but-empty plan returned when the multimodal call fails
    so the API surface always has a stable shape."""
    return {
        "summary": f"Critic unavailable: {reason}",
        "weaknesses": [],
        "mutations": [],
        "error": reason,
    }


def _post_process_plan(plan: dict, frames: list[dict]) -> dict:
    """Normalise plan shape, attach cost tags, dedupe mutation IDs.

    The LLM is mostly compliant but we don't trust it — every mutation
    gets a code-classified cost so the UI badge is reliable.
    """
    summary = (plan.get("summary") or "").strip() or "No summary."

    # Frames keyed by id for "from" value lookup when the LLM omitted it.
    frames_by_id = {f.get("id"): f for f in frames if isinstance(f, dict)}

    weaknesses_in = plan.get("weaknesses") or []
    weaknesses_out: list[dict] = []
    seen_w_ids: set[str] = set()
    for i, w in enumerate(weaknesses_in):
        if not isinstance(w, dict):
            continue
        wid = (w.get("id") or "").strip() or f"w{i}"
        if wid in seen_w_ids:
            wid = f"w{i}_{len(seen_w_ids)}"
        seen_w_ids.add(wid)
        sev = (w.get("severity") or "medium").strip().lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        cat = (w.get("category") or "composition").strip().lower()
        if cat not in (
            "contrast",
            "cut",
            "motion",
            "composition",
            "pacing",
            "narrative",
            "consistency",
        ):
            cat = "composition"
        weaknesses_out.append(
            {
                "id": wid,
                "frame_id": w.get("frame_id"),
                "transition": w.get("transition"),
                "issue": (w.get("issue") or "").strip()[:600],
                "severity": sev,
                "category": cat,
            }
        )

    mutations_in = plan.get("mutations") or []
    mutations_out: list[dict] = []
    seen_m_ids: set[str] = set()
    valid_w_ids = {w["id"] for w in weaknesses_out}
    for i, m in enumerate(mutations_in):
        if not isinstance(m, dict):
            continue
        mid = (m.get("id") or "").strip() or f"m{i}"
        if mid in seen_m_ids:
            mid = f"m{i}_{len(seen_m_ids)}"
        seen_m_ids.add(mid)
        target = (m.get("target") or "").strip()
        if not target:
            # Skip mutations with no target — they're not actionable.
            continue
        # Filter weakness_ids to known ones only.
        wids_in = m.get("weakness_ids") or []
        wids_filtered = [
            str(x) for x in wids_in if isinstance(x, str) and x in valid_w_ids
        ]
        cost, est_s = _classify_mutation_cost(target, m)
        # Try to backfill `from` from the storyboard if the LLM didn't
        # supply it — purely for UI display, never used for the actual
        # apply.
        from_val = m.get("from")
        if from_val is None:
            from_val = _lookup_from(target, frames_by_id)
        mutations_out.append(
            {
                "id": mid,
                "weakness_ids": wids_filtered,
                "target": target,
                "from": from_val,
                "to": m.get("to"),
                "reason": (m.get("reason") or "").strip()[:400],
                "cost": cost,
                "estimated_seconds": est_s,
            }
        )

    return {
        "summary": summary[:600],
        "weaknesses": weaknesses_out,
        "mutations": mutations_out,
    }


def _lookup_from(target: str, frames_by_id: dict) -> Any:
    """Best-effort lookup of a target's current value for UI display."""
    parts = target.split(".")
    if len(parts) < 3 or parts[0] != "frame":
        return None
    fid = parts[1]
    frame = frames_by_id.get(fid)
    if not frame:
        return None
    cursor: Any = frame
    for key in parts[2:]:
        if isinstance(cursor, dict):
            cursor = cursor.get(key)
        else:
            return None
        if cursor is None:
            return None
    return cursor


async def critique_video(
    storyboard_id: str,
    video_url: str,
    frames: list[dict],
) -> dict:
    """Multimodal Gemini review of the rendered video.

    Returns a plan dict with `summary`, `weaknesses`, and `mutations`.
    Failures (ffmpeg unavailable, no Gemini key, multimodal error) all
    return a structured empty plan with an `error` key set rather than
    raising — the caller is the API route that needs to give the user
    SOMETHING back.
    """
    storyboard_summary = _shape_storyboard_for_critic(storyboard_id, frames)

    # Step 1: extract thumbnails. Best-effort.
    thumbs: list[bytes] = []
    try:
        thumbs = await _extract_thumbnails(video_url)
    except Exception as e:
        log.warning("critic: thumbnail extraction crashed: %s", e)
        thumbs = []

    # Step 2: build multimodal Gemini call.
    client = get_veo_client()
    if client is None:
        return _empty_plan("GEMINI_API_KEY is not configured")

    # Compose the user message: thumbnails as inline base64 image parts
    # followed by the storyboard JSON as text. We follow the SDK's
    # types.Content / types.Part pattern. When thumbs is empty we fall
    # back to a text-only call (the planner sees only the JSON, which is
    # still useful for narrative-level critiques).
    parts: list[Any] = []
    for i, raw in enumerate(thumbs):
        try:
            parts.append(
                types.Part.from_bytes(
                    data=raw,
                    mime_type="image/jpeg",
                )
            )
        except Exception:
            # Some SDK variants take base64 strings on a different field;
            # try the inline_data dict shape as a fallback.
            try:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(raw).decode("ascii"),
                        }
                    }
                )
            except Exception:
                log.warning(
                    "critic: failed to attach thumbnail %s — skipping", i
                )
                continue

    parts.append(
        types.Part.from_text(
            text=_user_prompt(
                thumbs_count=len(thumbs),
                frames_count=len(frames),
            )
            + "\n\nSTORYBOARD JSON:\n"
            + storyboard_summary,
        )
    )

    contents = [
        types.Content(role="user", parts=parts),
    ]

    config = types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_planning_model,
            contents=contents,
            config=config,
        )
    except Exception as e:
        log.warning("critic: multimodal Gemini call failed: %s", e)
        return _empty_plan(f"multimodal call failed: {str(e)[:240]}")

    raw_text = (response.text or "").strip()
    if not raw_text:
        return _empty_plan("model returned empty response")
    try:
        plan = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.warning("critic: model emitted non-JSON: %s", e)
        return _empty_plan(f"non-JSON response: {str(e)[:240]}")

    if not isinstance(plan, dict):
        return _empty_plan("model returned non-object JSON")

    return _post_process_plan(plan, frames)


# ── Effects-in-motion (second-pass critic) ────────────────────────────────
# A SECOND multimodal pass that watches the FULL rendered video (not just
# thumbnails) and evaluates the motion-graphics effects layer + transitions.
# Emits a new class of mutations targeting `frame.X.effects[i].*` and the
# add/remove array operations the improver also handles.
#
# Runs in parallel with critique_video; the API aggregates both. Mutation IDs
# are namespaced ("em0", "em1", ...) so they never collide with the macro
# pass. All effects mutations are cost="free" — never trigger Veo.

# Inline upload cap. Above this we'd need the Files API; for v1 we skip
# the second pass and let the macro critic carry the full result.
_EFFECTS_VIDEO_INLINE_MAX_BYTES = 20 * 1024 * 1024


_EFFECTS_SYSTEM_PROMPT = (
    "You are a senior motion-graphics editor reviewing the EFFECTS LAYER of "
    "a 12-15 second marketing video — the kinetic_text, lower_third, "
    "brand_stinger, spotlight, kinetic_lines, and data_pop overlays the "
    "storyboard planner attached to each shot. Watch the full video. For "
    "each effect, evaluate:\n\n"
    "  - Is the effect doing its narrative job? Or is it decoration "
    "competing with the caption?\n"
    "  - Is the position right? (zone: tl/tc/tr/ml/mc/mr/bl/bc/br grid)\n"
    "  - Is the size right? (sm/md/lg)\n"
    "  - Is the color readable against the background?\n"
    "  - Is the timing tied to a beat? (cut, motion peak, narrative climax)\n"
    "  - Does kinetic_text duplicate the caption? It should PUNCTUATE, not "
    "echo.\n"
    "  - Does spotlight actually highlight the subject, or is it pointed at "
    "empty space?\n"
    "  - Does lower_third overlap the subject?\n"
    "  - Does brand_stinger land between two beats, or floating randomly?\n"
    "  - Are there too many effects on one shot? (>2 = noisy)\n"
    "  - Are there shots that NEED an effect but have none? (key moments "
    "without punctuation)\n\n"
    "Be ruthless. Most ineffective effects should be REMOVED, not tuned. "
    "Suggest specific param changes — concrete from→to values. Reference "
    "the exact frame_id and effect index.\n\n"
    "Also evaluate TRANSITIONS — every cut between shots. Is the cut "
    "working, or does the pair need a crossfade or a Veo motion bridge?\n\n"
    "Output JSON: {summary, weaknesses, mutations}."
)


def _shape_storyboard_effects_for_critic(
    storyboard_id: str, frames: list[dict]
) -> str:
    """Compact JSON view of the effects layer the second-pass critic
    needs to reason about. Includes per-frame caption + focal_zone +
    duration so the LLM can judge whether an effect duplicates the
    caption or overlaps the subject."""
    summary: list[dict] = []
    for f in frames:
        if not isinstance(f, dict):
            continue
        effects_in = f.get("effects") or []
        effects_out: list[dict] = []
        for idx, e in enumerate(effects_in):
            if not isinstance(e, dict):
                continue
            entry: dict = {
                "index": idx,
                "id": e.get("id"),
                "kind": e.get("kind"),
                "params": e.get("params") or {},
            }
            if e.get("start_ms") is not None:
                entry["start_ms"] = e["start_ms"]
            if e.get("duration_ms") is not None:
                entry["duration_ms"] = e["duration_ms"]
            effects_out.append(entry)
        summary.append(
            {
                "id": f.get("id"),
                "kind": f.get("kind", "live_action"),
                "caption": (f.get("caption") or "")[:200],
                "duration_ms": f.get("duration_ms"),
                "focal_zone": f.get("focal_zone", "mc"),
                "template": f.get("template"),
                "effects": effects_out,
            }
        )
    return json.dumps(
        {"storyboard_id": storyboard_id, "frames": summary},
        ensure_ascii=False,
        indent=None,
    )


def _effects_user_prompt(frames_count: int) -> str:
    """User-message portion. Documents the mutation grammar AND the
    add/remove array operations so the LLM emits actionable targets."""
    return (
        "Watch the full video attached above. Then read the storyboard "
        "EFFECTS JSON below — every overlay attached to every shot, with "
        f"{frames_count} frames in temporal order. Evaluate the effects "
        "layer per the system prompt and output JSON in this shape:\n\n"
        "{\n"
        "  \"summary\": \"1-2 sentence overall take on the effects layer\",\n"
        "  \"weaknesses\": [\n"
        "    {\n"
        "      \"id\": \"ew0\",\n"
        "      \"frame_id\": \"f3\" | null,\n"
        "      \"transition\": \"f3_f4\" | null,\n"
        "      \"effect_index\": 0 | null,\n"
        "      \"issue\": \"concrete failure of the effect or transition\",\n"
        "      \"severity\": \"high\" | \"medium\" | \"low\",\n"
        "      \"category\": \"contrast\" | \"cut\" | \"motion\" | "
        "\"composition\" | \"pacing\" | \"narrative\" | \"consistency\"\n"
        "    }\n"
        "  ],\n"
        "  \"mutations\": [\n"
        "    {\n"
        "      \"id\": \"em0\",\n"
        "      \"weakness_ids\": [\"ew0\"],\n"
        "      \"target\": <one of the targets below>,\n"
        "      \"from\": <current value, or for remove: the index/id>,\n"
        "      \"to\": <proposed value, or null for remove>,\n"
        "      \"reason\": \"one sentence justification\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "MUTATION TARGET GRAMMAR — pick one per mutation:\n"
        "  - frame.X.effects[i].params.zone        — string from "
        "tl|tc|tr|ml|mc|mr|bl|bc|br\n"
        "  - frame.X.effects[i].params.size        — \"sm\" | \"md\" | \"lg\"\n"
        "  - frame.X.effects[i].params.color       — \"accent\" | \"text\" "
        "| \"background\"\n"
        "  - frame.X.effects[i].params.text        — kinetic_text only\n"
        "  - frame.X.effects[i].params.value       — data_pop only\n"
        "  - frame.X.effects[i].duration_ms        — int (>=60)\n"
        "  - frame.X.effects[i].start_ms           — int (>=0)\n"
        "  - frame.X.effects[i].kind               — swap effect type "
        "(kinetic_text|lower_third|brand_stinger|spotlight|kinetic_lines|"
        "data_pop)\n"
        "  - frame.X.effects.add                   — `to` is "
        "{kind, params, start_ms?, duration_ms?} — append a NEW effect\n"
        "  - frame.X.effects.remove                — `from` is the integer "
        "index OR {\"id\": \"<effect id>\"}; `to` is null\n\n"
        "i is the integer effect_index from the EFFECTS JSON below. Cite "
        "exact frame ids ('f0', 'f3', etc) — do NOT invent new ids. Order "
        "weaknesses by severity desc. Most ineffective effects should be "
        "REMOVED rather than tuned — prefer the .remove target when an "
        "effect is decoration competing with the read. Mutation IDs must "
        "start with 'em' to distinguish from macro-pass mutations."
    )


def _post_process_effects_plan(plan: dict, frames: list[dict]) -> dict:
    """Normalise the effects-pass plan. Mirrors `_post_process_plan` but
    namespaces IDs ('ew', 'em' prefixes) and forces cost="free" on every
    mutation so the UI badge is reliable."""
    summary = (plan.get("summary") or "").strip() or "No summary."

    frames_by_id = {
        f.get("id"): f for f in frames if isinstance(f, dict)
    }

    weaknesses_in = plan.get("weaknesses") or []
    weaknesses_out: list[dict] = []
    seen_w_ids: set[str] = set()
    for i, w in enumerate(weaknesses_in):
        if not isinstance(w, dict):
            continue
        wid = (w.get("id") or "").strip() or f"ew{i}"
        if not wid.startswith("ew"):
            # Keep a stable namespace for downstream cross-references.
            wid = f"ew{i}"
        if wid in seen_w_ids:
            wid = f"ew{i}_{len(seen_w_ids)}"
        seen_w_ids.add(wid)
        sev = (w.get("severity") or "medium").strip().lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        cat = (w.get("category") or "composition").strip().lower()
        if cat not in (
            "contrast",
            "cut",
            "motion",
            "composition",
            "pacing",
            "narrative",
            "consistency",
        ):
            cat = "composition"
        weaknesses_out.append(
            {
                "id": wid,
                "frame_id": w.get("frame_id"),
                "transition": w.get("transition"),
                "issue": (w.get("issue") or "").strip()[:600],
                "severity": sev,
                "category": cat,
            }
        )

    mutations_in = plan.get("mutations") or []
    mutations_out: list[dict] = []
    seen_m_ids: set[str] = set()
    valid_w_ids = {w["id"] for w in weaknesses_out}
    for i, m in enumerate(mutations_in):
        if not isinstance(m, dict):
            continue
        mid = (m.get("id") or "").strip() or f"em{i}"
        if not mid.startswith("em"):
            mid = f"em{i}"
        if mid in seen_m_ids:
            mid = f"em{i}_{len(seen_m_ids)}"
        seen_m_ids.add(mid)
        target = (m.get("target") or "").strip()
        if not target:
            continue
        wids_in = m.get("weakness_ids") or []
        wids_filtered = [
            str(x) for x in wids_in if isinstance(x, str) and x in valid_w_ids
        ]
        # Effects mutations are ALWAYS free — never re-fire Veo.
        cost, est_s = "free", 30
        from_val = m.get("from")
        if from_val is None:
            from_val = _lookup_effects_from(target, frames_by_id)
        mutations_out.append(
            {
                "id": mid,
                "weakness_ids": wids_filtered,
                "target": target,
                "from": from_val,
                "to": m.get("to"),
                "reason": (m.get("reason") or "").strip()[:400],
                "cost": cost,
                "estimated_seconds": est_s,
            }
        )

    return {
        "summary": summary[:600],
        "weaknesses": weaknesses_out,
        "mutations": mutations_out,
    }


def _lookup_effects_from(target: str, frames_by_id: dict) -> Any:
    """Best-effort `from` lookup for the new effects-array grammar.
    Recognises:
      frame.X.effects[i].<sub>.<sub>...
      frame.X.effects.add  → None  (no current value)
      frame.X.effects.remove → the index/id (caller already supplied it)
    """
    parts = target.split(".")
    if len(parts) < 2 or parts[0] != "frame":
        return None
    fid = parts[1]
    frame = frames_by_id.get(fid)
    if not isinstance(frame, dict):
        return None

    # Effects-array operations: nothing to look up for `add`; `remove`
    # carries the index/id in the mutation's `from` already.
    if len(parts) >= 3 and parts[2].startswith("effects"):
        head = parts[2]
        if head == "effects":
            # frame.X.effects.add / .remove — no current value.
            return None
        if "[" in head and "]" in head:
            # frame.X.effects[i].sub.path
            try:
                idx = int(head[head.index("[") + 1 : head.index("]")])
            except ValueError:
                return None
            effects = frame.get("effects") or []
            if idx < 0 or idx >= len(effects):
                return None
            cursor: Any = effects[idx]
            for key in parts[3:]:
                if isinstance(cursor, dict):
                    cursor = cursor.get(key)
                else:
                    return None
                if cursor is None:
                    return None
            return cursor
    # Fall back to the macro-pass lookup for non-effects targets.
    return _lookup_from(target, frames_by_id)


async def _read_video_bytes_for_critic(video_url: str) -> tuple[bytes | None, str | None]:
    """Resolve `video_url` to mp4 bytes for the multimodal call.

    Strategy:
      - Local-mode storage URL → read directly from disk.
      - Absolute http/https → fetch through HTTP (httpx).
    Returns (bytes, error). At most one is set; on error, bytes is None
    and the error string is human-readable.
    """
    # Local-storage path first — cheapest + matches macro-critic resolver.
    src = _resolve_local_mp4_path(video_url)
    if src is not None:
        try:
            size = src.stat().st_size
        except OSError as e:
            return None, f"failed to stat local video: {e}"
        if size > _EFFECTS_VIDEO_INLINE_MAX_BYTES:
            return None, "video too large for inline upload"
        try:
            return src.read_bytes(), None
        except OSError as e:
            return None, f"failed to read local video: {e}"

    # Remote — only attempt on absolute http(s) URLs.
    if not video_url.startswith(("http://", "https://")):
        return None, "video url is not a local path or http(s) URL"
    try:
        # Lazy-import httpx so this module imports cleanly without it.
        import httpx  # type: ignore[import-not-found]
    except ImportError:
        return None, "httpx not installed — cannot fetch remote video"
    try:
        async with httpx.AsyncClient(timeout=30.0) as h:
            resp = await h.get(video_url)
        if resp.status_code != 200:
            return None, f"remote fetch returned {resp.status_code}"
        body = resp.content or b""
        if len(body) > _EFFECTS_VIDEO_INLINE_MAX_BYTES:
            return None, "video too large for inline upload"
        return body, None
    except Exception as e:
        return None, f"remote fetch failed: {str(e)[:200]}"


def _empty_effects_plan(reason: str) -> dict:
    """Empty plan in the SAME shape as critique_video so the API
    aggregator can mix them without special casing."""
    return {
        "summary": "",
        "weaknesses": [],
        "mutations": [],
        "error": reason,
    }


async def critique_effects_in_motion(
    storyboard_id: str,
    video_url: str,
    frames: list[dict],
) -> dict:
    """Second-pass multimodal critic that watches the FULL rendered video
    (not just thumbnails) and evaluates the motion-graphics effects +
    transitions.

    Returns the same plan shape as `critique_video` — but every weakness
    and mutation is namespaced (ew*/em*) and tagged so the aggregator
    can label them in the UI. All effects mutations are cost="free"
    (Remotion re-render only — no Veo refire).

    Failures (no key, video too big, multimodal error, JSON parse) all
    return a structured empty plan with `error` set rather than raising.
    The macro critic still produces a useful plan even when this one
    degrades.
    """
    client = get_veo_client()
    if client is None:
        return _empty_effects_plan("GEMINI_API_KEY is not configured")

    video_bytes, err = await _read_video_bytes_for_critic(video_url)
    if video_bytes is None:
        log.info(
            "effects critic: skipping multimodal call — %s (url=%s)",
            err,
            video_url,
        )
        return _empty_effects_plan(err or "could not load video bytes")

    storyboard_summary = _shape_storyboard_effects_for_critic(
        storyboard_id, frames
    )

    # Compose: video Part first, then a single text Part with the user
    # prompt + the storyboard effects JSON inline. Mirrors the macro
    # critic's pattern.
    parts: list[Any] = []
    try:
        parts.append(
            types.Part.from_bytes(
                data=video_bytes,
                mime_type="video/mp4",
            )
        )
    except Exception as e:
        log.warning("effects critic: failed to attach video Part: %s", e)
        return _empty_effects_plan(f"video Part build failed: {str(e)[:200]}")

    parts.append(
        types.Part.from_text(
            text=_effects_user_prompt(frames_count=len(frames))
            + "\n\nEFFECTS JSON:\n"
            + storyboard_summary,
        )
    )

    contents = [types.Content(role="user", parts=parts)]
    config = types.GenerateContentConfig(
        system_instruction=_EFFECTS_SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_planning_model,
            contents=contents,
            config=config,
        )
    except Exception as e:
        log.warning("effects critic: multimodal call failed: %s", e)
        return _empty_effects_plan(
            f"multimodal call failed: {str(e)[:240]}"
        )

    raw_text = (response.text or "").strip()
    if not raw_text:
        return _empty_effects_plan("model returned empty response")
    try:
        plan = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.warning("effects critic: model emitted non-JSON: %s", e)
        return _empty_effects_plan(f"non-JSON response: {str(e)[:240]}")

    if not isinstance(plan, dict):
        return _empty_effects_plan("model returned non-object JSON")

    return _post_process_effects_plan(plan, frames)
