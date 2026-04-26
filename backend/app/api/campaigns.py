from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db

router = APIRouter(prefix="/campaigns")


# ─── shared helpers ────────────────────────────────────────────────────────


def _channel_names(bundle: dict[str, Any] | None) -> list[str]:
    """Extract a stable list of channel ids from a campaign bundle. Drafts
    are the canonical source — older bundles may also carry blog/social
    siblings, which we surface so the Campaigns page can show their pills."""
    if not isinstance(bundle, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for d in bundle.get("drafts") or []:
        if isinstance(d, dict):
            ch = (d.get("channel") or "").strip()
            if ch and ch not in seen:
                seen.add(ch)
                out.append(ch)
    if isinstance(bundle.get("blog"), dict) and "blog" not in seen:
        seen.add("blog")
        out.append("blog")
    if isinstance(bundle.get("social"), dict) and "linkedin" not in seen:
        seen.add("linkedin")
        out.append("linkedin")
    return out


def _lift_band(lift: float | None) -> str:
    """Bucket a predicted lift into one of four tiers used by the UI's
    filter chips. Tiers are inclusive on the lower bound."""
    if lift is None:
        return "unknown"
    if lift >= 25:
        return "breakout"
    if lift >= 10:
        return "strong"
    if lift >= 0:
        return "modest"
    return "negative"


# ─── recent runs (legacy — kept for the dashboard's RecentRuns list) ───────


class RecentRun(BaseModel):
    id: str
    brand_id: str
    title: str
    predicted_lift: float | None
    created_at: str


@router.get("/recent", response_model=list[RecentRun])
def recent(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 10,
) -> list[RecentRun]:
    rows = (
        db.query(models.Campaign)
        .filter(models.Campaign.brand_id == brand_id)
        .order_by(models.Campaign.created_at.desc())
        .limit(max(1, min(50, limit)))
        .all()
    )
    return [
        RecentRun(
            id=c.id,
            brand_id=c.brand_id,
            title=c.title,
            predicted_lift=c.predicted_lift,
            created_at=c.created_at.isoformat(),
        )
        for c in rows
    ]


# ─── full campaigns library ────────────────────────────────────────────────


class CampaignListItem(BaseModel):
    id: str
    brand_id: str
    title: str
    predicted_lift: float | None
    lift_band: str
    confidence: str | None
    created_at: str
    channels: list[str]
    hero_image_url: str | None
    draft_count: int
    has_blog: bool
    target_prompts: list[str]


class CampaignListResponse(BaseModel):
    items: list[CampaignListItem]
    total: int
    offset: int
    limit: int


@router.get("/list", response_model=CampaignListResponse)
def list_campaigns(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    channel: str | None = Query(None, description="Filter by channel id present in bundle drafts"),
    band: str | None = Query(
        None,
        description="Filter by lift band: breakout|strong|modest|negative|unknown",
    ),
    sort: str = Query("recent", description="recent|oldest|lift_desc|lift_asc|alpha"),
    offset: int = 0,
    limit: int = 24,
) -> CampaignListResponse:
    """Paginated, filterable campaign listing. Filtering on bundle-derived
    fields (channel, band) happens in Python because they live inside the
    JSON column — the brand-scoped row count is small enough that this is
    cheaper than a JSON expression that won't index either way."""
    base = db.query(models.Campaign).filter(models.Campaign.brand_id == brand_id)
    rows = base.all()

    items: list[tuple[CampaignListItem, models.Campaign]] = []
    for c in rows:
        bundle = c.bundle or {}
        channels = _channel_names(bundle)
        if channel and channel not in channels:
            continue
        lift_val = c.predicted_lift
        if lift_val is None:
            pl = bundle.get("predicted_lift") if isinstance(bundle, dict) else None
            if isinstance(pl, dict):
                v = pl.get("lift_percent")
                if isinstance(v, (int, float)):
                    lift_val = float(v)
        bnd = _lift_band(lift_val)
        if band and band != bnd:
            continue
        if q:
            ql = q.lower()
            blob = " ".join(
                [
                    c.title or "",
                    str(bundle.get("user_request") or ""),
                    " ".join(channels),
                ]
            ).lower()
            if ql not in blob:
                continue
        confidence = None
        if isinstance(bundle, dict):
            pl = bundle.get("predicted_lift")
            if isinstance(pl, dict):
                cv = pl.get("confidence")
                if isinstance(cv, str):
                    confidence = cv
        targets = []
        if isinstance(bundle, dict):
            tp = bundle.get("target_prompts")
            if isinstance(tp, list):
                targets = [str(x) for x in tp][:6]
        item = CampaignListItem(
            id=c.id,
            brand_id=c.brand_id,
            title=c.title,
            predicted_lift=lift_val,
            lift_band=bnd,
            confidence=confidence,
            created_at=c.created_at.isoformat(),
            channels=channels,
            hero_image_url=(
                bundle.get("hero_image_url") if isinstance(bundle, dict) else None
            ),
            draft_count=len(bundle.get("drafts") or []) if isinstance(bundle, dict) else 0,
            has_blog=isinstance(bundle.get("blog"), dict) if isinstance(bundle, dict) else False,
            target_prompts=targets,
        )
        items.append((item, c))

    if sort == "oldest":
        items.sort(key=lambda t: t[1].created_at)
    elif sort == "lift_desc":
        items.sort(
            key=lambda t: (t[0].predicted_lift if t[0].predicted_lift is not None else -9999),
            reverse=True,
        )
    elif sort == "lift_asc":
        items.sort(
            key=lambda t: (t[0].predicted_lift if t[0].predicted_lift is not None else 9999),
        )
    elif sort == "alpha":
        items.sort(key=lambda t: (t[0].title or "").lower())
    else:
        items.sort(key=lambda t: t[1].created_at, reverse=True)

    total = len(items)
    page = items[max(0, offset) : max(0, offset) + max(1, min(100, limit))]
    return CampaignListResponse(
        items=[i for i, _ in page],
        total=total,
        offset=max(0, offset),
        limit=max(1, min(100, limit)),
    )


# ─── aggregate stats hero ──────────────────────────────────────────────────


class LiftBandSlice(BaseModel):
    band: str
    count: int


class ChannelSlice(BaseModel):
    channel: str
    count: int


class TimelineBucket(BaseModel):
    iso: str
    count: int
    avg_lift: float | None


class CampaignStats(BaseModel):
    total: int
    last_7_days: int
    last_30_days: int
    avg_lift: float | None
    median_lift: float | None
    best_lift: float | None
    best_id: str | None
    best_title: str | None
    bundled_share: float
    bands: list[LiftBandSlice]
    channels: list[ChannelSlice]
    timeline: list[TimelineBucket]


@router.get("/stats", response_model=CampaignStats)
def stats(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    window_days: int = Query(56, description="Timeline window in days (default 8 weeks)"),
) -> CampaignStats:
    rows = (
        db.query(models.Campaign)
        .filter(models.Campaign.brand_id == brand_id)
        .all()
    )
    now = datetime.now(timezone.utc)
    seven = now - timedelta(days=7)
    thirty = now - timedelta(days=30)
    cutoff = now - timedelta(days=max(7, window_days))

    last7 = 0
    last30 = 0
    lifts: list[float] = []
    band_counts: dict[str, int] = {
        "breakout": 0,
        "strong": 0,
        "modest": 0,
        "negative": 0,
        "unknown": 0,
    }
    channel_counts: dict[str, int] = {}
    bundled = 0
    best: tuple[float, str, str] | None = None
    week_keys: list[str] = []
    week_buckets: dict[str, list[float]] = {}
    week_count: dict[str, int] = {}

    # Pre-compute a stable list of week ISO labels covering the window so
    # the timeline always has continuous bars even when no campaigns landed
    # in a given week.
    span_weeks = max(1, (window_days + 6) // 7)
    for i in range(span_weeks):
        d = now - timedelta(days=i * 7)
        iso = d.date().isoformat()
        week_keys.append(iso)
        week_buckets[iso] = []
        week_count[iso] = 0
    week_keys.reverse()

    def _week_key(d: datetime) -> str:
        for i in range(len(week_keys)):
            anchor = datetime.fromisoformat(week_keys[i]).replace(tzinfo=timezone.utc)
            next_anchor = (
                datetime.fromisoformat(week_keys[i + 1]).replace(tzinfo=timezone.utc)
                if i + 1 < len(week_keys)
                else now + timedelta(days=7)
            )
            if anchor <= d < next_anchor:
                return week_keys[i]
        return week_keys[-1]

    for c in rows:
        ts = c.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= seven:
            last7 += 1
        if ts >= thirty:
            last30 += 1
        lift = c.predicted_lift
        bundle = c.bundle or {}
        if lift is None and isinstance(bundle, dict):
            pl = bundle.get("predicted_lift")
            if isinstance(pl, dict):
                v = pl.get("lift_percent")
                if isinstance(v, (int, float)):
                    lift = float(v)
        if lift is not None:
            lifts.append(lift)
            bundled += 1
            if best is None or lift > best[0]:
                best = (lift, c.id, c.title or "Campaign")
        band = _lift_band(lift)
        band_counts[band] = band_counts.get(band, 0) + 1
        for ch in _channel_names(bundle):
            channel_counts[ch] = channel_counts.get(ch, 0) + 1
        if ts >= cutoff:
            wk = _week_key(ts)
            week_count[wk] = week_count.get(wk, 0) + 1
            if lift is not None:
                week_buckets[wk].append(lift)

    avg = sum(lifts) / len(lifts) if lifts else None
    median: float | None = None
    if lifts:
        srt = sorted(lifts)
        mid = len(srt) // 2
        median = srt[mid] if len(srt) % 2 == 1 else (srt[mid - 1] + srt[mid]) / 2
    bundled_share = (bundled / len(rows)) if rows else 0.0

    timeline = [
        TimelineBucket(
            iso=k,
            count=week_count.get(k, 0),
            avg_lift=(sum(week_buckets[k]) / len(week_buckets[k]))
            if week_buckets[k]
            else None,
        )
        for k in week_keys
    ]

    bands = [LiftBandSlice(band=b, count=n) for b, n in band_counts.items() if n > 0]
    channels = sorted(
        [ChannelSlice(channel=c, count=n) for c, n in channel_counts.items()],
        key=lambda s: s.count,
        reverse=True,
    )

    # SQLAlchemy func.count is just to silence the unused import on some
    # lints — real counts come from the iteration above.
    _ = func.count

    return CampaignStats(
        total=len(rows),
        last_7_days=last7,
        last_30_days=last30,
        avg_lift=avg,
        median_lift=median,
        best_lift=best[0] if best else None,
        best_id=best[1] if best else None,
        best_title=best[2] if best else None,
        bundled_share=bundled_share,
        bands=bands,
        channels=channels,
        timeline=timeline,
    )


# ─── single-campaign detail / mutate ───────────────────────────────────────


class CampaignDetail(BaseModel):
    id: str
    brand_id: str
    title: str
    predicted_lift: float | None
    created_at: str
    bundle: dict[str, Any]


@router.get("/{campaign_id}", response_model=CampaignDetail)
def detail(
    campaign_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> CampaignDetail:
    """Full campaign incl. the bundle JSON. Used by the dashboard's
    Recent Runs list to restore a past session into the agent panel."""
    c = db.get(models.Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return CampaignDetail(
        id=c.id,
        brand_id=c.brand_id,
        title=c.title,
        predicted_lift=c.predicted_lift,
        created_at=c.created_at.isoformat(),
        bundle=c.bundle or {},
    )


class DeleteResponse(BaseModel):
    deleted: str


@router.delete("/{campaign_id}", response_model=DeleteResponse)
def delete_campaign(
    campaign_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> DeleteResponse:
    c = db.get(models.Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    db.delete(c)
    db.commit()
    return DeleteResponse(deleted=campaign_id)


@router.post("/{campaign_id}/duplicate", response_model=CampaignDetail)
def duplicate(
    campaign_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> CampaignDetail:
    """Clone an existing campaign so the user can rerun / fork it without
    blowing away the original. The bundle is copied as-is so all drafts and
    the hero image come along; only the title gets a `(copy)` suffix."""
    src = db.get(models.Campaign, campaign_id)
    if src is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    new = models.Campaign(
        id=str(uuid4()),
        brand_id=src.brand_id,
        title=f"{src.title} (copy)",
        bundle=src.bundle or {},
        predicted_lift=src.predicted_lift,
    )
    db.add(new)
    db.commit()
    db.refresh(new)
    return CampaignDetail(
        id=new.id,
        brand_id=new.brand_id,
        title=new.title,
        predicted_lift=new.predicted_lift,
        created_at=new.created_at.isoformat(),
        bundle=new.bundle or {},
    )
