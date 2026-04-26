"""Analytics overview API.

Exposes a single composite endpoint ``GET /api/analytics/overview`` that
the Analytics dashboard reads. Pulls from real sources only:

  - **Peec** (REST or MCP, whichever is wired up) — visibility, share-of-voice,
    sentiment, prompts where the brand is winning vs. absent, brands report
    rows for tracked competitors.
  - **DB** — customers acquired in the window (signup_at), email sends, campaign
    runs, kanban activity. These power Growth Trajectory and the data-source
    chips even when Peec is offline.
  - **Gemini** — turns the above structured signals into a short executive
    synthesis (summary + 3 recommended actions). When the LLM call fails we
    omit the synthesis section rather than fabricate one.

The response always tells the caller which sources were available
(``data_sources``) so the UI can render appropriate empty states instead of
inventing numbers.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.services.llm.client import chat_json
from app.services.peec.snapshot import PeecSnapshot, fetch_snapshot

log = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics")

Window = Literal["90D", "6M", "1Y"]


# ----------------------------------------------------------- response schemas


class MarketPosition(BaseModel):
    score: float | None
    delta: float | None
    percentile: int | None
    share_of_voice: float | None
    sentiment: float | None
    explanation: str


class TrajectoryBucket(BaseModel):
    label: str
    value: int
    iso: str


class GrowthTrajectory(BaseModel):
    metric: str
    metric_label: str
    buckets: list[TrajectoryBucket]
    total: int
    delta_pct: float | None


class CompetitorRow(BaseModel):
    id: str
    name: str
    url: str | None
    visibility: float | None
    share_of_voice: float | None
    delta: float | None
    rank_label: str
    has_peec_data: bool


class EngineBreakdown(BaseModel):
    engine: str
    label: str
    visibility: float | None
    share_of_voice: float | None
    rank: int | None
    sample_count: int | None


class CitationRow(BaseModel):
    domain: str
    citation_count: int | None
    rank: int | None
    favicon_url: str | None


class PromptDrillDown(BaseModel):
    prompt: str
    own_rank: int | None
    own_visibility: float | None
    winner: str | None
    winner_visibility: float | None
    engines: list[str]
    cited_domains: list[str]
    last_seen_at: str | None


class SynthesisAction(BaseModel):
    label: str
    rationale: str


class AISynthesis(BaseModel):
    summary: str
    actions: list[SynthesisAction]
    top_competitor: str | None
    absent_prompts: list[str]


class DataSources(BaseModel):
    peec: Literal["connected", "no_data", "not_configured"]
    # Which transport actually answered the snapshot. mcp = OAuth-backed
    # MCP session (the contest-credible path); rest = x-api-key REST
    # fallback; none = no source available. Surfaced in the dashboard's
    # data-sources strip so the user can verify MCP is live.
    peec_transport: Literal["mcp", "rest", "none"]
    customers_count: int
    campaigns_count: int
    email_sends_count: int


class AnalyticsOverview(BaseModel):
    brand_id: str
    brand_name: str
    window: Window
    fetched_at: str
    market_position: MarketPosition | None
    growth_trajectory: GrowthTrajectory
    competitor_radar: list[CompetitorRow]
    engine_breakdown: list[EngineBreakdown]
    citations: list[CitationRow]
    prompt_drilldown: list[PromptDrillDown]
    ai_synthesis: AISynthesis | None
    data_sources: DataSources


# --------------------------------------------------------------- window math


def _window_days(window: Window) -> int:
    return {"90D": 90, "6M": 183, "1Y": 365}[window]


def _bucket_count(window: Window) -> int:
    # 90D → 6 fortnight buckets, 6M → 6 months, 1Y → 12 months
    return {"90D": 6, "6M": 6, "1Y": 12}[window]


def _bucket_label(start: datetime, window: Window) -> str:
    if window == "90D":
        return start.strftime("%b %d")
    return start.strftime("%b")


def _bucket_starts(window: Window) -> list[datetime]:
    """Return ascending bucket start times (UTC) covering the window."""
    now = datetime.now(timezone.utc)
    n = _bucket_count(window)
    days = _window_days(window)
    step = timedelta(days=days // n)
    starts: list[datetime] = []
    cursor = now - step * n
    for _ in range(n):
        starts.append(cursor)
        cursor = cursor + step
    return starts


# ------------------------------------------------------------ growth metric


def _compute_growth(
    db: Session,
    brand_id: str,
    window: Window,
    snap: PeecSnapshot | None = None,
) -> tuple[GrowthTrajectory, int, int, int]:
    """Pick the most informative metric the brand actually has and bucket it.

    Priority: Peec visibility timeseries → customer signups → email sends →
    campaign runs → kanban moves. Empty windows still return zero-buckets so
    the UI can paint axes.
    """
    # Prefer real Peec visibility timeseries when present — that's the
    # number users actually came to the analytics page to see.
    if snap is not None and snap.history:
        peec_traj = _peec_history_to_trajectory(snap.history, window)
        if peec_traj is not None:
            customers_count = (
                db.query(func.count(models.Customer.id))
                .filter(models.Customer.brand_id == brand_id)
                .scalar()
                or 0
            )
            campaigns_count = (
                db.query(func.count(models.Campaign.id))
                .filter(models.Campaign.brand_id == brand_id)
                .scalar()
                or 0
            )
            email_sends_count = (
                db.query(func.count(models.EmailSend.id))
                .filter(models.EmailSend.brand_id == brand_id)
                .scalar()
                or 0
            )
            return (
                peec_traj,
                customers_count,
                campaigns_count,
                email_sends_count,
            )
    starts = _bucket_starts(window)
    end = datetime.now(timezone.utc)
    boundaries = starts + [end]

    customers_count = (
        db.query(func.count(models.Customer.id))
        .filter(models.Customer.brand_id == brand_id)
        .scalar()
        or 0
    )
    campaigns_count = (
        db.query(func.count(models.Campaign.id))
        .filter(models.Campaign.brand_id == brand_id)
        .scalar()
        or 0
    )
    email_sends_count = (
        db.query(func.count(models.EmailSend.id))
        .filter(models.EmailSend.brand_id == brand_id)
        .scalar()
        or 0
    )

    customer_signups = (
        db.query(models.Customer.signup_at)
        .filter(
            models.Customer.brand_id == brand_id,
            models.Customer.signup_at.isnot(None),
            models.Customer.signup_at >= boundaries[0],
        )
        .all()
    )
    email_send_dates = (
        db.query(models.EmailSend.created_at)
        .filter(
            models.EmailSend.brand_id == brand_id,
            models.EmailSend.created_at >= boundaries[0],
        )
        .all()
    )
    campaign_dates = (
        db.query(models.Campaign.created_at)
        .filter(
            models.Campaign.brand_id == brand_id,
            models.Campaign.created_at >= boundaries[0],
        )
        .all()
    )
    kanban_moves = (
        db.query(models.KanbanCard.moved_at)
        .filter(
            models.KanbanCard.brand_id == brand_id,
            models.KanbanCard.moved_at.isnot(None),
            models.KanbanCard.moved_at >= boundaries[0],
        )
        .all()
    )

    candidates: list[tuple[str, str, list[datetime]]] = [
        (
            "new_customers",
            "New Customers",
            [r[0] for r in customer_signups if r[0]],
        ),
        (
            "email_sends",
            "Email Sends",
            [r[0] for r in email_send_dates if r[0]],
        ),
        (
            "campaigns_run",
            "Campaign Runs",
            [r[0] for r in campaign_dates if r[0]],
        ),
        (
            "kanban_activity",
            "Kanban Moves",
            [r[0] for r in kanban_moves if r[0]],
        ),
    ]
    metric_key, metric_label, dates = next(
        ((k, l, d) for k, l, d in candidates if d),
        ("new_customers", "New Customers", []),
    )

    buckets = _bucket_dates(dates, boundaries, window)
    total = sum(b.value for b in buckets)

    half = len(buckets) // 2
    first_half = sum(b.value for b in buckets[:half]) if half else 0
    second_half = (
        sum(b.value for b in buckets[half:]) if len(buckets) > half else 0
    )
    delta_pct: float | None = None
    if first_half > 0:
        delta_pct = ((second_half - first_half) / first_half) * 100.0
    elif second_half > 0:
        delta_pct = 100.0

    return (
        GrowthTrajectory(
            metric=metric_key,
            metric_label=metric_label,
            buckets=buckets,
            total=total,
            delta_pct=delta_pct,
        ),
        customers_count,
        campaigns_count,
        email_sends_count,
    )


def _peec_history_to_trajectory(
    history: list, window: Window
) -> GrowthTrajectory | None:
    """Bucket Peec history points into the current window. Returns None if
    Peec history doesn't have any usable points for this window."""
    points: list[tuple[datetime, float]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_window_days(window))
    for h in history:
        try:
            dt = datetime.fromisoformat(h.date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff:
            continue
        if h.visibility is None:
            continue
        points.append((dt, float(h.visibility)))
    if len(points) < 2:
        return None
    points.sort(key=lambda p: p[0])

    n = _bucket_count(window)
    starts = _bucket_starts(window)
    end = datetime.now(timezone.utc)
    boundaries = starts + [end]
    buckets: list[TrajectoryBucket] = []
    for i in range(len(boundaries) - 1):
        start, stop = boundaries[i], boundaries[i + 1]
        in_bucket = [v for (d, v) in points if start <= d < stop]
        avg = sum(in_bucket) / len(in_bucket) if in_bucket else 0
        buckets.append(
            TrajectoryBucket(
                label=_bucket_label(start, window),
                value=int(round(avg)),
                iso=start.isoformat(),
            )
        )
    if all(b.value == 0 for b in buckets):
        return None

    half = n // 2
    first_half_pts = [v for (d, v) in points if d < boundaries[half]] if half else []
    second_half_pts = [v for (d, v) in points if d >= boundaries[half]]
    delta_pct: float | None = None
    if first_half_pts and second_half_pts:
        a = sum(first_half_pts) / len(first_half_pts)
        b = sum(second_half_pts) / len(second_half_pts)
        if a > 0:
            delta_pct = ((b - a) / a) * 100.0

    total = int(round(sum(v for _, v in points) / len(points)))
    return GrowthTrajectory(
        metric="peec_visibility",
        metric_label="Visibility (Peec)",
        buckets=buckets,
        total=total,
        delta_pct=delta_pct,
    )


def _bucket_dates(
    dates: list[datetime],
    boundaries: list[datetime],
    window: Window,
) -> list[TrajectoryBucket]:
    if len(boundaries) < 2:
        return []
    # Normalize datetimes to UTC for the < comparisons below.
    norm: list[datetime] = []
    for d in dates:
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        norm.append(d)

    out: list[TrajectoryBucket] = []
    for i in range(len(boundaries) - 1):
        start, stop = boundaries[i], boundaries[i + 1]
        count = sum(1 for d in norm if start <= d < stop)
        out.append(
            TrajectoryBucket(
                label=_bucket_label(start, window),
                value=count,
                iso=start.isoformat(),
            )
        )
    return out


# ---------------------------------------------------------- market position


def _compute_market_position(
    snap: PeecSnapshot | None,
) -> MarketPosition | None:
    if snap is None or (
        snap.visibility is None
        and snap.share_of_voice is None
        and snap.sentiment is None
    ):
        return None
    score = snap.visibility
    if score is None and snap.share_of_voice is not None:
        score = snap.share_of_voice
    visible_count = len(snap.visible_on)
    absent_count = len(snap.absent_from)
    total = visible_count + absent_count
    explanation = (
        f"Visibility across {total} tracked prompts · top in {visible_count}"
        if total
        else "Composite visibility from connected Peec project."
    )
    percentile: int | None = None
    if snap.share_of_voice is not None:
        # Peec returns share-of-voice as 0-100; convert to a top-X% bucket
        # that matches the dashboard's UI conceit. 50% SoV → top 50% of voice.
        percentile = max(2, min(99, int(round(100 - snap.share_of_voice))))
    return MarketPosition(
        score=score,
        delta=None,  # Peec doesn't expose historical visibility on read; leave null.
        percentile=percentile,
        share_of_voice=snap.share_of_voice,
        sentiment=snap.sentiment,
        explanation=explanation,
    )


# --------------------------------------------------------- competitor radar


def _compute_competitor_radar(
    brand: models.Brand, snap: PeecSnapshot | None
) -> list[CompetitorRow]:
    rows: list[CompetitorRow] = []

    peec_index: dict[str, dict[str, Any]] = {}
    if snap is not None:
        # First-class source: brands_report rows for each competitor have
        # real visibility / SoV / sentiment numbers per brand. Index those.
        for c in snap.competitors:
            name = (c.get("name") or "").strip()
            if not name:
                continue
            peec_index[name.lower()] = {
                "visibility": c.get("visibility"),
                "share_of_voice": c.get("share_of_voice"),
                "sentiment": c.get("sentiment"),
                "wins": 0,
                "from_report": True,
            }

        # Fallback: aggregate competitor "wins" per absent prompt for any
        # competitor we didn't see in brands_report.
        win_counts: Counter[str] = Counter()
        for ap in snap.absent_from:
            if ap.competitor_winning:
                win_counts[ap.competitor_winning.lower()] += 1
        max_wins = max(win_counts.values()) if win_counts else 0

        for ap in snap.absent_from:
            if not ap.competitor_winning:
                continue
            key = ap.competitor_winning.lower()
            entry = peec_index.get(key)
            if entry:
                entry["wins"] = win_counts.get(key, 0)
                continue
            wins = win_counts.get(key, 0)
            visibility = ap.competitor_visibility
            if visibility is None and max_wins > 0:
                visibility = (wins / max_wins) * 100.0
            peec_index[key] = {
                "visibility": visibility,
                "share_of_voice": None,
                "sentiment": None,
                "wins": wins,
                "from_report": False,
            }

    competitors = brand.competitors or []
    for c in competitors:
        key = (c.name or "").lower()
        peec = peec_index.get(key)
        rows.append(
            CompetitorRow(
                id=c.id,
                name=c.name,
                url=c.url,
                visibility=peec["visibility"] if peec else None,
                share_of_voice=peec["share_of_voice"] if peec else None,
                delta=None,
                rank_label=_rank_label(peec, c),
                has_peec_data=peec is not None,
            )
        )

    rows.sort(
        key=lambda r: (r.has_peec_data is False, -(r.visibility or 0.0))
    )
    return rows


def _rank_label(
    peec: dict[str, Any] | None, _competitor: models.Competitor
) -> str:
    if peec is None:
        return "Tracked Brand"
    wins = peec.get("wins") or 0
    if wins >= 5:
        return "Direct Competitor"
    if wins >= 1:
        return "Emerging Threat"
    return "Tracked Brand"


# ------------------------------------------------------ engines / citations


def _compute_engines(snap: PeecSnapshot | None) -> list[EngineBreakdown]:
    if snap is None or not snap.engines:
        return []
    out: list[EngineBreakdown] = []
    for e in snap.engines[:8]:
        out.append(
            EngineBreakdown(
                engine=e.engine,
                label=e.label,
                visibility=e.visibility,
                share_of_voice=e.share_of_voice,
                rank=e.rank,
                sample_count=e.sample_count,
            )
        )
    out.sort(
        key=lambda e: -(e.visibility if e.visibility is not None else -1)
    )
    return out


def _compute_citations(snap: PeecSnapshot | None) -> list[CitationRow]:
    if snap is None:
        return []
    return [
        CitationRow(
            domain=c.domain,
            citation_count=c.citation_count,
            rank=c.rank,
            favicon_url=c.favicon_url,
        )
        for c in snap.cited_domains[:12]
        if c.domain
    ]


def _compute_prompt_drilldown(
    snap: PeecSnapshot | None,
) -> list[PromptDrillDown]:
    if snap is None or not snap.prompt_details:
        return []
    out: list[PromptDrillDown] = []
    for p in snap.prompt_details[:25]:
        out.append(
            PromptDrillDown(
                prompt=p.prompt,
                own_rank=p.own_rank,
                own_visibility=p.own_visibility,
                winner=p.winner,
                winner_visibility=p.winner_visibility,
                engines=p.engines,
                cited_domains=p.cited_domains,
                last_seen_at=p.last_seen_at,
            )
        )
    return out


# ------------------------------------------------------------- AI synthesis


_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["label", "rationale"],
            },
        },
    },
    "required": ["summary", "actions"],
}


