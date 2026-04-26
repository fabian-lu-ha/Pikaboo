"""Definition-first rewrite generator.

Rewrites the lede + first-30%-of-page block on a target page so it opens
with a clean definitional sentence ('X is a Y that does Z'). Per the
ConvertMate 2026 GEO benchmark, 44.2% of all AI citations come from the
first 30% of a page; definition-first ledes get chunked cleanly by
retrievers and are disproportionately picked up.
"""

from __future__ import annotations

from typing import Any

from app.services.geo.asset_generator import GeneratedAsset
from app.services.llm.client import chat_json

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "definition_sentence": {"type": "string"},
        "second_sentence": {"type": "string"},
        "lede_paragraph": {"type": "string"},
        "first_section_heading": {"type": "string"},
        "first_section_body": {"type": "string"},
        "anti_pattern_to_replace": {"type": "string"},
        "guidance_for_editor": {"type": "string"},
    },
    "required": [
        "title",
        "definition_sentence",
        "lede_paragraph",
        "first_section_body",
    ],
}


async def generate(brand: dict, gap: dict, recommendation: dict) -> GeneratedAsset:
    outline = recommendation.get("asset_outline") or {}
    key_points = outline.get("key_points") or []

    system = (
        "You are rewriting the OPENING of a brand's existing page so it gets "
        "chunked cleanly by LLM retrievers and surfaces in answer engines. "
        "Constraints (all required):\n"
        "1) The first sentence MUST be definition-first in the form "
        "'<Brand>/<concept> is a <category> that <does X>.' No throat-clearing.\n"
        "2) The second sentence answers the gap prompt directly (one sentence).\n"
        "3) The lede paragraph is 2-3 sentences. Inverted pyramid — answer "
        "first, context after.\n"
        "4) The first section heading is a question users actually search.\n"
        "5) The first section body is 120-180 words, dense (entities + "
        "specifics), no marketing fluff.\n"
        "Also call out one anti-pattern lede this rewrite replaces (e.g. "
        "'In today's fast-paced world…') and short guidance the editor "
        "should follow when applying the change."
    )

    facts = (
        f"BRAND: {brand.get('name')} — {brand.get('description') or ''}\n"
        f"BRAND URL (the page being rewritten): {brand.get('url') or 'unknown'}\n"
        f"GAP PROMPT (this rewrite must answer it within the first 30% "
        f"of the page): \"{gap['prompt']}\"\n"
        f"RECOMMENDED KEY POINTS: {key_points}\n"
        f"VOICE PROFILE: {brand.get('voice_profile')}\n"
        f"COMPETITOR WINNING ON THIS PROMPT: {gap.get('competitor_name')}"
    )

    out = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": facts},
        ],
        schema=_SCHEMA,
        brand_id=brand.get("id"),
    )

    title = (out.get("title") or "Definition-first lede rewrite").strip()
    body_parts: list[str] = []
    if out.get("definition_sentence"):
        body_parts.append(f"**Definition sentence**\n\n{out['definition_sentence']}")
    if out.get("lede_paragraph"):
        body_parts.append(f"**Lede paragraph**\n\n{out['lede_paragraph']}")
    if out.get("first_section_heading"):
        body_parts.append(f"## {out['first_section_heading']}")
    if out.get("first_section_body"):
        body_parts.append(out["first_section_body"])
    if out.get("anti_pattern_to_replace"):
        body_parts.append(
            f"_Anti-pattern this replaces:_ {out['anti_pattern_to_replace']}"
        )
    if out.get("guidance_for_editor"):
        body_parts.append(
            f"_Editor guidance:_ {out['guidance_for_editor']}"
        )
    body_markdown = "\n\n".join(body_parts)

    return GeneratedAsset(
        title=title,
        body_markdown=body_markdown,
        body_json={
            "definition_sentence": out.get("definition_sentence"),
            "second_sentence": out.get("second_sentence"),
            "lede_paragraph": out.get("lede_paragraph"),
            "first_section_heading": out.get("first_section_heading"),
            "first_section_body": out.get("first_section_body"),
            "anti_pattern_to_replace": out.get("anti_pattern_to_replace"),
        },
        target_url=brand.get("url"),
        predicted_lift_pct=44.2,
    )
