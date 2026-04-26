"""Build a ``PeecSnapshot`` via Peec's MCP server.

We discover tool names dynamically — Peec hasn't published a stable contract,
so we substring-match on names ('brand', 'prompt', 'history', 'engine',
'citation') and call whatever's available. Result is mapped into the same
dataclasses as ``snapshot.py`` so callers don't care which path ran.

Beyond the original two tools (list_prompts, brands_report) we now opportunistically
fetch:

  - **history / timeseries** — per-brand visibility over time (powers Growth
    Trajectory in the dashboard)
  - **engines / sources** — per-engine breakdown (ChatGPT / Perplexity / etc.)
  - **citations / sources** — top cited domains (rich form, with counts/rank)
  - **prompt detail** — drill-down per prompt (rank, responses, engines)

Each call is best-effort. Returns ``None`` only when authn fails entirely;
partial responses still produce a populated PeecSnapshot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.peec.mcp_client import (
    PeecMCPNotConnectedError,
    peec_mcp_session,
)
from app.services.peec.snapshot import (
    AbsentPrompt,
    CitedDomain,
    EnginePoint,
    HistoryPoint,
    PeecSnapshot,
    PromptDetail,
    VisiblePrompt,
    _f,
    _to_float,
    _to_int,
)

log = logging.getLogger(__name__)


def _pick(tools: list[dict], *needles: str) -> str | None:
    """First tool whose name contains ALL needles (case-insensitive)."""
    for t in tools:
        name = (t.get("name") or "").lower()
        if all(n in name for n in needles):
            return t["name"]
    return None


def _pick_any(tools: list[dict], *needles: str) -> str | None:
    """First tool whose name contains ANY needle."""
    for t in tools:
        name = (t.get("name") or "").lower()
        if any(n in name for n in needles):
            return t["name"]
    return None


def _as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in (
            "data",
            "items",
            "prompts",
            "brands",
            "results",
            "rows",
            "history",
            "engines",
            "sources",
            "citations",
            "domains",
        ):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


_ENGINE_CANON: dict[str, str] = {
    "chatgpt": "chatgpt",
    "openai": "chatgpt",
    "gpt": "chatgpt",
    "perplexity": "perplexity",
    "ppl": "perplexity",
    "gemini": "gemini",
    "google": "gemini",
    "bard": "gemini",
    "claude": "claude",
    "anthropic": "claude",
    "copilot": "copilot",
    "bing": "copilot",
    "you.com": "you",
    "you": "you",
    "grok": "grok",
}


def _canon_engine(label: str | None) -> str:
    if not label:
        return "unknown"
    s = label.strip().lower()
    for needle, canon in _ENGINE_CANON.items():
        if needle in s:
            return canon
    return s.replace(" ", "_")


async def fetch_snapshot_via_mcp(brand: dict) -> PeecSnapshot | None:
    """Same return shape as ``snapshot.fetch_snapshot`` but via MCP. Returns
    None when MCP isn't connected; otherwise returns a snapshot with whichever
    fields the discovered tools could populate."""
    project_id = settings.peec_project_id
    brand_name = brand.get("name") or ""
    brand_name_lc = brand_name.lower()

    # Probe for tokens; bail early if not connected.
    try:
        async with peec_mcp_session() as session:
            tool_list_result = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in tool_list_result.tools
            ]

            list_prompts_name = _pick(tools, "prompt", "list") or _pick(
                tools, "prompt"
            )
            brands_report_name = _pick(tools, "brand", "report") or _pick(
                tools, "brand"
            )
            history_name = _pick_any(
                tools, "history", "trend", "timeseries", "timeline"
            )
            engines_name = _pick_any(
                tools, "engine", "source", "model", "platform"
            )
            citations_name = _pick_any(
                tools, "citation", "domain", "cited"
            )

            common: dict[str, Any] = {}
            if project_id:
                common["project_id"] = project_id
            brand_arg: dict[str, Any] = dict(common)
            if brand_name:
                brand_arg["brand"] = brand_name
                brand_arg["brand_name"] = brand_name

            prompts: list[dict] = []
            report: Any = {}
            history_payload: Any = {}
            engines_payload: Any = {}
            citations_payload: Any = {}

            async def _safe_call(name: str | None, args: dict) -> Any:
                if not name:
                    return None
                try:
                    r = await session.call_tool(name, args)
                    if r.isError:
                        return None
                    return _unwrap(r.content)
                except Exception as e:  # noqa: BLE001
                    log.warning("peec_mcp.%s failed: %s", name, e)
                    return None

            prompts_payload = await _safe_call(list_prompts_name, common)
            if prompts_payload is not None:
                prompts = _as_list(prompts_payload)

            report = await _safe_call(brands_report_name, common) or {}
            history_payload = (
                await _safe_call(history_name, brand_arg) or {}
            )
            engines_payload = (
                await _safe_call(engines_name, brand_arg) or {}
            )
            citations_payload = (
                await _safe_call(citations_name, brand_arg) or {}
            )
    except PeecMCPNotConnectedError:
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("peec_mcp session failed: %s", e)
        return None

    if not tools:
        log.warning("peec_mcp: no tools advertised")
        return None

    # ---------------- brands report → own row + competitors --------------
    rows = _as_list(report)
    own_summary: dict = {}
    competitors: list[dict] = []
    for row in rows:
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

    # ------------------------- prompts → visible/absent ------------------
    visible: list[VisiblePrompt] = []
    absent: list[AbsentPrompt] = []
    prompt_details: list[PromptDetail] = []
    for p in prompts[:40]:
        prompt_text = _f(p, "prompt", "text", "query", default="")
        if not prompt_text:
            continue
        own_rank = _to_int(_f(p, "own_rank", "brand_rank", "rank"))
        own_vis = _to_float(_f(p, "own_visibility", "visibility"))
        comp = _f(p, "winning_competitor", "top_competitor", "leader")
        comp_vis = _to_float(
            _f(p, "competitor_visibility", "leader_visibility")
        )
        engines_for_prompt: list[str] = []
        ep = _f(p, "engines", "sources", "models")
        if isinstance(ep, list):
            for e in ep:
                if isinstance(e, str):
                    engines_for_prompt.append(_canon_engine(e))
                elif isinstance(e, dict):
                    engines_for_prompt.append(
                        _canon_engine(_f(e, "name", "engine", "label"))
                    )
        cited_for_prompt: list[str] = []
        cp = _f(p, "cited_domains", "top_domains", "domains")
        if isinstance(cp, list):
            for d in cp[:5]:
                if isinstance(d, str):
                    cited_for_prompt.append(d)
                elif isinstance(d, dict):
                    dom = _f(d, "domain", "host", "url")
                    if dom:
                        cited_for_prompt.append(dom)

        prompt_details.append(
            PromptDetail(
                prompt=prompt_text,
                own_rank=own_rank,
                own_visibility=own_vis,
                winner=str(comp) if comp else None,
                winner_visibility=comp_vis,
                engines=list(dict.fromkeys(engines_for_prompt))[:6],
                cited_domains=cited_for_prompt[:5],
                last_seen_at=_f(p, "last_seen_at", "updated_at", "fetched_at"),
            )
        )

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

    # ----------------------------- citations -----------------------------
    cited_domains: list[CitedDomain] = []
    domains_payload = (
        _f(own_summary, "cited_domains", "top_domains", default=None)
        or citations_payload
    )
    domain_rows: list = []
    if isinstance(domains_payload, list):
        domain_rows = domains_payload
    elif isinstance(domains_payload, dict):
        domain_rows = _as_list(domains_payload)
    for i, d in enumerate(domain_rows[:15]):
        if isinstance(d, dict):
            domain = (
                _f(d, "domain", "host", "url", "site", "name") or ""
            ).strip()
            if not domain:
                continue
            cited_domains.append(
                CitedDomain(
                    domain=domain,
                    citation_count=_to_int(
                        _f(d, "citations", "count", "n", "mentions")
                    ),
                    rank=_to_int(_f(d, "rank", "position")) or (i + 1),
                    favicon_url=_f(d, "favicon", "favicon_url", "icon"),
                )
            )
        elif isinstance(d, str):
            cited_domains.append(CitedDomain(domain=d, rank=i + 1))

    # ----------------------------- engines -------------------------------
    engines: list[EnginePoint] = []
    seen_engines: set[str] = set()
    engine_rows = _as_list(engines_payload)
    for r in engine_rows:
        label = (
            _f(r, "engine", "name", "label", "platform", "source")
            or ""
        ).strip()
        if not label:
            continue
        canon = _canon_engine(label)
        if canon in seen_engines:
            continue
        seen_engines.add(canon)
        engines.append(
            EnginePoint(
                engine=canon,
                label=label,
                visibility=_to_float(
                    _f(r, "visibility", "visibility_score", "share")
                ),
                share_of_voice=_to_float(
                    _f(r, "share_of_voice", "sov")
                ),
                rank=_to_int(_f(r, "rank", "position")),
                sample_count=_to_int(
                    _f(r, "samples", "responses", "count", "n")
                ),
            )
        )

    # If we couldn't get a dedicated engines tool, derive from prompt
    # engine breadcrumbs (count of prompts each engine showed up on).
    if not engines and prompt_details:
        from collections import Counter

        c: Counter[str] = Counter()
        for pd in prompt_details:
            for e in pd.engines:
                c[e] += 1
        max_n = max(c.values()) if c else 0
        for canon, n in c.most_common(8):
            engines.append(
                EnginePoint(
                    engine=canon,
                    label=canon.title(),
                    visibility=(n / max_n) * 100.0 if max_n else None,
                    sample_count=n,
                )
            )

    # ------------------------------ history ------------------------------
    history: list[HistoryPoint] = []
    history_rows = _as_list(history_payload)
    for r in history_rows:
        date = _f(r, "date", "timestamp", "ts", "day", "bucket")
        if not date:
            continue
        history.append(
            HistoryPoint(
                date=str(date),
                visibility=_to_float(
                    _f(r, "visibility", "visibility_score", "value", "y")
                ),
                share_of_voice=_to_float(
                    _f(r, "share_of_voice", "sov")
                ),
                sentiment=_to_float(_f(r, "sentiment")),
            )
        )

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
        engines=engines,
        history=history,
        prompt_details=prompt_details,
        competitors=competitors,
        raw_summary={
            "prompt_count": len(prompts),
            "had_brands_report": bool(rows),
            "matched_brand_row": bool(own_summary),
            "via": "mcp",
            "tools_used": [
                t
                for t in (
                    list_prompts_name,
                    brands_report_name,
                    history_name,
                    engines_name,
                    citations_name,
                )
                if t
            ],
            "discovered_tools": [t["name"] for t in tools],
        },
    )


def _unwrap(content: list) -> Any:
    """Same content unwrapping as mcp_client.call_tool."""
    import json

    out: list[Any] = []
    for block in content:
        if block.type == "text":
            try:
                out.append(json.loads(block.text))
            except Exception:
                out.append(block.text)
        else:
            out.append(block.model_dump())
    if len(out) == 1:
        return out[0]
    return out
