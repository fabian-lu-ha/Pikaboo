"""Domain logic that turns raw Peec calls into the artifacts the agent needs:
 - PeecSnapshot — current visibility, share-of-voice, prompts the brand appears
   in vs. is absent from, and which domains LLMs cite for those prompts
 - TargetPrompt — a single prompt the agent should target this campaign

Designed to fail gracefully — if Peec response shapes don't match expectations,
return whatever fields we could resolve and let the caller render a partial card.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.config import settings
from app.services.peec.client import PeecError, get_peec

log = logging.getLogger(__name__)


@dataclass
class VisiblePrompt:
    prompt: str
    rank: int | None = None
    visibility: float | None = None


@dataclass
class AbsentPrompt:
    prompt: str
    competitor_winning: str | None = None
    competitor_visibility: float | None = None
    own_visibility: float | None = None


@dataclass
class CitedDomain:
    domain: str
    citation_count: int | None = None
    rank: int | None = None
    favicon_url: str | None = None


@dataclass
class EnginePoint:
    """Per-engine visibility (ChatGPT / Perplexity / Gemini / Claude / etc.)."""

    engine: str  # canonicalized lower-case key, e.g. "chatgpt"
    label: str  # display label as Peec returned it
    visibility: float | None = None
    share_of_voice: float | None = None
    rank: int | None = None
    sample_count: int | None = None


@dataclass
class HistoryPoint:
    """One bucket on the brand's visibility timeseries."""

    date: str  # ISO-8601 date or datetime, whichever Peec returned
    visibility: float | None = None
    share_of_voice: float | None = None
    sentiment: float | None = None


@dataclass
class PromptDetail:
    """Rich per-prompt drill-down. Used by the dashboard's prompt modal."""

    prompt: str
    own_rank: int | None = None
    own_visibility: float | None = None
    winner: str | None = None
    winner_visibility: float | None = None
    engines: list[str] = field(default_factory=list)
    cited_domains: list[str] = field(default_factory=list)
    last_seen_at: str | None = None


@dataclass
class TargetPrompt:
    prompt: str
    current_rank: int | None = None
    own_visibility: float | None = None
    competitor_winning: str | None = None
    top_cited_domains: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class PeecSnapshot:
    brand_id: str
    project_id: str | None
    fetched_at: str
    visibility: float | None = None
    share_of_voice: float | None = None
    sentiment: float | None = None
    visible_on: list[VisiblePrompt] = field(default_factory=list)
    absent_from: list[AbsentPrompt] = field(default_factory=list)
    cited_domains: list[CitedDomain] = field(default_factory=list)
    engines: list[EnginePoint] = field(default_factory=list)
    history: list[HistoryPoint] = field(default_factory=list)
    prompt_details: list[PromptDetail] = field(default_factory=list)
    competitors: list[dict] = field(default_factory=list)
    raw_summary: dict = field(default_factory=dict)

    def to_event_payload(self) -> dict:
        return {
            "brand_id": self.brand_id,
            "project_id": self.project_id,
            "fetched_at": self.fetched_at,
            "visibility": self.visibility,
            "share_of_voice": self.share_of_voice,
            "sentiment": self.sentiment,
            "visible_on": [asdict(v) for v in self.visible_on[:5]],
            "absent_from": [asdict(a) for a in self.absent_from[:5]],
            "cited_domains": [asdict(c) for c in self.cited_domains[:8]],
            "engines": [asdict(e) for e in self.engines],
            "history_points": len(self.history),
        }


