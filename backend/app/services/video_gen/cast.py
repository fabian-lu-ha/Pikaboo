"""Cast bible registry for the marketing-video surface.

A *cast* is the set of recurring visual ingredients (characters, settings,
key props, products) that need to stay consistent across all keyframes of
a storyboard. Each cast member resolves to a single canonical image — the
identity reference passed as multi-image input on every frame that uses
the member.

Two flavors of canonical:
  - **brand_asset**: a borrowed URL from the brand's existing assets
    (real product photos, founder headshots, logos). Used as-is, including
    any legitimate text on the photo.
  - **needs_generation**: a synthesized neutral reference sheet that the
    `frame_gen.generate_ingredient` call produces. These sheets must be
    text-free per the hardened anti-prompt.

Backed by the ``storyboards`` table in the app DB. A storyboard's cast,
cinematic_brief, and voiceover all live as JSON columns on a single row
keyed by storyboard_id. We keep the table name singular-resource ("a
storyboard") even though it's pluralized in SQL (``storyboards``) to match
the rest of the schema.

This module exposes a thin sync API (``registry.upsert_storyboard``,
``registry.get_member``, etc.) that opens a fresh ``SessionLocal`` per
call. A process-wide threading lock serializes mutations so the
read-modify-write pattern on JSON columns (e.g. ``bind_canonical``) is
race-free within a process. Cross-process safety is handled by SQLite's
write lock.
"""

from __future__ import annotations

import logging
import threading
from typing import Literal, TypedDict

from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

CastKind = Literal["character", "setting", "prop", "product"]
BindingType = Literal["brand_asset", "needs_generation"]


class CastBinding(TypedDict, total=False):
    type: BindingType
    asset_index: int  # only when type=brand_asset


class CastMember(TypedDict, total=False):
    id: str
    kind: CastKind
    role: str
    description: str
    # narrative_purpose: one-sentence justification for why this entity
    # recurs across frames. Required for cast acceptance — fragmentary or
    # abstract entities (body parts, moods, weather) generally fail this.
    narrative_purpose: str
    neutral_pose_hint: str
    binding: CastBinding
    canonical_url: str | None


class CastRef(TypedDict):
    """Resolved view passed into frame_gen for multi-image conditioning."""

    id: str
    kind: CastKind
    description: str
    canonical_url: str


