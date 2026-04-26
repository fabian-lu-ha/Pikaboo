"""Mutation applier for the v1 → v2 improvement loop.

Takes a base storyboard snapshot + the user's approved subset of
mutation IDs (from a critic plan) and produces:

  - A new storyboard dict with mutations applied to the frames.
  - The list of frame_ids that need a Veo re-fire (any mutation that
    targets `frame.X.prompt` or `frame.X.motion`).
  - A persisted version entry on the Storyboard row's `versions` JSON
    column. v1 is recorded automatically when the first /render call
    succeeds; v2+ are produced here.

Versions are append-only — never deleted or rewritten. The UI loads
any historical version into the editor for inspection.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.db.session import SessionLocal

log = logging.getLogger(__name__)


# ── stable frame ID minting ───────────────────────────────────────────────

_VALID_FRAME_KINDS: tuple[str, ...] = ("live_action", "design_sequence")


def _mint_frame_id(existing_ids: set[str]) -> str:
    """Mint a fresh frame ID that doesn't collide with anything in
    `existing_ids`. Uses an uuid4-suffixed prefix so concurrent appliers
    don't accidentally produce the same ID — and keeps the prefix
    "f_added_" so the UI can spot inserted-by-critic frames in logs.
    """
    for _ in range(8):
        candidate = f"f_added_{uuid.uuid4().hex[:8]}"
        if candidate not in existing_ids:
            return candidate
    # Last-resort fallback — extremely unlikely to ever hit.
    return f"f_added_{uuid.uuid4().hex}"


# ── version snapshots ─────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_version(
    storyboard_id: str,
    *,
    frames: list[dict],
    video_url: str | None,
    critique: dict | None,
    applied_mutations: list[str] | None,
    aspect: str | None = None,
    title_card: dict | None = None,
    end_card: dict | None = None,
) -> int:
    """Append a new version snapshot to the Storyboard row's `versions`
    JSON column. Returns the assigned version_number.

    Idempotent guard: if the most-recent version has the same video_url
    AND no critique attached, we skip — that's the v1 auto-record path
    being called twice (e.g. on hot reload). v2+ entries always have a
    distinct video_url AND a critique payload so they're never deduped.
    """
    if not storyboard_id:
        return 0
    with SessionLocal() as db:
        sb = db.get(models.Storyboard, storyboard_id)
        if sb is None:
            log.warning(
                "improver: cannot record version — storyboard %s not found",
                storyboard_id,
            )
            return 0
        existing = list(sb.versions or [])
        if (
            existing
            and critique is None
            and existing[-1].get("video_url") == video_url
        ):
            # Same render, no critique — that's a duplicate v1 record.
            return int(existing[-1].get("version_number") or len(existing))
        version_number = len(existing) + 1
        entry = {
            "version_number": version_number,
            "frames": [dict(f) for f in (frames or [])],
            "video_url": video_url,
            "critique": critique,
            "applied_mutations": list(applied_mutations or []),
            "aspect": aspect,
            "title_card": dict(title_card) if title_card else None,
            "end_card": dict(end_card) if end_card else None,
            "created_at": _now_iso(),
        }
        existing.append(entry)
        sb.versions = existing
        flag_modified(sb, "versions")
        db.commit()
        log.info(
            "improver: recorded v%s for storyboard=%s (mutations=%s)",
            version_number,
            storyboard_id,
            len(applied_mutations or []),
        )
        return version_number


def list_versions(storyboard_id: str) -> list[dict]:
    """Return [{version_number, video_url, summary, mutation_count,
    created_at}] in ascending order. Lightweight — does not echo full
    frame snapshots."""
    if not storyboard_id:
        return []
    with SessionLocal() as db:
        sb = db.get(models.Storyboard, storyboard_id)
        if sb is None:
            return []
        out: list[dict] = []
        for v in sb.versions or []:
            if not isinstance(v, dict):
                continue
            critique = v.get("critique") or {}
            summary = (
                critique.get("summary") if isinstance(critique, dict) else None
            )
            out.append(
                {
                    "version_number": int(v.get("version_number") or 0),
                    "video_url": v.get("video_url"),
                    "summary": summary,
                    "mutation_count": len(v.get("applied_mutations") or []),
                    "created_at": v.get("created_at"),
                }
            )
        out.sort(key=lambda x: x["version_number"])
        return out


def get_version(storyboard_id: str, version_number: int) -> dict | None:
    """Fetch the full snapshot for a single version. None when missing."""
    if not storyboard_id or version_number <= 0:
        return None
    with SessionLocal() as db:
        sb = db.get(models.Storyboard, storyboard_id)
        if sb is None:
            return None
        for v in sb.versions or []:
            if isinstance(v, dict) and int(v.get("version_number") or 0) == version_number:
                return dict(v)
    return None


# ── mutation application ──────────────────────────────────────────────────


def _set_at_path(target_root: dict, path: list[str], value: Any) -> bool:
    """Walk `path` into `target_root` (mutating intermediate dicts as
    needed) and set the leaf to `value`. Returns True on success."""
    cursor = target_root
    for key in path[:-1]:
        if not isinstance(cursor, dict):
            return False
        if key not in cursor or not isinstance(cursor.get(key), dict):
            cursor[key] = {}
        cursor = cursor[key]
    if not isinstance(cursor, dict):
        return False
    cursor[path[-1]] = value
    return True


def _parse_effects_head(head: str) -> tuple[str, int | None]:
    """Parse the first segment after `frame.X.` when it relates to the
    effects array.

    Returns (op, index) where:
      - op="effects_index", index=i  for `effects[i]`
      - op="effects",       index=None for the bare `effects` segment
        (used by the .add / .remove array operations)
    Raises ValueError on a malformed segment.
    """
    if head == "effects":
        return ("effects", None)
    if head.startswith("effects[") and head.endswith("]"):
        try:
            idx = int(head[len("effects[") : -1])
        except ValueError as e:
            raise ValueError(f"bad effects index: {head}") from e
        return ("effects_index", idx)
    raise ValueError(f"unrecognized effects segment: {head}")


def _find_frame(frames: list, fid: str) -> tuple[int, dict] | None:
    """Locate (index, frame_dict) for frame id `fid`. None when missing."""
    for i, f in enumerate(frames):
        if isinstance(f, dict) and f.get("id") == fid:
            return i, f
    return None


def _apply_effect_mutation(
    storyboard: dict,
    fid: str,
    prop_path: list[str],
    mutation: dict,
) -> bool:
    """Apply an effects-array mutation to the storyboard frame `fid`.

    prop_path starts with the effects segment (either bare `effects` for
    add/remove, or `effects[i]` for in-place property edits). Returns
    True on success, False on any structural problem (missing frame,
    out-of-bounds index, malformed grammar) — never raises. All effects
    mutations are cost-free; this function never triggers a Veo refire.
    """
    frames = storyboard.get("frames") or []
    found = _find_frame(frames, fid)
    if found is None:
        log.warning(
            "improver: effects mutation target frame=%s not found — skipping",
            fid,
        )
        return False
    idx_in_frames, frame = found

    if not prop_path:
        log.warning("improver: empty effects prop_path for frame=%s", fid)
        return False

    head = prop_path[0]
    try:
        op, eff_idx = _parse_effects_head(head)
    except ValueError as e:
        log.warning("improver: %s — skipping mutation", e)
        return False

    new_value = mutation.get("to")
    from_value = mutation.get("from")
    effects = list(frame.get("effects") or [])

    if op == "effects":
        # frame.X.effects.<add|remove>
        if len(prop_path) < 2:
            log.warning(
                "improver: effects op missing add/remove suffix for frame=%s",
                fid,
            )
            return False
        action = prop_path[1]
        if action == "add":
            new_eff = new_value if isinstance(new_value, dict) else None
            if new_eff is None:
                log.warning(
                    "improver: effects.add for frame=%s requires a dict `to`",
                    fid,
                )
                return False
            # Auto-assign id if missing so downstream ops can reference it.
            entry = dict(new_eff)
            if not entry.get("id"):
                entry["id"] = f"{fid}_e_added_{len(effects)}"
            # Don't enforce kind validity here — the storyboard normalizer
            # handles unknown kinds at render time. Log them for visibility.
            kind = entry.get("kind")
            if kind is None:
                log.warning(
                    "improver: effects.add for frame=%s has no kind — Remotion "
                    "will validate at render time",
                    fid,
                )
            effects.append(entry)
        elif action == "remove":
            removed = False
            target_index: int | None = None
            target_id: str | None = None
            # Accept `from` as int (index) OR {"id": "..."} (lookup by id).
            if isinstance(from_value, int):
                target_index = from_value
            elif isinstance(from_value, dict) and isinstance(
                from_value.get("id"), str
            ):
                target_id = from_value["id"]
            else:
                # Fall back to mutation.to as a lookup hint — some LLMs put the
                # target there.
                if isinstance(new_value, int):
                    target_index = new_value
                elif isinstance(new_value, dict) and isinstance(
                    new_value.get("id"), str
                ):
                    target_id = new_value["id"]
            if target_index is not None:
                if 0 <= target_index < len(effects):
                    effects.pop(target_index)
                    removed = True
            elif target_id is not None:
                for i, e in enumerate(effects):
                    if isinstance(e, dict) and e.get("id") == target_id:
                        effects.pop(i)
                        removed = True
                        break
            if not removed:
                log.warning(
                    "improver: effects.remove for frame=%s could not resolve "
                    "target (from=%r, to=%r) — skipping",
                    fid,
                    from_value,
                    new_value,
                )
                return False
        else:
            log.warning(
                "improver: unknown effects op %r for frame=%s — skipping",
                action,
                fid,
            )
            return False

        new_frame = dict(frame)
        new_frame["effects"] = effects
        frames[idx_in_frames] = new_frame
        storyboard["frames"] = frames
        return True

    # op == "effects_index" — in-place edit on effects[i].<sub>...
    assert eff_idx is not None
    if eff_idx < 0 or eff_idx >= len(effects):
        log.warning(
            "improver: effects index %s out of bounds for frame=%s (len=%s) — "
            "skipping",
            eff_idx,
            fid,
            len(effects),
        )
        return False
    sub_path = prop_path[1:]
    if not sub_path:
        log.warning(
            "improver: effects[%s] mutation for frame=%s has no sub-path — "
            "skipping",
            eff_idx,
            fid,
        )
        return False
    target_entry = dict(effects[eff_idx])
    ok = _set_at_path(target_entry, sub_path, new_value)
    if not ok:
        log.warning(
            "improver: failed to set %s on effects[%s] for frame=%s — skipping",
            ".".join(sub_path),
            eff_idx,
            fid,
        )
        return False
    effects[eff_idx] = target_entry
    new_frame = dict(frame)
    new_frame["effects"] = effects
    frames[idx_in_frames] = new_frame
    storyboard["frames"] = frames
    return True


def _resolve_index_or_id(
    frames: list,
    raw: Any,
    *,
    allow_after: bool = False,
) -> int | None:
    """Resolve a structural-op location reference into a frames-list index.

    Accepts:
      - int                         → index (clamped into bounds)
      - {"id": "f3"}                → look up by frame id
      - {"after": "f3"}             → return idx_of(f3) + 1 (only if allow_after)
      - {"before": "f3"}            → return idx_of(f3)    (only if allow_after)
      - str                         → treated as a frame id

    Returns None on miss. Used by frames.add (allow_after=True) and
    frames.remove / frames.reorder (allow_after=False).
    """
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        for i, f in enumerate(frames):
            if isinstance(f, dict) and f.get("id") == raw:
                return i
        return None
    if isinstance(raw, dict):
        if allow_after and isinstance(raw.get("after"), str):
            for i, f in enumerate(frames):
                if isinstance(f, dict) and f.get("id") == raw["after"]:
                    return i + 1
            return None
        if allow_after and isinstance(raw.get("before"), str):
            for i, f in enumerate(frames):
                if isinstance(f, dict) and f.get("id") == raw["before"]:
                    return i
            return None
        if isinstance(raw.get("id"), str):
            for i, f in enumerate(frames):
                if isinstance(f, dict) and f.get("id") == raw["id"]:
                    return i
            return None
    return None


def _normalize_inserted_frame(spec: dict, *, frame_id: str) -> dict | None:
    """Validate + shape an inserted-frame spec the LLM proposed for
    `frames.add`. Returns the cleaned frame dict, or None if the spec
    is too malformed to use.

    Required fields:
      - kind: "live_action" or "design_sequence"
      - caption: short string (defaults to "")
      - duration_ms: int (defaults to 2500)
    Conditional:
      - live_action: prompt should be present (best-effort)
      - design_sequence: template + template_params required
    """
    if not isinstance(spec, dict):
        return None
    kind = str(spec.get("kind") or "live_action").strip().lower()
    if kind not in _VALID_FRAME_KINDS:
        kind = "live_action"

    new_frame: dict[str, Any] = {
        "id": frame_id,
        "kind": kind,
        "prompt": str(spec.get("prompt") or "").strip()[:2000],
        "motion": str(spec.get("motion") or "").strip()[:600],
        "caption": str(spec.get("caption") or "").strip()[:200],
        "duration_ms": int(spec.get("duration_ms") or 2500),
        "focal_zone": str(spec.get("focal_zone") or "mc"),
        "image_url": None,
        "clip_url": None,
        "cast_refs": list(spec.get("cast_refs") or []),
        "effects": list(spec.get("effects") or []),
        "template": None,
        "template_params": None,
    }

    if kind == "design_sequence":
        tmpl = spec.get("template")
        params = spec.get("template_params")
        if not isinstance(tmpl, str) or not tmpl.strip():
            log.warning(
                "improver: frames.add design_sequence missing template — skipping"
            )
            return None
        new_frame["template"] = tmpl.strip()
        new_frame["template_params"] = (
            dict(params) if isinstance(params, dict) else {}
        )

    return new_frame


def _apply_frames_structural(
    storyboard: dict,
    op: str,
    mutation: dict,
) -> tuple[bool, str | None]:
    """Handle the four structural mutations: frames.add, frames.remove,
    frames.reorder, and the frame.X.kind swap.

    Returns (applied, refire_frame_id). refire_frame_id is set only when
    the structural change requires a Veo re-fire — currently:
      - frames.add(kind=live_action) → the new frame ID
      - frame.X.kind → "live_action" → the swapped frame ID

    Failures (unresolvable indices, bad spec, etc.) log + return
    (False, None) — never raise.
    """
    frames = list(storyboard.get("frames") or [])

    if op == "frames.add":
        spec = mutation.get("to")
        if not isinstance(spec, dict):
            log.warning("improver: frames.add requires `to` to be a frame spec dict")
            return False, None
        existing_ids = {
            f.get("id") for f in frames if isinstance(f, dict) and f.get("id")
        }
        # Allow the LLM to suggest an id; otherwise mint one.
        proposed_id = spec.get("id")
        if isinstance(proposed_id, str) and proposed_id and proposed_id not in existing_ids:
            new_id = proposed_id
        else:
            new_id = _mint_frame_id(existing_ids)
        new_frame = _normalize_inserted_frame(spec, frame_id=new_id)
        if new_frame is None:
            return False, None
        from_raw = mutation.get("from")
        # `from` carries the insertion target. Default = append.
        if from_raw is None:
            insert_at = len(frames)
        else:
            resolved = _resolve_index_or_id(frames, from_raw, allow_after=True)
            if resolved is None:
                log.warning(
                    "improver: frames.add could not resolve `from`=%r — appending",
                    from_raw,
                )
                insert_at = len(frames)
            else:
                insert_at = max(0, min(resolved, len(frames)))
        frames.insert(insert_at, new_frame)
        storyboard["frames"] = frames
        # live_action inserts need a Veo refire so the new frame has a clip.
        # design_sequence frames are pure-graphic Remotion templates and
        # never go to Veo, so no refire id is returned.
        refire_fid = new_id if new_frame["kind"] == "live_action" else None
        log.info(
            "improver: frames.add inserted frame=%s (kind=%s) at index=%s",
            new_id,
            new_frame["kind"],
            insert_at,
        )
        return True, refire_fid

    if op == "frames.remove":
        from_raw = mutation.get("from")
        idx = _resolve_index_or_id(frames, from_raw, allow_after=False)
        if idx is None or idx < 0 or idx >= len(frames):
            log.warning(
                "improver: frames.remove could not resolve `from`=%r (len=%s) — skipping",
                from_raw,
                len(frames),
            )
            return False, None
        removed = frames.pop(idx)
        storyboard["frames"] = frames
        log.info(
            "improver: frames.remove removed frame=%s at index=%s",
            (removed.get("id") if isinstance(removed, dict) else None),
            idx,
        )
        return True, None

    if op == "frames.reorder":
        from_raw = mutation.get("from")
        to_raw = mutation.get("to")
        src_idx = _resolve_index_or_id(frames, from_raw, allow_after=False)
        if src_idx is None or src_idx < 0 or src_idx >= len(frames):
            log.warning(
                "improver: frames.reorder could not resolve `from`=%r — skipping",
                from_raw,
            )
            return False, None
        # `to` is a destination index. Accept int directly; for {id: ...} or
        # {after: ...} we fall back to _resolve_index_or_id with allow_after.
        dst_idx: int | None
        if isinstance(to_raw, int):
            dst_idx = to_raw
        else:
            dst_idx = _resolve_index_or_id(frames, to_raw, allow_after=True)
        if dst_idx is None:
            log.warning(
                "improver: frames.reorder could not resolve `to`=%r — skipping",
                to_raw,
            )
            return False, None
        moving = frames.pop(src_idx)
        # After the pop, indices to the right shift left by one — adjust dst.
        if dst_idx > src_idx:
            dst_idx -= 1
        dst_idx = max(0, min(dst_idx, len(frames)))
        frames.insert(dst_idx, moving)
        storyboard["frames"] = frames
        log.info(
            "improver: frames.reorder moved frame=%s from %s → %s",
            (moving.get("id") if isinstance(moving, dict) else None),
            src_idx,
            dst_idx,
        )
        return True, None

    # Unknown structural op (shouldn't reach here — caller guards).
    return False, None


def _apply_kind_swap(
    storyboard: dict,
    fid: str,
    mutation: dict,
) -> tuple[bool, str | None]:
    """Handle the `frame.X.kind` swap. Going to live_action clears the
    template payload and triggers a Veo refire; going to design_sequence
    clears clip/keyframe URLs (the LLM is expected to provide a paired
    template + template_params mutation in the same plan).
    """
    new_kind_raw = mutation.get("to")
    new_kind = str(new_kind_raw or "").strip().lower()
    if new_kind not in _VALID_FRAME_KINDS:
        log.warning(
            "improver: frame.%s.kind invalid `to`=%r — skipping",
            fid,
            new_kind_raw,
        )
        return False, None

    frames = list(storyboard.get("frames") or [])
    for i, f in enumerate(frames):
        if not isinstance(f, dict) or f.get("id") != fid:
            continue
        old_kind = str(f.get("kind") or "live_action").lower()
        if old_kind == new_kind:
            log.info(
                "improver: frame.%s.kind already %s — no-op", fid, new_kind
            )
            return True, None

        next_frame = dict(f)
        next_frame["kind"] = new_kind
        if new_kind == "live_action":
            # Going from design → live: drop the template payload, leave the
            # prompt to be filled by a paired frame.X.prompt mutation. Force
            # a Veo refire so the new frame produces a clip.
            next_frame["template"] = None
            next_frame["template_params"] = None
            # Existing clip from a former design_sequence is meaningless
            # (it didn't have one). Clear keyframe so Veo won't lock it.
            next_frame["clip_url"] = None
            next_frame["image_url"] = None
            frames[i] = next_frame
            storyboard["frames"] = frames
            log.info("improver: frame.%s.kind swapped design→live_action", fid)
            return True, fid
        # new_kind == "design_sequence"
        # Going from live → design: drop the Veo media. The LLM is expected
        # to attach template + template_params in paired mutations; if it
        # didn't, the storyboard normalizer will downgrade back to live at
        # render time.
        next_frame["clip_url"] = None
        next_frame["image_url"] = None
        if not next_frame.get("template_params"):
            next_frame["template_params"] = {}
        frames[i] = next_frame
        storyboard["frames"] = frames
        log.info("improver: frame.%s.kind swapped live_action→design_sequence", fid)
        return True, None

    log.warning(
        "improver: frame.%s.kind target frame not found — skipping", fid
    )
    return False, None


def _apply_one_mutation(
    storyboard: dict,
    mutation: dict,
) -> tuple[bool, str | None]:
    """Apply a single mutation to `storyboard` (in place). Returns
    (applied, refire_frame_id). refire_frame_id is set when the mutation
    targeted `frame.X.prompt` / `frame.X.motion`, OR when a structural
    change introduced a new live_action frame that needs Veo to produce
    its clip (frames.add live_action / frame.X.kind → live_action).
    """
    target = (mutation.get("target") or "").strip()
    if not target:
        return False, None
    parts = target.split(".")
    if len(parts) < 2:
        return False, None

    domain = parts[0]
    new_value = mutation.get("to")

    # ── structural frame ops (no fid in target) ─────────────────────────
    # frames.add / frames.remove / frames.reorder all live under the
    # `frames` domain (as opposed to `frame.<id>` for in-place edits).
    if domain == "frames" and len(parts) == 2:
        op = f"frames.{parts[1]}"
        if op in ("frames.add", "frames.remove", "frames.reorder"):
            return _apply_frames_structural(storyboard, op, mutation)
        log.warning("improver: unknown frames.* op %r — skipping", op)
        return False, None

    if domain == "frame":
        if len(parts) < 3:
            return False, None
        fid = parts[1]
        prop_path = parts[2:]

        # Effects-array grammar: anything starting with `effects` or
        # `effects[i]` after `frame.X.` is routed through the dedicated
        # applier so add/remove/in-place edits all share one code path.
        head = prop_path[0]
        if head == "effects" or (head.startswith("effects[") and head.endswith("]")):
            ok = _apply_effect_mutation(storyboard, fid, prop_path, mutation)
            return (ok, None)

        # frame.X.kind — swap the pathway (live_action ↔ design_sequence).
        # Refires live_action so the new frame produces a clip.
        if prop_path == ["kind"]:
            return _apply_kind_swap(storyboard, fid, mutation)

        frames = storyboard.get("frames") or []
        for i, f in enumerate(frames):
            if not isinstance(f, dict):
                continue
            if f.get("id") != fid:
                continue
            target_dict = dict(f)
            ok = _set_at_path(target_dict, prop_path, new_value)
            if not ok:
                return False, None
            frames[i] = target_dict
            storyboard["frames"] = frames
            # Veo re-fire when prompt or motion changed.
            leaf = prop_path[-1]
            if "prompt" in prop_path or "motion" in prop_path or leaf in (
                "prompt",
                "motion",
            ):
                return True, fid
            return True, None
        log.warning(
            "improver: frame=%s not found for target=%s — skipping",
            fid,
            target,
        )
        return False, None

    if domain == "transition":
        # Transition mutations live on the storyboard's planned-transitions
        # list (we keep them on a `transitions` field for v2+; the legacy
        # render path plans them on the fly so we just stash overrides
        # here). Schema: transition.<from_id>_<to_id>.<prop>
        if len(parts) < 3:
            return False, None
        pair = parts[1]
        prop_path = parts[2:]
        overrides = storyboard.get("transition_overrides") or {}
        per_pair = dict(overrides.get(pair) or {})
        ok = _set_at_path(per_pair, prop_path, new_value)
        if not ok:
            return False, None
        # When the LLM proposes upgrading a transition to a Veo bridge, the
        # existing per-pair `clip_url` (if any) is stale — it was rendered
        # for the prior style. Clear it so the bridge-generation pass in
        # /improve treats the pair as needing a fresh clip.
        leaf = prop_path[-1]
        if leaf == "style" and (new_value or "").strip().lower() == "veo_bridge":
            per_pair.pop("clip_url", None)
        overrides[pair] = per_pair
        storyboard["transition_overrides"] = overrides
        return True, None

    # Unknown domain — skip.
    return False, None


async def apply_mutations(
    storyboard_id: str,
    base_storyboard: dict,
    approved_mutation_ids: list[str],
    full_plan: dict,
) -> tuple[dict, list[str]]:
    """Apply selected mutations to a storyboard snapshot.

    Returns:
      (new_storyboard_dict, list_of_frame_ids_that_need_veo_refire)

    The new_storyboard dict mirrors `base_storyboard` shape (cast,
    frames, narrative, etc) — we only touch frames + transition_overrides.
    The improver does NOT persist the result on the Storyboard row; the
    API layer owns that step (and bundles it with re-render + version
    snapshot).
    """
    plan_mutations = {
        m.get("id"): m
        for m in (full_plan.get("mutations") or [])
        if isinstance(m, dict) and m.get("id")
    }
    new_sb = copy.deepcopy(base_storyboard or {})
    if "frames" not in new_sb:
        new_sb["frames"] = []

    refire: set[str] = set()
    applied_count = 0
    skipped: list[str] = []
    for mid in approved_mutation_ids or []:
        mutation = plan_mutations.get(mid)
        if not mutation:
            skipped.append(mid)
            continue
        ok, frame_id = _apply_one_mutation(new_sb, mutation)
        if not ok:
            skipped.append(mid)
            continue
        applied_count += 1
        if frame_id:
            refire.add(frame_id)

    if skipped:
        log.info(
            "improver: skipped %s/%s mutations (unknown id or invalid target)",
            len(skipped),
            len(approved_mutation_ids or []),
        )

    log.info(
        "improver: applied %s mutations on storyboard=%s — %s frames need Veo refire",
        applied_count,
        storyboard_id,
        len(refire),
    )
    return new_sb, sorted(refire)
