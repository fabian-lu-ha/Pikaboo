"""Comparison page generator — "Brand vs Competitor for [use case]".

Highest-yield format per the 2026 GEO benchmarks: comparative listicles
land 32.5% of all AI-engine citations. Output is a ~700-word markdown
page with: definition lede, feature comparison table, balanced pro/con
breakdown, embedded statistic, expert quote, outbound citation, FAQ
block. Tuned to feel like a real third-party-style review (not vendor
slop, which LLMs increasingly down-weight).
"""

from __future__ import annotations

from typing import Any

from app.services.geo.asset_generator import GeneratedAsset
from app.services.llm.client import chat_json

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "lede": {"type": "string"},
        "comparison_table_markdown": {"type": "string"},
        "body_markdown": {"type": "string"},
        "embedded_statistic": {"type": "string"},
        "expert_quote": {"type": "string"},
        "outbound_citation_url": {"type": "string"},
        "faq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["question", "answer"],
            },
        },
    },
    "required": [
        "title",
        "lede",
        "comparison_table_markdown",
        "body_markdown",
        "faq",
    ],
}


async def generate(brand: dict, gap: dict, recommendation: dict) -> GeneratedAsset:
    competitor = gap.get("competitor_name") or "the leading competitor"
    outline = recommendation.get("asset_outline") or {}
    key_points = outline.get("key_points") or []

    system = (
        "You are writing a balanced, citation-worthy comparison page for an "
        "answer-engine optimization (GEO) workflow. The page must look like "
        "honest third-party editorial — vendor-favoring 'X vs competitors' "
        "pages are increasingly down-weighted by LLMs. Structure (in this "
        "order, all required):\n"
        "1) ONE definition-first lede sentence ('X is a Y that does Z')\n"
        "2) A markdown comparison table with 5-7 feature rows\n"
        "3) Body: balanced 'where Brand wins' + 'where Competitor wins' + "
        "'who should pick which', ~400-500 words\n"
        "4) ONE embedded specific statistic (% or Nx) with a plausible source "
        "in parentheses\n"
        "5) ONE short expert quote (in italics, 1-2 sentences)\n"
        "6) ONE outbound citation URL to a reputable domain\n"
        "7) FAQ block: 4-6 Q&A pairs that real users searching the gap "
        "prompt would ask\n"
        "Combine these into ONE markdown body in body_markdown. Also return "
        "the table, statistic, quote, citation URL, and FAQ as separate "
        "fields so we can also persist a JSON-LD payload alongside."
    )

    facts = (
        f"BRAND: {brand.get('name')} — {brand.get('description') or ''}\n"
        f"BRAND URL: {brand.get('url') or 'unknown'}\n"
        f"COMPETITOR: {competitor}\n"
        f"GAP PROMPT (the search this page must surface for): \"{gap['prompt']}\"\n"
        f"RECOMMENDED KEY POINTS: {key_points}\n"
        f"COMPETITOR'S OWN VISIBILITY: {gap.get('competitor_visibility')}\n"
        f"BRAND'S OWN VISIBILITY: {gap.get('own_visibility')}\n"
        f"ENGINES PRESENT: {gap.get('engines_present')}\n"
        f"DOMAINS CURRENTLY CITED ON THIS PROMPT: {gap.get('cited_domains')}"
    )

    out = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": facts},
        ],
        schema=_SCHEMA,
        brand_id=brand.get("id"),
    )

    title = (out.get("title") or f"{brand.get('name')} vs {competitor}").strip()
    body = (out.get("body_markdown") or "").strip()
    if not body:
        body = _fallback_body(out)

    body_json = {
        "lede": out.get("lede"),
        "comparison_table_markdown": out.get("comparison_table_markdown"),
        "embedded_statistic": out.get("embedded_statistic"),
        "expert_quote": out.get("expert_quote"),
        "outbound_citation_url": out.get("outbound_citation_url"),
        "faq": out.get("faq") or [],
    }
    return GeneratedAsset(
        title=title,
        body_markdown=body,
        body_json=body_json,
        predicted_lift_pct=32.5,  # benchmark headline rate for this format
    )


def _fallback_body(out: dict) -> str:
    parts: list[str] = []
    if out.get("lede"):
        parts.append(out["lede"])
    if out.get("comparison_table_markdown"):
        parts.append(out["comparison_table_markdown"])
    if out.get("embedded_statistic"):
        parts.append(f"> {out['embedded_statistic']}")
    if out.get("expert_quote"):
        parts.append(f"_{out['expert_quote']}_")
    return "\n\n".join(parts)