class CastRegistry:
    """DB-backed cast bible registry, keyed by storyboard_id.

    Every method opens its own SessionLocal so the registry has no shared
    connection state. Mutations are wrapped in a process-wide lock to
    prevent two concurrent ``bind_canonical`` calls (or similar JSON-column
    read-modify-writes) from clobbering each other within a single process.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ── reads ──────────────────────────────────────────────────────────

    def get_member(
        self, storyboard_id: str, cast_id: str
    ) -> CastMember | None:
        if not storyboard_id or not cast_id:
            return None
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                return None
            cast = sb.cast or {}
            mem = cast.get(cast_id)
            return None if mem is None else dict(mem)  # type: ignore[return-value]

    def has_storyboard(self, storyboard_id: str) -> bool:
        if not storyboard_id:
            return False
        with SessionLocal() as db:
            return db.get(models.Storyboard, storyboard_id) is not None

    def list_members(self, storyboard_id: str) -> list[CastMember]:
        if not storyboard_id:
            return []
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                return []
            return [dict(m) for m in (sb.cast or {}).values()]  # type: ignore[misc]

    def all_locked(self, storyboard_id: str) -> bool:
        """True iff every cast member has a canonical_url."""
        if not storyboard_id:
            return False
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None or not sb.cast:
                return False
            return all(bool(m.get("canonical_url")) for m in sb.cast.values())

    def resolve(
        self, storyboard_id: str, cast_ids: list[str]
    ) -> list[CastRef]:
        """Resolve cast IDs to ordered CastRef list. Skips members with no
        canonical_url and unknown IDs (logged)."""
        out: list[CastRef] = []
        if not storyboard_id or not cast_ids:
            return out
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                log.warning(
                    "cast resolve: unknown storyboard %s (refs=%s)",
                    storyboard_id, cast_ids,
                )
                return out
            cast = sb.cast or {}
            for cid in cast_ids:
                m = cast.get(cid)
                if m is None:
                    log.warning(
                        "cast resolve: unknown cast id %s in %s",
                        cid, storyboard_id,
                    )
                    continue
                url = m.get("canonical_url")
                if not url:
                    log.warning(
                        "cast resolve: %s in %s has no canonical_url yet",
                        cid, storyboard_id,
                    )
                    continue
                out.append(
                    CastRef(
                        id=m["id"],
                        kind=m.get("kind", "character"),  # type: ignore[arg-type]
                        description=m.get("description", ""),
                        canonical_url=url,
                    )
                )
        return out

    def get_brief(self, storyboard_id: str) -> dict | None:
        if not storyboard_id:
            return None
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None or not sb.cinematic_brief:
                return None
            return dict(sb.cinematic_brief)

    def get_voiceover(self, storyboard_id: str) -> dict | None:
        if not storyboard_id:
            return None
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None or not sb.voiceover:
                return None
            return dict(sb.voiceover)

    # ── writes ─────────────────────────────────────────────────────────

    def upsert_storyboard(
        self, storyboard_id: str, cast: list[CastMember]
    ) -> None:
        """Create or replace the cast bible for a storyboard.

        Used at /suggest time. Replaces ``cast`` wholesale — any existing
        canonical_urls under cast IDs that survive the new bible are
        preserved (re-binding a cast member shouldn't lose the expensive
        ingredient sheet that was already generated for it)."""
        if not storyboard_id:
            return
        members: dict[str, CastMember] = {}
        for m in cast:
            mid = m.get("id")
            if not mid:
                continue
            members[mid] = dict(m)  # type: ignore[assignment]
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                sb = models.Storyboard(id=storyboard_id, cast=members)
                db.add(sb)
            else:
                # Preserve any pre-existing canonical_urls when the bible
                # is re-uploaded (e.g. variation hint on /regenerate-
                # ingredient triggers a re-suggest from the planner).
                prev = sb.cast or {}
                for cid, m in members.items():
                    if not m.get("canonical_url") and prev.get(cid, {}).get("canonical_url"):
                        m["canonical_url"] = prev[cid]["canonical_url"]
                sb.cast = members
                flag_modified(sb, "cast")
            db.commit()

    def set_brief(self, storyboard_id: str, brief: dict | None) -> None:
        """Attach the director's cinematic brief to a storyboard."""
        if not storyboard_id:
            return
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                sb = models.Storyboard(
                    id=storyboard_id, cinematic_brief=dict(brief or {})
                )
                db.add(sb)
            else:
                sb.cinematic_brief = dict(brief or {})
                flag_modified(sb, "cinematic_brief")
            db.commit()

    def set_voiceover(self, storyboard_id: str, voiceover: dict | None) -> None:
        """Attach the planner-authored voiceover spec to a storyboard.

        Keys: script, voice_persona, voice_name. /voiceover fetches this by
        storyboard_id so the frontend doesn't have to round-trip it.
        """
        if not storyboard_id:
            return
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                sb = models.Storyboard(
                    id=storyboard_id, voiceover=dict(voiceover or {})
                )
                db.add(sb)
            else:
                sb.voiceover = dict(voiceover or {})
                flag_modified(sb, "voiceover")
            db.commit()

    def bind_canonical(
        self, storyboard_id: str, cast_id: str, url: str
    ) -> bool:
        """Set canonical_url on an existing cast member. False if unknown."""
        if not storyboard_id or not cast_id:
            return False
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None or not sb.cast or cast_id not in sb.cast:
                return False
            sb.cast[cast_id]["canonical_url"] = url
            flag_modified(sb, "cast")
            db.commit()
            return True

    # ── frame + render persistence ──────────────────────────────────────
    # Everything below survives reload so the frontend can hydrate from
    # the DB instead of re-running /suggest on every page refresh.

    def set_plan(
        self,
        storyboard_id: str,
        *,
        brand_id: str | None,
        aspect: str | None,
        narrative: dict | None,
        title_card: dict | None,
        end_card: dict | None,
        frames: list[dict] | None,
    ) -> None:
        """Persist the planner-authored portion of a storyboard at /suggest
        time. The cinematic_brief and voiceover are written separately by
        their own setters; this writes everything else the planner emits."""
        if not storyboard_id:
            return
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                sb = models.Storyboard(id=storyboard_id)
                db.add(sb)
            if brand_id is not None:
                sb.brand_id = brand_id
            if aspect is not None:
                sb.aspect = aspect
            sb.narrative = dict(narrative or {})
            sb.title_card = dict(title_card) if title_card else None
            sb.end_card = dict(end_card) if end_card else None
            sb.frames = [dict(f) for f in (frames or [])]
            flag_modified(sb, "narrative")
            flag_modified(sb, "frames")
            db.commit()

    def update_frame(
        self, storyboard_id: str, frame_id: str, patch: dict
    ) -> bool:
        """Patch a single frame in-place (e.g. write image_url after /frame
        completes, write clip_url after /scene completes). Returns True iff
        the frame was found and updated."""
        if not storyboard_id or not frame_id or not patch:
            return False
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                return False
            frames = list(sb.frames or [])
            hit = False
            for i, f in enumerate(frames):
                if isinstance(f, dict) and f.get("id") == frame_id:
                    frames[i] = {**f, **patch}
                    hit = True
                    break
            if not hit:
                return False
            sb.frames = frames
            flag_modified(sb, "frames")
            db.commit()
            return True

    def replace_frames(
        self, storyboard_id: str, frames: list[dict]
    ) -> bool:
        """Replace the entire frames list on a storyboard. Used by the
        improvement loop when a v2 swap-in lands. Returns True iff the
        storyboard exists.
        """
        if not storyboard_id:
            return False
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                return False
            sb.frames = [dict(f) for f in (frames or [])]
            flag_modified(sb, "frames")
            db.commit()
            return True

    def set_render(
        self,
        storyboard_id: str,
        *,
        video_id: str,
        video_url: str,
        duration_ms: int,
    ) -> None:
        """Persist the final Remotion render artifact so the silent video
        URL survives reload. Cleared from voiced_video_url is intentional —
        a fresh render means the prior voiced mp4 no longer matches."""
        if not storyboard_id:
            return
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                sb = models.Storyboard(id=storyboard_id)
                db.add(sb)
            sb.video_id = video_id
            sb.video_url = video_url
            sb.video_duration_ms = int(duration_ms)
            sb.voiced_video_url = None
            db.commit()

    def set_voiced_video(
        self, storyboard_id: str, voiced_url: str
    ) -> None:
        """Persist the muxed voiceover video URL after /voiceover completes."""
        if not storyboard_id:
            return
        with self._lock, SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                return
            sb.voiced_video_url = voiced_url
            db.commit()

    def get_full_storyboard(self, storyboard_id: str) -> dict | None:
        """Return the complete restorable shape for the frontend store —
        everything needed to rehydrate a storyboard panel after a reload."""
        if not storyboard_id:
            return None
        with SessionLocal() as db:
            sb = db.get(models.Storyboard, storyboard_id)
            if sb is None:
                return None
            return _serialize_storyboard(sb)

    def get_latest_for_brand(self, brand_id: str | None) -> dict | None:
        """Return the most-recently-touched storyboard for a brand (or any
        brand when ``brand_id`` is None — useful in single-tenant demo
        mode where every storyboard belongs to the one onboarded brand)."""
        with SessionLocal() as db:
            q = db.query(models.Storyboard)
            if brand_id:
                q = q.filter(models.Storyboard.brand_id == brand_id)
            sb = q.order_by(models.Storyboard.updated_at.desc()).first()
            if sb is None:
                return None
            return _serialize_storyboard(sb)


