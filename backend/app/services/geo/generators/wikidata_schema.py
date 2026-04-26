"""Wikidata + Organization JSON-LD generator.

Drafts the brand's canonical Organization JSON-LD with `sameAs` pointers
to Wikidata, LinkedIn, Crunchbase, GitHub, and the relevant social
handles — and proposes the Wikidata Q-item statements to populate (or
update) for entity-resolution coverage.

The most under-used high-leverage tag in the 2026 GEO playbook. ChatGPT
pulls ~7.8% of all citations from Wikipedia/Wikidata; Gemini's
Knowledge Graph integration leans heavily on Wikidata Q-items. Both
engines reward brands whose Organization schema's `sameAs` resolves
back into the entity graph.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.geo.asset_generator import GeneratedAsset
from app.services.llm.client import chat_json

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "organization_jsonld": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "alternate_name": {"type": "string"},
                "url": {"type": "string"},
                "description": {"type": "string"},
                "founding_date": {"type": "string"},
                "logo": {"type": "string"},
                "same_as": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["name", "url", "description", "same_as"],
        },
        "wikidata_statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "property": {"type": "string"},
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["property", "label", "value"],
            },
        },
        "wikidata_existing_q_id": {"type": "string"},
        "missing_links_to_create": {
            "type": "array",
            "items": {"type": "string"},
        },
        "notes_for_editor": {"type": "string"},
    },
    "required": [
        "organization_jsonld",
        "wikidata_statements",
        "missing_links_to_create",
    ],
}


async def generate(brand: dict, gap: dict, recommendation: dict) -> GeneratedAsset:
    handles = brand.get("handles") or {}
    handles_summary = ", ".join(f"{k}={v}" for k, v in handles.items()) or "none"

    system = (
        "You are drafting the canonical Organization JSON-LD AND a Wikidata "
        "entity update for a brand, to close a Generative-Engine "
        "Optimization gap. The goal is entity resolution: AI engines should "
        "be able to traverse from the brand's homepage → Wikidata Q-item → "
        "Wikipedia / LinkedIn / Crunchbase and back.\n\n"
        "Constraints:\n"
        "1) organization_jsonld.same_as MUST include candidate URLs for "
        "Wikidata, Wikipedia (if the brand qualifies for an article), "
        "LinkedIn, Crunchbase, and the brand's known social handles. Where "
        "the canonical URL is unknown, propose the most likely URL pattern "
        "and flag it.\n"
        "2) wikidata_statements is a list of properties (P31 instance of, "
        "P452 industry, P856 official website, P1581 official blog, P159 "
        "headquarters location, etc.) that should be populated on the "
        "brand's Wikidata Q-item. Include a one-line rationale per "
        "statement so a human editor knows *why* to add it.\n"
        "3) If the brand has an existing Wikidata Q-item you can infer, "
        "set wikidata_existing_q_id (e.g. 'Q12345'); otherwise leave empty.\n"
        "4) missing_links_to_create lists URLs the brand needs to obtain "
        "before this asset can ship: 'create LinkedIn company page', "
        "'request Wikipedia article (notability bar)', etc.\n"
        "5) notes_for_editor is one paragraph the brand owner should read "
        "before clicking publish."
    )

    facts = (
        f"BRAND NAME: {brand.get('name')}\n"
        f"BRAND URL: {brand.get('url')}\n"
        f"DESCRIPTION: {brand.get('description')}\n"
        f"KNOWN SOCIAL HANDLES: {handles_summary}\n"
        f"GAP PROMPT (the search this entity work targets): \"{gap['prompt']}\"\n"
        f"COMPETITOR WINNING: {gap.get('competitor_name')}\n"
        f"ENGINES MOST CITING ON THIS PROMPT: {gap.get('engines_present')}"
    )

    out = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": facts},
        ],
        schema=_SCHEMA,
        brand_id=brand.get("id"),
    )

    org = out.get("organization_jsonld") or {}
    statements = out.get("wikidata_statements") or []
    existing_q = out.get("wikidata_existing_q_id") or ""
    missing = out.get("missing_links_to_create") or []
    notes = out.get("notes_for_editor") or ""

    json_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": org.get("name") or brand.get("name"),
        "url": org.get("url") or brand.get("url"),
        "description": org.get("description") or brand.get("description"),
    }
    if org.get("alternate_name"):
        json_ld["alternateName"] = org["alternate_name"]
    if org.get("founding_date"):
        json_ld["foundingDate"] = org["founding_date"]
    if org.get("logo"):
        json_ld["logo"] = org["logo"]
    if org.get("same_as"):
        json_ld["sameAs"] = org["same_as"]

    json_ld_html = (
        '<script type="application/ld+json">\n'
        + json.dumps(json_ld, indent=2, ensure_ascii=False)
        + "\n</script>"
    )

    md_parts: list[str] = [
        "### Organization JSON-LD (drop in your homepage `<head>`)",
        "```html\n" + json_ld_html + "\n```",
    ]
    if statements:
        md_parts.append("### Wikidata statements to populate")
        md_parts.append(
            "| Property | Label | Value | Rationale |\n"
            "|---|---|---|---|"
        )
        for s in statements:
            md_parts.append(
                f"| {s.get('property') or '—'} | {s.get('label') or '—'} | "
                f"{s.get('value') or '—'} | {s.get('rationale') or '—'} |"
            )
    if existing_q:
        md_parts.append(
            f"_Existing Wikidata item:_ "
            f"[{existing_q}](https://www.wikidata.org/wiki/{existing_q})"
        )
    if missing:
        md_parts.append("### Before publishing — these URLs need to exist")
        md_parts.append("\n".join(f"- [ ] {item}" for item in missing))
    if notes:
        md_parts.append(f"_Editor note:_ {notes}")

    return GeneratedAsset(
        title=f"{brand.get('name')} — Organization schema + Wikidata update",
        body_markdown="\n\n".join(md_parts),
        body_json={
            "organization_jsonld": json_ld,
            "json_ld_html": json_ld_html,
            "wikidata_statements": statements,
            "wikidata_existing_q_id": existing_q,
            "missing_links_to_create": missing,
            "notes_for_editor": notes,
        },
        target_url=brand.get("url"),
        predicted_lift_pct=15.0,  # high-leverage entity wedge, conservative
    )
