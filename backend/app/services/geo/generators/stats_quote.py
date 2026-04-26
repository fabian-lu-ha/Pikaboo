"""Stats + quote injection generator — the Princeton GEO paper's
highest-yield single play.

Drops one specific statistic, one expert quote, and one outbound
citation onto a target page. The arXiv 2311.09735 study showed this
combo lifts position-adjusted citation share 30-40% on average.

Returns BOTH ready-to-paste markdown blocks AND a JSON payload listing
the three injections separately so an integration could splice them
into a CMS field-by-field.
"""

from __future__ import annotations

from typing import Any

from app.services.geo.asset_generator import GeneratedAsset
from app.services.llm.client import chat_json

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "statistic": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "specifics": {"type": "string"},
                "plausible_source": {"type": "string"},
                "source_url": {"type": "string"},
                "where_to_inject": {"type": "string"},
            },
            "required": ["claim", "plausible_source", "where_to_inject"],
        },
        "quote": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "attribution_role": {"type": "string"},
                "attribution_name": {"type": "string"},
                "where_to_inject": {"type": "string"},
            },
            "required": ["text", "attribution_role", "where_to_inject"],
        },
        "outbound_citation": {
            "type": "object",
            "properties": {
                "anchor_text": {"type": "string"},
                "url": {"type": "string"},
                "domain_authority_note": {"type": "string"},
                "where_to_inject": {"type": "string"},
            },
            "required": ["anchor_text", "url", "where_to_inject"],
        },
        "verification_checklist": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "statistic", "quote", "outbound_citation"],
}


async def generate(brand: dict, gap: dict, recommendation: dict) -> GeneratedAsset:
    outline = recommendation.get("asset_outline") or {}
    key_points = outline.get("key_points") or []

    system = (
        "You are proposing three citation-boosting injections for a brand's "
        "existing page that targets the GAP PROMPT. Apply the Princeton GEO "
        "paper's highest-leverage finding: ONE specific stat + ONE expert "
        "quote + ONE outbound citation lifts AI citation share 30-40%.\n\n"
        "Constraints:\n"
        "1) The statistic must be SPECIFIC (e.g. '47% of...', '3.2x faster "
        "than...'). Suggest a plausible_source (a specific industry report "
        "name) and a source_url. NEVER fabricate a fake stat — propose "
        "what the brand should look up if they don't already have it.\n"
        "2) The quote is 1-2 sentences in the voice of a domain expert "
        "(not a brand executive). attribution_role is the expert's job "
        "title; attribution_name can be a placeholder if the brand needs "
        "to source one.\n"
        "3) The outbound citation must point at a high-authority domain "
        "the brand DOES NOT compete with — research papers, .gov, .edu, "
        "Wikipedia, established trade publications. Note the domain's "
        "authority signal in domain_authority_note.\n"
        "4) For each injection, where_to_inject is a short instruction "
        "('after the second paragraph of the intro', 'inside the comparison "
        "table footer', etc.).\n"
        "Also return a verification_checklist (3-5 items) the brand should "
        "tick before publishing the injections."
    )

    facts = (
        f"BRAND: {brand.get('name')} — {brand.get('description') or ''}\n"
        f"BRAND URL: {brand.get('url') or 'unknown'}\n"
        f"GAP PROMPT: \"{gap['prompt']}\"\n"
        f"RECOMMENDED KEY POINTS the injections should reinforce: {key_points}\n"
        f"COMPETITOR WINNING: {gap.get('competitor_name')}\n"
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

    stat = out.get("statistic") or {}
    quote = out.get("quote") or {}
    cite = out.get("outbound_citation") or {}
    title = (out.get("title") or "Stats + quote injections").strip()

    md = (
        "### Statistic to inject\n\n"
        f"**Claim:** {stat.get('claim') or '—'}\n\n"
        f"**Specifics:** {stat.get('specifics') or '—'}\n\n"
        f"**Source to cite:** {stat.get('plausible_source') or '—'} — "
        f"{stat.get('source_url') or 'find/verify URL before publishing'}\n\n"
        f"**Inject:** {stat.get('where_to_inject') or '—'}\n\n"
        "---\n\n"
        "### Expert quote to inject\n\n"
        f"> _\"{(quote.get('text') or '—').strip()}\"_\n"
        f">\n"
        f"> — {quote.get('attribution_name') or 'Source TBD'}, "
        f"{quote.get('attribution_role') or 'expert role'}\n\n"
        f"**Inject:** {quote.get('where_to_inject') or '—'}\n\n"
        "---\n\n"
        "### Outbound citation\n\n"
        f"**Link:** [{cite.get('anchor_text') or 'anchor'}]"
        f"({cite.get('url') or '#'})\n\n"
        f"**Why it helps:** {cite.get('domain_authority_note') or '—'}\n\n"
        f"**Inject:** {cite.get('where_to_inject') or '—'}\n\n"
    )

    checklist = out.get("verification_checklist") or []
    if checklist:
        md += "---\n\n### Verify before publishing\n\n"
        md += "\n".join(f"- [ ] {item}" for item in checklist)

    return GeneratedAsset(
        title=title,
        body_markdown=md,
        body_json={
            "statistic": stat,
            "quote": quote,
            "outbound_citation": cite,
            "verification_checklist": checklist,
        },
        target_url=brand.get("url"),
        predicted_lift_pct=35.0,  # midpoint of the 30-40% Princeton range
    )