async def _generate_ai_synthesis(
    brand: models.Brand,
    snap: PeecSnapshot | None,
    growth: GrowthTrajectory,
    competitors: list[CompetitorRow],
) -> AISynthesis | None:
    """Ask Gemini for a short summary + 3 recommended actions, grounded in the
    real numbers we just computed. Returns None if Gemini errors out — the
    caller renders an empty state rather than fabricated copy."""
    facts: dict[str, Any] = {
        "brand": {"name": brand.name, "url": brand.url},
        "window": growth.metric,
        "growth_metric": growth.metric_label,
        "growth_total": growth.total,
        "growth_delta_pct": growth.delta_pct,
        "competitors": [
            {
                "name": c.name,
                "visibility": c.visibility,
                "rank_label": c.rank_label,
                "has_peec_data": c.has_peec_data,
            }
            for c in competitors[:6]
        ],
    }
    if snap is not None:
        facts["peec"] = {
            "visibility": snap.visibility,
            "share_of_voice": snap.share_of_voice,
            "sentiment": snap.sentiment,
            "visible_on": [v.prompt for v in snap.visible_on[:5]],
            "absent_from": [
                {
                    "prompt": a.prompt,
                    "winner": a.competitor_winning,
                }
                for a in snap.absent_from[:5]
            ],
            "cited_domains": [c.domain for c in snap.cited_domains[:5]],
            "engines": [
                {
                    "label": e.label,
                    "visibility": e.visibility,
                }
                for e in snap.engines[:6]
            ],
            "history_points": len(snap.history),
        }
    else:
        facts["peec"] = None

    system = (
        "You are a marketing analyst writing one paragraph + 3 actions for a "
        "brand's analytics dashboard. Use the structured facts JSON. Do NOT "
        "invent numbers or competitor names. If a field is null, ignore it. "
        "Keep the summary under 280 characters. Each action label is <60 "
        "chars and imperative; each rationale is one sentence tied to the "
        "facts. Return JSON matching the schema."
    )
    user = f"FACTS:\n{facts}"

    try:
        out = await chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=_SYNTHESIS_SCHEMA,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ai synthesis failed for brand=%s: %s", brand.id, e)
        return None

    summary = (out.get("summary") or "").strip()
    raw_actions = out.get("actions") or []
    actions: list[SynthesisAction] = []
    for a in raw_actions[:3]:
        if not isinstance(a, dict):
            continue
        label = (a.get("label") or "").strip()
        rationale = (a.get("rationale") or "").strip()
        if not label:
            continue
        actions.append(SynthesisAction(label=label, rationale=rationale))

    if not summary or not actions:
        return None

    top_competitor = next(
        (c.name for c in competitors if c.has_peec_data), None
    )
    absent_prompts: list[str] = []
    if snap is not None:
        absent_prompts = [a.prompt for a in snap.absent_from[:5]]

    return AISynthesis(
        summary=summary,
        actions=actions,
        top_competitor=top_competitor,
        absent_prompts=absent_prompts,
    )