def _serialize_storyboard(sb: "models.Storyboard") -> dict:
    """Flatten a Storyboard ORM row into the dict shape the API + frontend
    consume. Cast is returned as a LIST (the API contract) — the DB stores
    it as a dict keyed by id for O(1) member lookups."""
    cast_dict = sb.cast or {}
    cast_list = list(cast_dict.values()) if isinstance(cast_dict, dict) else []
    versions_raw = sb.versions or []
    # Lightweight version index for the frontend — never echo the full
    # frame snapshots here (the dedicated /version/{n} endpoint loads
    # them on demand). Keep it cheap so /storyboard/latest stays small.
    versions_index: list[dict] = []
    for v in versions_raw:
        if not isinstance(v, dict):
            continue
        critique = v.get("critique") if isinstance(v.get("critique"), dict) else None
        versions_index.append(
            {
                "version_number": int(v.get("version_number") or 0),
                "video_url": v.get("video_url"),
                "summary": (critique or {}).get("summary"),
                "mutation_count": len(v.get("applied_mutations") or []),
                "created_at": v.get("created_at"),
            }
        )
    versions_index.sort(key=lambda x: x["version_number"])
    current_version = max(
        (v["version_number"] for v in versions_index), default=1
    )
    # Hydrate the targeted segment (when present) so the frontend can
    # show a "Targeted for: …" banner without a follow-up fetch. Live
    # re-aggregation picks up any newly-attached segment members.
    segment_payload: dict | None = None
    seg_id_attr = getattr(sb, "segment_id", None)
    if seg_id_attr:
        try:
            with SessionLocal() as db:
                seg = db.get(models.Segment, seg_id_attr)
                if seg is not None and seg.brand_id == sb.brand_id:
                    from app.services.audience.feature_usage import (
                        compute_segment_feature_stats,
                    )

                    stats = compute_segment_feature_stats(db, seg.id)
                    segment_payload = {
                        "id": seg.id,
                        "name": seg.name or "",
                        "description": seg.description or "",
                        "rationale": seg.rationale or "",
                        "size": len(seg.customer_ids or []),
                        "feature_focus": seg.feature_focus or stats["focus"],
                        "feature_stats": stats["stats"],
                        "contributor_counts": stats["contributor_counts"],
                    }
        except Exception:  # noqa: BLE001
            log.exception(
                "serialize_storyboard: failed to hydrate segment %s",
                seg_id_attr,
            )

    return {
        "storyboard_id": sb.id,
        "brand_id": sb.brand_id,
        "aspect": sb.aspect or "9:16",
        "narrative": sb.narrative or {},
        "cinematic_brief": sb.cinematic_brief or {},
        "voiceover": sb.voiceover or {},
        "title_card": sb.title_card,
        "end_card": sb.end_card,
        "cast": cast_list,
        "frames": list(sb.frames or []),
        "video_id": sb.video_id,
        "video_url": sb.video_url,
        "video_duration_ms": sb.video_duration_ms,
        "voiced_video_url": sb.voiced_video_url,
        "segment": segment_payload,
        "versions": versions_index,
        "current_version": current_version,
        "updated_at": sb.updated_at.isoformat() if sb.updated_at else None,
    }


