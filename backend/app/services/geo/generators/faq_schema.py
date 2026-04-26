"""FAQ block + FAQPage JSON-LD generator.

Schema'd pages are cited 8.2x more often per the Averi 2026 study; FAQ/
HowTo specifically lifts citation odds 78%. This generator emits BOTH
the human-readable Q&A markdown for the page body AND the JSON-LD
payload to drop into the page <head>.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.geo.asset_generator import GeneratedAsset
from app.services.llm.client import chat_json

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "faqs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer_markdown": {"type": "string"},
                    "answer_plain": {"type": "string"},
                },
                "required": ["question", "answer_markdown", "answer_plain"],
            },
        },
        "intro": {"type": "string"},
    },
    "required": ["title", "faqs"],
}


async def generate(brand: dict, gap: dict, recommendation: dict) -> GeneratedAsset:
    outline = recommendation.get("asset_outline") or {}
    key_points = outline.get("key_points") or []

    system = (
        "You are generating an FAQ block + FAQPage JSON-LD for an answer-"
        "engine optimization workflow. Output 6-10 Q&A pairs. Constraints:\n"
        "1) The first question MUST literally restate the gap prompt "
        "verbatim (or near-verbatim). LLM retrievers prefer exact-match Q's.\n"
        "2) Each answer is 40-90 words, dense and definitional. Use "
        "specifics (numbers, named features) over abstractions.\n"
        "3) Answers must NOT be self-promotional or end with a CTA — they "
        "must read like a knowledge base, not marketing copy.\n"
        "4) Mix question types: definitional, comparative, how-to, when-to, "
        "edge-case. answer_markdown may use light formatting; answer_plain "
        "is the same content stripped of markdown for the JSON-LD payload.\n"
        "Also write a 1-2 sentence intro paragraph for the FAQ block."
    )

    facts = (
        f"BRAND: {brand.get('name')} — {brand.get('description') or ''}\n"
        f"GAP PROMPT (must be Q1): \"{gap['prompt']}\"\n"
        f"RECOMMENDED KEY POINTS to cover across the Q&A: {key_points}\n"
        f"COMPETITOR WINNING THIS PROMPT: {gap.get('competitor_name')}\n"
        f"ENGINES PRESENT: {gap.get('engines_present')}"
    )

    out = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": facts},
        ],
        schema=_SCHEMA,
        brand_id=brand.get("id"),
    )

    title = (out.get("title") or "FAQ block").strip()
    intro = (out.get("intro") or "").strip()
    faqs = out.get("faqs") or []

    md_parts: list[str] = []
    if intro:
        md_parts.append(intro)
    for f in faqs:
        q = (f.get("question") or "").strip()
        a = (f.get("answer_markdown") or "").strip()
        if q and a:
            md_parts.append(f"### {q}\n\n{a}")

    json_ld = _build_faq_json_ld(faqs)
    md_parts.append("**FAQPage JSON-LD (drop in `<head>`):**\n")
    md_parts.append("```html\n" + json_ld + "\n```")
    body_markdown = "\n\n".join(md_parts)

    return GeneratedAsset(
        title=title,
        body_markdown=body_markdown,
        body_json={
            "intro": intro,
            "faqs": faqs,
            "json_ld_html": json_ld,
        },
        predicted_lift_pct=78.0,
    )


def _build_faq_json_ld(faqs: list[dict]) -> str:
    items = []
    for f in faqs:
        q = (f.get("question") or "").strip()
        a = (f.get("answer_plain") or f.get("answer_markdown") or "").strip()
        if not q or not a:
            continue
        items.append(
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": a,
                },
            }
        )
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": items,
    }
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n</script>"
    )