# ---------------------------------------------------------------- endpoints


# In-memory caches. The /overview endpoint is cheap to recompute (DB queries
# + a possible Peec MCP discovery), so we cache it for ~30s to make tab
# switches and back-button navigation feel instant. The /synthesis endpoint
# is far more expensive (Gemini call ~6s), so we cache it longer (~5 min)
# and key it by the structural facts that would actually change the output.
import time as _time

_OVERVIEW_TTL = 30.0
_SYNTHESIS_TTL = 300.0
_overview_cache: dict[tuple[str, Window], tuple[float, AnalyticsOverview]] = {}
_synthesis_cache: dict[str, tuple[float, AISynthesis | None]] = {}


def _synthesis_key(
    brand: models.Brand,
    snap: PeecSnapshot | None,
    growth: GrowthTrajectory,
    radar: list[CompetitorRow],
) -> str:
    """Stable cache key for synthesis. Changes when the underlying signal
    changes — visibility, growth total, top competitor, etc. Tiny brand-name
    salt keeps multi-tenant runs isolated."""
    parts = [
        brand.id,
        f"v={(snap.visibility if snap else None)}",
        f"sov={(snap.share_of_voice if snap else None)}",
        f"prompts={(len(snap.visible_on) if snap else 0)}/{(len(snap.absent_from) if snap else 0)}",
        f"growth={growth.metric}:{growth.total}:{growth.delta_pct}",
        f"radar={','.join(c.name for c in radar[:6])}",
    ]
    return "|".join(parts)