# Module-level singleton — one registry per process.
registry = CastRegistry()


def auto_bind_brand_assets(
    brand: dict, cast: list[CastMember]
) -> list[CastMember]:
    """For each cast member with binding.type='brand_asset' + asset_index,
    validate the index against brand.assets and write canonical_url.

    Falls back to binding.type='needs_generation' (and no canonical_url)
    if the index is out of range.
    """
    assets: list[str] = list(brand.get("assets") or [])
    out: list[CastMember] = []
    for raw in cast:
        m: CastMember = dict(raw)  # type: ignore[assignment]
        binding = dict(m.get("binding") or {})
        if binding.get("type") == "brand_asset":
            idx = binding.get("asset_index")
            if isinstance(idx, int) and 0 <= idx < len(assets):
                m["canonical_url"] = assets[idx]
                m["binding"] = binding  # keep type+asset_index
            else:
                log.info(
                    "auto_bind: cast %s has invalid asset_index %s; "
                    "falling back to needs_generation",
                    m.get("id"),
                    idx,
                )
                m["binding"] = {"type": "needs_generation"}
                m["canonical_url"] = None
        else:
            if not binding:
                m["binding"] = {"type": "needs_generation"}
            else:
                m["binding"] = binding
            m.setdefault("canonical_url", None)
        out.append(m)
    return out
