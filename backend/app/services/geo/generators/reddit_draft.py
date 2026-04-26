"""Reddit answer-draft generator — surfaces 1-3 likely subreddits + a
draft human-voice reply for each.

Reddit drives 5-21% of citations across engines (peak in Google AI
Overviews at 21%). But auto-posting gets accounts banned and the LLM
citation models actively down-weight low-karma / new-account posts.
This generator NEVER posts — it produces drafts queued for human
approval. The dashboard surfaces them with a "copy to Reddit" CTA so
the founder/team posts from their own credentialed account.
"""

from __future__ import annotations

from typing import Any

from app.services.geo.asset_generator import GeneratedAsset
from app.services.llm.client import chat_json

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subreddit": {"type": "string"},
                    "thread_pattern_to_search": {"type": "string"},
                    "expected_thread_examples": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "draft_reply_markdown": {"type": "string"},
                    "voice_notes": {"type": "string"},
                    "do_not": {"type": "string"},
                },
                "required": [
                    "subreddit",
                    "thread_pattern_to_search",
                    "draft_reply_markdown",
                ],
            },
        },
        "human_in_loop_checklist": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "candidates", "human_in_loop_checklist"],
}


async def generate(brand: dict, gap: dict, recommendation: dict) -> GeneratedAsset:
    outline = recommendation.get("asset_outline") or {}
    key_points = outline.get("key_points") or []

    system = (
        "You are surfacing Reddit answer opportunities for a brand whose "
        "GAP PROMPT is being lost to a competitor in answer engines. Reddit "
        "is high-leverage for citations (5-21% across engines, peak in "
        "Google AI Overviews) BUT auto-posting gets accounts banned and "
        "LLMs down-weight new-account/low-karma posts. NEVER frame the "
        "drafts as 'post this'; they are queued for human approval.\n\n"
        "Output 1-3 candidate subreddit + thread + draft-reply triples. "
        "Each draft_reply_markdown MUST:\n"
        "1) Sound like a real user — first person, casual, no marketing voice\n"
        "2) Mention the brand by name AT MOST ONCE, late in the reply\n"
        "3) Be honest — acknowledge competitor strengths if relevant\n"
        "4) Lead with the answer to the question, not the brand pitch\n"
        "5) Be 80-220 words\n\n"
        "voice_notes is one short sentence on the subreddit's culture; "
        "do_not lists what would get this reply removed/downvoted there. "
        "human_in_loop_checklist is 4-6 items the human reviewer must tick "
        "before posting (account age, karma threshold, disclosure if "
        "founder, no link spam, etc.)."
    )

    facts = (
        f"BRAND: {brand.get('name')} — {brand.get('description') or ''}\n"
        f"GAP PROMPT (people searching this): \"{gap['prompt']}\"\n"
        f"RECOMMENDED KEY POINTS the reply must convey: {key_points}\n"
        f"COMPETITOR WINNING THIS PROMPT: {gap.get('competitor_name')}"
    )

    out = await chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": facts},
        ],
        schema=_SCHEMA,
        brand_id=brand.get("id"),
    )

    title = (out.get("title") or "Reddit answer drafts").strip()
    candidates = out.get("candidates") or []
    checklist = out.get("human_in_loop_checklist") or []

    md_parts: list[str] = [
        "> ⚠ **Human approval required.** Auto-posting Reddit replies gets "
        "accounts banned and LLMs down-weight low-karma posts. Have a "
        "human review and post from a credentialed account."
    ]
    for i, c in enumerate(candidates, start=1):
        md_parts.append(
            f"### Candidate {i} — r/{c.get('subreddit', 'subreddit')}"
        )
        md_parts.append(
            f"**Thread pattern to search:** {c.get('thread_pattern_to_search') or '—'}"
        )
        examples = c.get("expected_thread_examples") or []
        if examples:
            md_parts.append("**Example threads:**")
            md_parts.append("\n".join(f"- {e}" for e in examples))
        md_parts.append("**Draft reply (review before posting):**")
        md_parts.append(c.get("draft_reply_markdown") or "—")
        if c.get("voice_notes"):
            md_parts.append(f"_Subreddit voice:_ {c['voice_notes']}")
        if c.get("do_not"):
            md_parts.append(f"_Avoid:_ {c['do_not']}")

    if checklist:
        md_parts.append("---")
        md_parts.append("### Human-in-loop checklist")
        md_parts.append("\n".join(f"- [ ] {item}" for item in checklist))

    return GeneratedAsset(
        title=title,
        body_markdown="\n\n".join(md_parts),
        body_json={
            "candidates": candidates,
            "human_in_loop_checklist": checklist,
        },
        predicted_lift_pct=8.0,  # conservative — depends on adoption
    )