async def _build_overview(
    brand: models.Brand, db: Session, window: Window
) -> tuple[AnalyticsOverview, PeecSnapshot | None, GrowthTrajectory, list[CompetitorRow]]:
    brand_payload: dict[str, Any] = {"id": brand.id, "name": brand.name}
    snap: PeecSnapshot | None = None
    try:
        snap = await fetch_snapshot(brand_payload)
    except Exception as e:  # noqa: BLE001
        log.warning("peec snapshot failed for brand=%s: %s", brand.id, e)
        snap = None

    market = _compute_market_position(snap)
    growth, customers_count, campaigns_count, email_sends_count = (
        _compute_growth(db, brand.id, window, snap)
    )
    radar = _compute_competitor_radar(brand, snap)
    engines = _compute_engines(snap)
    citations = _compute_citations(snap)
    drilldown = _compute_prompt_drilldown(snap)

    if snap is None:
        peec_status: Literal[
            "connected", "no_data", "not_configured"
        ] = "not_configured"
    elif snap.visibility is None and not snap.visible_on and not snap.absent_from:
        peec_status = "no_data"
    else:
        peec_status = "connected"

    # Resolve the transport that actually answered. fetch_snapshot stamps
    # ``raw_summary['via']`` as 'mcp' or 'rest'; surface it so the
    # dashboard can render "Peec MCP live" instead of generic "Peec live".
    if snap is None:
        peec_transport: Literal["mcp", "rest", "none"] = "none"
    else:
        via = (snap.raw_summary or {}).get("via")
        peec_transport = "mcp" if via == "mcp" else "rest" if via == "rest" else "none"

    overview = AnalyticsOverview(
        brand_id=brand.id,
        brand_name=brand.name,
        window=window,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        market_position=market,
        growth_trajectory=growth,
        competitor_radar=radar,
        engine_breakdown=engines,
        citations=citations,
        prompt_drilldown=drilldown,
        # Synthesis is fetched separately via /synthesis to keep the main
        # response sub-100ms. Frontend renders a "thinking…" skeleton until
        # that lazy call lands.
        ai_synthesis=None,
        data_sources=DataSources(
            peec=peec_status,
            peec_transport=peec_transport,
            customers_count=customers_count,
            campaigns_count=campaigns_count,
            email_sends_count=email_sends_count,
        ),
    )
    return overview, snap, growth, radar


