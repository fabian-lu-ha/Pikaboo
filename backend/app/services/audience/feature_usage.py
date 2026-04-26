"""Feature-usage analytics for the audience.

Aggregates ``CustomerEvent`` rows whose ``kind == 'feature_use'`` and whose
``payload['feature']`` names a product feature, then exposes three views:

  - per-customer top features (``compute_customer_top_features``)
  - brand-wide feature distribution (``compute_brand_feature_distribution``)
  - per-segment feature stats (``compute_segment_feature_stats``)

These power three things downstream:

  1. The audience analytics surface — "what features does our audience
     actually use?"
  2. Feature-driven segmentation — segmentation.py reads per-customer
     top features as a signal so it can propose "Heavy users of feature X"
     segments.
  3. Segment-aware storyboard generation — when ``/api/video/suggest`` is
     called with a ``segment_id``, the planner reads the segment's
     ``feature_focus`` and threads it through the cinematic_brief, frame
     prompts, and voiceover script so different segments get different
     videos.

Convention: ``CustomerEvent.kind = 'feature_use'``,
``CustomerEvent.payload = {'feature': 'analytics_dashboard', ...optional}``.
The 'feature' key is the only thing this module relies on; everything else
is metadata the caller can include for their own bookkeeping.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.db import models

log = logging.getLogger(__name__)

# Convention: every event whose kind matches gets aggregated. We accept
# both ``feature_use`` (forward-compatible) and the legacy ``feature``
# alias used by some demo seeders.
FEATURE_EVENT_KINDS: tuple[str, ...] = ("feature_use", "feature")


def _feature_of(e: "models.CustomerEvent") -> str | None:
    """Pull the feature name out of a CustomerEvent. None when the row
    isn't a feature_use event or its payload lacks a usable name."""
    if e.kind not in FEATURE_EVENT_KINDS:
        return None
    payload = e.payload or {}
    name = payload.get("feature") or payload.get("name") or payload.get("key")
    if not isinstance(name, str):
        return None
    return name.strip() or None


def track_feature(
    db: Session,
    *,
    brand_id: str,
    customer_id: str,
    feature: str,
    properties: dict | None = None,
    occurred_at: datetime | None = None,
) -> models.CustomerEvent | None:
    """Convenience writer — emits a CustomerEvent that the aggregators
    will pick up. Returns None when brand or customer don't exist (so
    the caller can decide to log; we never raise)."""
    feature = (feature or "").strip()
    if not feature or not brand_id or not customer_id:
        return None
    payload = {"feature": feature, **(properties or {})}
    row = models.CustomerEvent(
        brand_id=brand_id,
        customer_id=customer_id,
        kind="feature_use",
        occurred_at=occurred_at or datetime.now(timezone.utc),
        payload=payload,
    )
    db.add(row)
    db.flush()  # let the caller decide whether to commit
    return row


def compute_customer_top_features(
    db: Session,
    customer_id: str,
    *,
    limit: int = 5,
) -> list[dict]:
    """Return the customer's most-used features, newest-event first as
    tiebreaker. Each entry is ``{feature, count, last_used}``."""
    if not customer_id:
        return []
    events = (
        db.query(models.CustomerEvent)
        .filter(
            models.CustomerEvent.customer_id == customer_id,
            models.CustomerEvent.kind.in_(FEATURE_EVENT_KINDS),
        )
        .all()
    )
    counter: Counter[str] = Counter()
    last_seen: dict[str, datetime] = {}
    for e in events:
        f = _feature_of(e)
        if not f:
            continue
        counter[f] += 1
        prev = last_seen.get(f)
        if prev is None or (e.occurred_at and e.occurred_at > prev):
            last_seen[f] = e.occurred_at
    out: list[dict] = []
    for feature, count in counter.most_common(limit):
        ts = last_seen.get(feature)
        out.append(
            {
                "feature": feature,
                "count": count,
                "last_used": ts.isoformat() if ts else None,
            }
        )
    return out


