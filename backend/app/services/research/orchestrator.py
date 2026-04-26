"""Tavily research orchestration — high-level helpers used by onboarding
and the agent loop.

Two entry points:

- ``gather_brand_context(brand)`` — once-per-brand snapshot. Pulls company
  context, recent news, and category trends. Stored on ``Brand.research``.
- ``gather_campaign_context(brand, user_request)`` — once-per-campaign
  freshness pass. Pulls topic-specific news so drafts can cite something
  written in the last 30 days instead of priors.

Both emit ``research.requested`` → per-source ``research.source_added`` →
``research.completed``. They never raise — on failure we emit
``research.failed`` (or ``research.unavailable`` when no key) and return
an empty payload so the caller's pipeline keeps moving.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.events.bus import bus
from app.events.types import Events
from app.services.research.tavily import (
    TavilyClient,
    TavilyError,
    get_tavily,
    normalize_results,
)

log = logging.getLogger(__name__)


# Number of results we keep per query in the persisted bundle. Tavily
# returns up to ~20; for grounding we want the top 4-5.
PER_QUERY_KEEP = 5
# Max total sources we ship to the LLM as grounding context. Keeps tokens
# bounded; Tavily's relevance ranking already surfaces the best ones.
LLM_CONTEXT_CAP = 12


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str
    bucket: str  # 'company' | 'news' | 'trend' | 'topic' | 'competitor' | 'campaign'
    score: float | None = None
    published_date: str | None = None


@dataclass
class BrandResearch:
    brand_id: str
    fetched_at: str
    queries: list[dict[str, Any]] = field(default_factory=list)
    sources: list[ResearchSource] = field(default_factory=list)
    answer: str | None = None  # Tavily's auto-generated synthesized answer
    domain: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class CompetitorIntel:
    competitor_id: str
    competitor_name: str
    competitor_url: str | None
    fetched_at: str
    sources: list[ResearchSource] = field(default_factory=list)
    answer: str | None = None  # synthesized "what they're doing right now"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CampaignResearch:
    campaign_id: str
    brand_id: str | None
    user_request: str
    fetched_at: str
    sources: list[ResearchSource] = field(default_factory=list)
    answer: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── helpers ────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return host or None
    except Exception:
        return None


def _emit_sources(
    scope: str, scope_id: str, sources: list[ResearchSource]
) -> None:
    """Stream each citation as it lands so the UI can render progressively."""
    for s in sources:
        bus.emit(
            Events.RESEARCH_SOURCE_ADDED,
            {
                "scope": scope,  # 'brand' | 'campaign'
                "scope_id": scope_id,
                "source": asdict(s),
            },
        )


async def _safe_search(
    client: TavilyClient,
    query: str,
    *,
    bucket: str,
    topic: str = "general",
    days: int | None = None,
    include_answer: bool = False,
    exclude_domains: list[str] | None = None,
) -> tuple[list[ResearchSource], str | None]:
    """Run one Tavily search and tag every result with the bucket. Returns
    ``([], None)`` on any error so callers can keep gathering."""
    try:
        payload = await client.search(
            query,
            topic=topic,  # type: ignore[arg-type]
            days=days,
            include_answer="advanced" if include_answer else False,
            exclude_domains=exclude_domains,
        )
    except TavilyError as e:
        log.warning("tavily search [%s] failed: %s", bucket, e)
        return [], None
    results = normalize_results(payload)[:PER_QUERY_KEEP]
    sources = [
        ResearchSource(
            title=r["title"] or r["url"],
            url=r["url"],
            snippet=r["snippet"],
            bucket=bucket,
            score=r.get("score"),
            published_date=r.get("published_date"),
        )
        for r in results
    ]
    answer = (
        (payload.get("answer") or "").strip() or None
        if include_answer
        else None
    )
    return sources, answer


# ── public entry points ────────────────────────────────────────────────


async def gather_brand_context(
    *,
    brand_id: str,
    brand_name: str,
    brand_url: str | None,
    description: str | None,
    competitors: list[dict] | None = None,
) -> BrandResearch:
    """Once-per-brand research pass. Concurrent searches across the four
    buckets we care about for grounding. Always emits an event lifecycle
    even on failure / no-key so the UI can render the card."""

    client = get_tavily()
    bundle = BrandResearch(brand_id=brand_id, fetched_at=_now())
    bundle.domain = _domain_of(brand_url)

    bus.emit(
        Events.RESEARCH_REQUESTED,
        {
            "scope": "brand",
            "scope_id": brand_id,
            "brand_id": brand_id,
            "brand_name": brand_name,
            "url": brand_url,
        },
    )

    if client is None:
        bus.emit(
            Events.RESEARCH_UNAVAILABLE,
            {
                "scope": "brand",
                "scope_id": brand_id,
                "brand_id": brand_id,
                "reason": "no api key",
            },
        )
        bundle.error = "tavily api key not set"
        return bundle

    label = brand_name or _domain_of(brand_url) or "the company"
    desc = (description or "").strip()
    own_domain = bundle.domain
    exclude = [own_domain] if own_domain else None

    queries: list[tuple[str, dict[str, Any]]] = [
        (
            "company",
            {
                "query": (
                    f"{label} company overview "
                    + (desc[:120] if desc else "")
                ).strip(),
                "bucket": "company",
                "include_answer": True,
            },
        ),
        (
            "news",
            {
                "query": f"{label} news",
                "bucket": "news",
                "topic": "news",
                "days": 30,
                "exclude_domains": exclude,
            },
        ),
        (
            "trend",
            {
                "query": (
                    f"{desc[:120]} trends 2026"
                    if desc
                    else f"{label} category trends 2026"
                ),
                "bucket": "trend",
            },
        ),
    ]

    # Add up to two competitor-recent-moves queries when we have names
    for c in (competitors or [])[:2]:
        cname = (c.get("name") or "").strip()
        if not cname:
            continue
        queries.append(
            (
                "competitor",
                {
                    "query": f"{cname} recent product launches",
                    "bucket": "competitor",
                    "topic": "news",
                    "days": 60,
                },
            )
        )

    bundle.queries = [
        {"label": label_, **{k: v for k, v in q.items() if k != "query"}, "query": q["query"]}
        for label_, q in queries
    ]

    async def _one(label_: str, q: dict[str, Any]) -> tuple[list[ResearchSource], str | None]:
        return await _safe_search(
            client,
            q["query"],
            bucket=q["bucket"],
            topic=q.get("topic", "general"),
            days=q.get("days"),
            include_answer=q.get("include_answer", False),
            exclude_domains=q.get("exclude_domains"),
        )

    try:
        results = await asyncio.gather(*(_one(l, q) for l, q in queries))
    except Exception as e:
        log.exception("gather_brand_context failed")
        bundle.error = str(e)[:200]
        bus.emit(
            Events.RESEARCH_FAILED,
            {
                "scope": "brand",
                "scope_id": brand_id,
                "brand_id": brand_id,
                "error": bundle.error,
            },
        )
        return bundle

    seen: set[str] = set()
    for sources, answer in results:
        if answer and not bundle.answer:
            bundle.answer = answer
        for s in sources:
            if s.url in seen:
                continue
            seen.add(s.url)
            bundle.sources.append(s)

    _emit_sources("brand", brand_id, bundle.sources)

    bus.emit(
        Events.RESEARCH_COMPLETED,
        {
            "scope": "brand",
            "scope_id": brand_id,
            "brand_id": brand_id,
            "source_count": len(bundle.sources),
            "answer": bundle.answer,
            "sources": [asdict(s) for s in bundle.sources],
            "fetched_at": bundle.fetched_at,
        },
    )
    return bundle


async def gather_competitor_intel(
    *,
    competitor_id: str,
    competitor_name: str,
    competitor_url: str | None,
    own_brand_name: str | None = None,
) -> CompetitorIntel:
    """On-demand competitor intel. Fires when the user opens the watchlist
    modal (or hits POST /competitors/{id}/intel). Three parallel queries:

      - **launches**: news, last 90 days — recently-launched products /
        features / announcements. The headline of the modal section.
      - **moves**: news, last 60 days — go-to-market shifts (pricing,
        partnerships, hires, repositioning).
      - **footprint**: general — what categories / messaging / positioning
        they're known for. Slower-moving context the LLM uses to compare.

    Always emits ``competitor.intel_*`` lifecycle events so the modal
    populates progressively. Never raises — failures degrade to an empty
    bundle with ``error`` set."""

    client = get_tavily()
    bundle = CompetitorIntel(
        competitor_id=competitor_id,
        competitor_name=competitor_name,
        competitor_url=competitor_url,
        fetched_at=_now(),
    )

    bus.emit(
        Events.COMPETITOR_INTEL_REQUESTED,
        {
            "competitor_id": competitor_id,
            "competitor_name": competitor_name,
            "url": competitor_url,
        },
    )

    if client is None:
        bus.emit(
            Events.COMPETITOR_INTEL_UNAVAILABLE,
            {
                "competitor_id": competitor_id,
                "reason": "no api key",
            },
        )
        bundle.error = "tavily api key not set"
        return bundle

    label = competitor_name.strip() or _domain_of(competitor_url) or "competitor"
    own_domain = _domain_of(competitor_url)
    # Don't pollute with the competitor's own marketing site — we want
    # third-party coverage of their moves, not their own press release page.
    exclude = [own_domain] if own_domain else None

    queries: list[tuple[str, dict[str, Any]]] = [
        (
            "launches",
            {
                "query": (
                    f"{label} new product launch OR new feature OR release "
                    "announcement"
                ),
                "bucket": "launches",
                "topic": "news",
                "days": 90,
                "exclude_domains": exclude,
                "include_answer": True,
            },
        ),
        (
            "moves",
            {
                "query": (
                    f"{label} pricing OR partnership OR funding OR hiring "
                    "OR strategy"
                ),
                "bucket": "moves",
                "topic": "news",
                "days": 60,
                "exclude_domains": exclude,
            },
        ),
        (
            "footprint",
            {
                "query": (
                    f"{label} positioning OR messaging OR competitors"
                    + (f" vs {own_brand_name}" if own_brand_name else "")
                ),
                "bucket": "footprint",
                "topic": "general",
            },
        ),
    ]

    async def _one(label_: str, q: dict[str, Any]):
        return await _safe_search(
            client,
            q["query"],
            bucket=q["bucket"],
            topic=q.get("topic", "general"),
            days=q.get("days"),
            include_answer=q.get("include_answer", False),
            exclude_domains=q.get("exclude_domains"),
        )

    try:
        results = await asyncio.gather(*(_one(l, q) for l, q in queries))
    except Exception as e:
        log.exception("gather_competitor_intel failed")
        bundle.error = str(e)[:200]
        bus.emit(
            Events.COMPETITOR_INTEL_FAILED,
            {"competitor_id": competitor_id, "error": bundle.error},
        )
        return bundle

    seen: set[str] = set()
    for sources, answer in results:
        if answer and not bundle.answer:
            bundle.answer = answer
        for s in sources:
            if s.url in seen:
                continue
            seen.add(s.url)
            bundle.sources.append(s)
            bus.emit(
                Events.COMPETITOR_INTEL_SOURCE_ADDED,
                {
                    "competitor_id": competitor_id,
                    "source": asdict(s),
                },
            )

    bus.emit(
        Events.COMPETITOR_INTEL_COMPLETED,
        {
            "competitor_id": competitor_id,
            "competitor_name": competitor_name,
            "source_count": len(bundle.sources),
            "answer": bundle.answer,
            "sources": [asdict(s) for s in bundle.sources],
            "fetched_at": bundle.fetched_at,
        },
    )
    return bundle


async def gather_campaign_context(
    *,
    campaign_id: str,
    brand_id: str | None,
    brand_name: str,
    description: str | None,
    user_request: str,
) -> CampaignResearch:
    """Once-per-campaign freshness pass. Single focused Tavily news search
    so drafts can cite something published in the last 30 days. Cheap
    enough to run on every campaign."""

    client = get_tavily()
    bundle = CampaignResearch(
        campaign_id=campaign_id,
        brand_id=brand_id,
        user_request=user_request,
        fetched_at=_now(),
    )

    bus.emit(
        Events.RESEARCH_REQUESTED,
        {
            "scope": "campaign",
            "scope_id": campaign_id,
            "brand_id": brand_id,
            "user_request": user_request,
        },
    )

    if client is None:
        bus.emit(
            Events.RESEARCH_UNAVAILABLE,
            {
                "scope": "campaign",
                "scope_id": campaign_id,
                "brand_id": brand_id,
                "reason": "no api key",
            },
        )
        bundle.error = "tavily api key not set"
        return bundle

    desc = (description or "").strip()
    label = brand_name or "the brand"
    queries = [
        (
            f"{user_request[:160]} {desc[:80]}".strip(),
            "topic",
            "general",
            None,
            True,
        ),
        (
            f"{user_request[:160]} {label}".strip(),
            "campaign",
            "news",
            30,
            False,
        ),
    ]

    async def _one(q: str, bucket: str, topic: str, days: int | None, ans: bool):
        return await _safe_search(
            client,
            q,
            bucket=bucket,
            topic=topic,
            days=days,
            include_answer=ans,
        )

    try:
        results = await asyncio.gather(*(_one(*q) for q in queries))
    except Exception as e:
        log.exception("gather_campaign_context failed")
        bundle.error = str(e)[:200]
        bus.emit(
            Events.RESEARCH_FAILED,
            {
                "scope": "campaign",
                "scope_id": campaign_id,
                "brand_id": brand_id,
                "error": bundle.error,
            },
        )
        return bundle

    seen: set[str] = set()
    for sources, answer in results:
        if answer and not bundle.answer:
            bundle.answer = answer
        for s in sources:
            if s.url in seen:
                continue
            seen.add(s.url)
            bundle.sources.append(s)
            if len(bundle.sources) >= LLM_CONTEXT_CAP:
                break

    _emit_sources("campaign", campaign_id, bundle.sources)

    bus.emit(
        Events.RESEARCH_COMPLETED,
        {
            "scope": "campaign",
            "scope_id": campaign_id,
            "brand_id": brand_id,
            "source_count": len(bundle.sources),
            "answer": bundle.answer,
            "sources": [asdict(s) for s in bundle.sources],
            "fetched_at": bundle.fetched_at,
        },
    )
    return bundle


def research_to_prompt_block(
    sources: list[ResearchSource] | list[dict],
    answer: str | None = None,
    *,
    cap: int = LLM_CONTEXT_CAP,
) -> str:
    """Render a research bundle as a compact LLM grounding block. Caller
    drops the result into the user message after the brand voice block.
    Empty if nothing useful — leaving zero-cost when research was skipped."""
    if not sources and not answer:
        return ""
    lines: list[str] = []
    if answer:
        lines.append(f"Synthesized answer (web): {answer.strip()[:600]}")
    if sources:
        lines.append(
            "Recent web sources (cite where natural; don't fabricate links):"
        )
        for s in sources[:cap]:
            d = s if isinstance(s, dict) else asdict(s)
            title = (d.get("title") or d.get("url") or "").strip()[:140]
            url = d.get("url") or ""
            snippet = (d.get("snippet") or "").strip()[:240]
            published = (d.get("published_date") or "").strip()
            tail = f" ({published})" if published else ""
            lines.append(f"- [{title}]({url}){tail}\n  {snippet}")
    return "\n".join(lines)