@router.get("/overview", response_model=AnalyticsOverview)
async def overview(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    window: Window = "6M",
) -> AnalyticsOverview:
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    cache_key = (brand_id, window)
    cached = _overview_cache.get(cache_key)
    now = _time.time()
    if cached is not None and now - cached[0] < _OVERVIEW_TTL:
        return cached[1]

    out, _snap, _growth, _radar = await _build_overview(brand, db, window)
    _overview_cache[cache_key] = (now, out)
    return out


@router.get("/synthesis", response_model=AISynthesis | None)
async def synthesis(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
    window: Window = "6M",
) -> AISynthesis | None:
    """Lazy-loaded LLM synthesis. Hit this in parallel with /overview from
    the frontend — the dashboard paints from /overview while this 5-15s
    Gemini call resolves separately."""
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    _out, snap, growth, radar = await _build_overview(brand, db, window)

    key = _synthesis_key(brand, snap, growth, radar)
    cached = _synthesis_cache.get(key)
    now = _time.time()
    if cached is not None and now - cached[0] < _SYNTHESIS_TTL:
        return cached[1]

    result = await _generate_ai_synthesis(brand, snap, growth, radar)
    _synthesis_cache[key] = (now, result)
    return result


# --------------------------------------------------------------- raw export


@router.get("/snapshot")
async def raw_snapshot(brand_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Used by the Export Report button — returns whatever Peec gave us, raw."""
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    try:
        snap = await fetch_snapshot({"id": brand.id, "name": brand.name})
    except Exception as e:  # noqa: BLE001
        log.warning("peec snapshot failed: %s", e)
        snap = None
    if snap is None:
        return {"connected": False, "snapshot": None}
    return {"connected": True, "snapshot": asdict(snap)}