def compute_brand_feature_distribution(
    db: Session,
    brand_id: str,
) -> list[dict]:
    """Brand-wide rollup. For each feature, returns ``{feature,
    customer_count, event_count, last_seen}``. Sorted by customer_count
    desc — the planner uses this to decide whether a feature has a
    large-enough cohort to be a video subject."""
    if not brand_id:
        return []
    events = (
        db.query(models.CustomerEvent)
        .filter(
            models.CustomerEvent.brand_id == brand_id,
            models.CustomerEvent.kind.in_(FEATURE_EVENT_KINDS),
        )
        .all()
    )
    customers_per_feature: dict[str, set[str]] = defaultdict(set)
    events_per_feature: Counter[str] = Counter()
    last_seen: dict[str, datetime] = {}
    for e in events:
        f = _feature_of(e)
        if not f:
            continue
        events_per_feature[f] += 1
        customers_per_feature[f].add(e.customer_id)
        prev = last_seen.get(f)
        if prev is None or (e.occurred_at and e.occurred_at > prev):
            last_seen[f] = e.occurred_at
    out: list[dict] = []
    for feature, ec in events_per_feature.most_common():
        ts = last_seen.get(feature)
        out.append(
            {
                "feature": feature,
                "customer_count": len(customers_per_feature[feature]),
                "event_count": ec,
                "last_seen": ts.isoformat() if ts else None,
            }
        )
    # Re-sort by customer_count desc — most-common-feature isn't always
    # the same as most-customers-using-it (one heavy user can skew
    # event counts).
    out.sort(key=lambda r: (r["customer_count"], r["event_count"]), reverse=True)
    return out


def compute_segment_feature_stats(
    db: Session,
    segment_id: str,
) -> dict:
    """Aggregate feature usage across the customers in a segment.

    Returns ``{focus: <single dominant feature or None>,
                stats: {feature: event_count, ...},
                contributor_counts: {feature: customers_with_it, ...}}``.

    The dominant feature is the one with the most distinct customers using
    it (ties broken by event count). When no segment member has any
    feature events, returns ``{focus: None, stats: {}, ...}``.
    """
    if not segment_id:
        return {"focus": None, "stats": {}, "contributor_counts": {}}
    seg = db.get(models.Segment, segment_id)
    if seg is None:
        return {"focus": None, "stats": {}, "contributor_counts": {}}
    member_ids: list[str] = list(seg.customer_ids or [])
    if not member_ids:
        return {"focus": None, "stats": {}, "contributor_counts": {}}

    rows = (
        db.query(models.CustomerEvent)
        .filter(
            models.CustomerEvent.brand_id == seg.brand_id,
            models.CustomerEvent.customer_id.in_(member_ids),
            models.CustomerEvent.kind.in_(FEATURE_EVENT_KINDS),
        )
        .all()
    )
    events_per_feature: Counter[str] = Counter()
    customers_per_feature: dict[str, set[str]] = defaultdict(set)
    for e in rows:
        f = _feature_of(e)
        if not f:
            continue
        events_per_feature[f] += 1
        customers_per_feature[f].add(e.customer_id)

    if not events_per_feature:
        return {"focus": None, "stats": {}, "contributor_counts": {}}

    # Pick the focus: most distinct customers, tie-break by event count.
    ranked = sorted(
        events_per_feature.keys(),
        key=lambda f: (
            len(customers_per_feature[f]),
            events_per_feature[f],
        ),
        reverse=True,
    )
    focus = ranked[0]
    return {
        "focus": focus,
        "stats": dict(events_per_feature),
        "contributor_counts": {
            f: len(customers_per_feature[f]) for f in events_per_feature
        },
    }


def attach_segment_feature_focus(
    db: Session,
    segment_id: str,
    *,
    commit: bool = True,
) -> dict:
    """Compute feature stats for a segment and persist them on the
    Segment row (``feature_focus`` + ``feature_stats``). Returns the
    same shape ``compute_segment_feature_stats`` does."""
    stats = compute_segment_feature_stats(db, segment_id)
    seg = db.get(models.Segment, segment_id)
    if seg is None:
        return stats
    seg.feature_focus = stats["focus"]
    seg.feature_stats = {
        "events": stats["stats"],
        "contributors": stats["contributor_counts"],
    }
    if commit:
        db.commit()
    return stats


def bulk_track_features(
    db: Session,
    brand_id: str,
    rows: Iterable[dict],
) -> int:
    """Demo / webhook ingestion path. Each row: ``{customer_id, feature,
    occurred_at?, properties?}``. Returns the count of events written."""
    if not brand_id:
        return 0
    written = 0
    for r in rows:
        cid = r.get("customer_id")
        feat = r.get("feature")
        if not cid or not feat:
            continue
        ts = r.get("occurred_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        elif not isinstance(ts, datetime):
            ts = None
        track_feature(
            db,
            brand_id=brand_id,
            customer_id=str(cid),
            feature=str(feat),
            properties=r.get("properties") if isinstance(r.get("properties"), dict) else None,
            occurred_at=ts,
        )
        written += 1
    if written:
        db.commit()
    return written