def _f(d: dict, *keys, default=None):
    """Get the first non-None value among keys, with a default."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _to_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def fetch_snapshot(brand: dict) -> PeecSnapshot | None:
    """Pull a full visibility snapshot for the given brand.

    MCP-first: if the user has connected Peec via OAuth, fetch through the
    MCP transport (richer demo, contest-credible). Falls back to the REST
    client when MCP isn't available. Returns None when neither path is
    configured."""
    # MCP path — only succeeds when tokens are persisted on disk.
    try:
        from app.services.peec.mcp_snapshot import fetch_snapshot_via_mcp

        mcp_snap = await fetch_snapshot_via_mcp(brand)
        if mcp_snap is not None:
            return mcp_snap
    except Exception as e:  # noqa: BLE001 — fall through to REST
        log.warning("peec.fetch_snapshot: MCP path errored: %s", e)

    peec = get_peec()
    if peec is None:
        return None

    project_id = settings.peec_project_id

    try:
        prompts = await peec.list_prompts(project_id=project_id)
    except PeecError as e:
        log.warning("peec list_prompts failed: %s", e)
        return None

    try:
        report = await peec.get_brands_report(project_id=project_id)
    except PeecError as e:
        log.warning("peec brands_report failed: %s", e)
        report = {}

    brand_name_lc = (brand.get("name") or "").lower()
    visible: list[VisiblePrompt] = []
    absent: list[AbsentPrompt] = []
    cited_domains: list[CitedDomain] = []

    rows = peec._as_list(report) if isinstance(report, dict) else []
    own_summary: dict = {}
    competitors: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_brand = (
            _f(row, "brand", "brand_name", "name", default="") or ""
        ).lower()
        if row_brand and brand_name_lc and row_brand == brand_name_lc:
            own_summary = row
        elif row_brand:
            competitors.append(
                {
                    "name": _f(row, "brand", "brand_name", "name") or "",
                    "visibility": _to_float(
                        _f(row, "visibility", "visibility_score", "share")
                    ),
                    "share_of_voice": _to_float(
                        _f(row, "share_of_voice", "sov")
                    ),
                    "sentiment": _to_float(
                        _f(row, "sentiment", "sentiment_score")
                    ),
                }
            )

    own_visibility = _to_float(
        _f(own_summary, "visibility", "visibility_score", "share")
    )
    sov = _to_float(_f(own_summary, "share_of_voice", "sov"))
    sentiment = _to_float(_f(own_summary, "sentiment", "sentiment_score"))

    for p in prompts[:25]:
        if not isinstance(p, dict):
            continue
        prompt_text = _f(p, "prompt", "text", "query", default="")
        if not prompt_text:
            continue
        own_rank = _to_int(_f(p, "own_rank", "brand_rank", "rank"))
        own_vis = _to_float(_f(p, "own_visibility", "visibility"))
        comp = _f(p, "winning_competitor", "top_competitor", "leader")
        comp_vis = _to_float(_f(p, "competitor_visibility", "leader_visibility"))
        if own_rank and own_rank <= 5:
            visible.append(
                VisiblePrompt(
                    prompt=prompt_text, rank=own_rank, visibility=own_vis
                )
            )
        else:
            absent.append(
                AbsentPrompt(
                    prompt=prompt_text,
                    competitor_winning=str(comp) if comp else None,
                    competitor_visibility=comp_vis,
                    own_visibility=own_vis,
                )
            )

    domains_payload = _f(own_summary, "cited_domains", "top_domains", default=[])
    if isinstance(domains_payload, list):
        for d in domains_payload[:10]:
            if isinstance(d, dict):
                cited_domains.append(
                    CitedDomain(
                        domain=_f(d, "domain", "host", "url") or "",
                        citation_count=_to_int(
                            _f(d, "citations", "count", "n")
                        ),
                    )
                )
            elif isinstance(d, str):
                cited_domains.append(CitedDomain(domain=d))

    return PeecSnapshot(
        brand_id=brand.get("id") or "",
        project_id=project_id,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        visibility=own_visibility,
        share_of_voice=sov,
        sentiment=sentiment,
        visible_on=visible,
        absent_from=absent,
        cited_domains=cited_domains,
        competitors=competitors,
        raw_summary={
            "prompt_count": len(prompts),
            "had_brands_report": bool(rows),
            "matched_brand_row": bool(own_summary),
            "via": "rest",
        },
    )


def select_target_prompts(
    snap: PeecSnapshot, k: int = 3
) -> list[TargetPrompt]:
    """Top-k prompts where the brand could realistically win + has highest absence.

    Score = competitor_top_visibility * (1 - own_visibility/100) * citation_overlap
    For v0 we proxy citation_overlap with 1.0 (uniform) — a future refinement
    pulls citation lists for each prompt and computes overlap with our own
    brand's citation surface.
    """
    candidates: list[TargetPrompt] = []
    for ap in snap.absent_from:
        comp_vis = ap.competitor_visibility or 0.0
        own_vis = ap.own_visibility or 0.0
        gap = max(0.0, 1.0 - (own_vis / 100.0))
        score = comp_vis * gap
        candidates.append(
            TargetPrompt(
                prompt=ap.prompt,
                current_rank=None,
                own_visibility=ap.own_visibility,
                competitor_winning=ap.competitor_winning,
                top_cited_domains=[c.domain for c in snap.cited_domains[:3]],
                score=score,
            )
        )
    candidates.sort(key=lambda c: -c.score)
    return candidates[:k]
