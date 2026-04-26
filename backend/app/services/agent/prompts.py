"""LLM prompts for the agent loop's drafting steps. Channel-aware.

Stack (per docs/CHANNEL_PLAYBOOK.md §4):
  1. Brand voice profile (the stable personality)
  2. Channel idiom notes (research-grounded drafting guidance)
  3. Voice adaptation note (how the channel modulates that voice)
  4. Channel anti-patterns (what NOT to do — explicit AI-slop tells)
  5. User request (last, freshest context)
"""

from app.services.agent.channels import Channel
from app.services.research.orchestrator import research_to_prompt_block


def _voice_block(brand: dict) -> str:
    voice = brand.get("voice_profile") or {}
    if not voice:
        return ""
    return (
        "Brand voice profile (match this exactly):\n"
        f"- Tone: {voice.get('tone', '')}\n"
        f"- Recurring phrases: "
        f"{', '.join(voice.get('recurring_phrases', [])[:10])}\n"
        f"- Do: {' / '.join(voice.get('do', [])[:5])}\n"
        f"- Don't: {' / '.join(voice.get('dont', [])[:5])}\n"
        f"- Sample voice: {voice.get('voice_excerpt', '')}\n"
    )


def _recent_posts_block(brand: dict, max_posts: int = 4) -> str:
    """Concrete examples from real posts beat abstract voice instructions.
    Pulls captions across all platforms (top N most recent) so the model
    sees the brand's actual cadence + sentence structure."""
    posts = brand.get("recent_posts") or []
    pasted = (brand.get("pasted_posts") or "").strip()
    examples: list[str] = []
    if pasted:
        # User-pasted posts get top weight — they're explicitly hand-picked.
        for chunk in pasted.split("\n\n")[:2]:
            chunk = chunk.strip()
            if chunk:
                examples.append(f"[user-pasted]\n{chunk[:400]}")
    for p in posts[:max_posts]:
        cap = (p.get("caption") or "").strip()
        if not cap:
            continue
        platform = p.get("platform") or "post"
        examples.append(f"[{platform}]\n{cap[:300]}")
        if len(examples) >= max_posts + 2:
            break
    if not examples:
        return ""
    return (
        "Real published posts from this brand (mimic the rhythm + register, "
        "do not paraphrase or copy):\n"
        + "\n---\n".join(examples)
    )


def _reference_brands_block(brand: dict, max_refs: int = 3) -> str:
    """Reference brands the user picked as 'aspire to write/look like these'.
    Surface their voice_excerpts so the model can borrow cadence."""
    refs = brand.get("reference_brands") or []
    if not refs:
        return ""
    lines: list[str] = []
    for r in refs[:max_refs]:
        name = (r.get("name") or "(reference)").strip()
        excerpt = (r.get("voice_excerpt") or "").strip()
        if not excerpt:
            continue
        lines.append(f"- {name}: {excerpt[:240]}")
    if not lines:
        return ""
    return (
        "Reference brands the team admires (borrow rhythm + register, "
        "do not copy or name them):\n" + "\n".join(lines)
    )


def _research_block(brand: dict) -> str:
    """Combine the persisted brand-level research (set during onboarding)
    with the freshly-pulled campaign-level research (set on this run) into
    one grounding block. Campaign sources go first because they're tied to
    the user's actual request; brand sources are background context."""
    parts: list[str] = []
    camp = brand.get("_campaign_research") or {}
    if camp.get("sources") or camp.get("answer"):
        block = research_to_prompt_block(
            camp.get("sources") or [], camp.get("answer")
        )
        if block:
            parts.append("# Live web research for this request\n" + block)
    brand_research = brand.get("research") or {}
    if brand_research.get("sources") or brand_research.get("answer"):
        block = research_to_prompt_block(
            brand_research.get("sources") or [],
            brand_research.get("answer"),
            cap=8,
        )
        if block:
            parts.append("# Brand background research\n" + block)
    return "\n\n".join(parts)


def _competitor_block(brand: dict) -> str:
    comps = brand.get("competitors") or []
    if not comps:
        return ""
    lines = [
        f"- {c['name']}: {c.get('reason') or '(no reason)'}"
        for c in comps[:5]
    ]
    return "Competitors (for context — do not copy):\n" + "\n".join(lines)


def _system_for(channel: Channel) -> str:
    word_range = f"{channel.word_min}-{channel.word_max} words"
    role_line = {
        "linkedin": "You are drafting a LinkedIn post in the brand's exact voice.",
        "instagram": "You are drafting an Instagram feed caption in the brand's voice.",
        "x": "You are drafting a single tweet in the brand's voice.",
        "blog": "You are drafting a blog post in the brand's voice.",
    }.get(channel.id, f"You are drafting a {channel.text_kind} in the brand's voice.")

    parts = [
        role_line,
        f"Length target: {word_range}.",
        f"Channel idiom (follow precisely): {channel.idiom_notes}",
        f"Voice adaptation: {channel.voice_adaptation_note}",
    ]
    if channel.anti_patterns:
        # Only the text-side anti-patterns matter here (image ones go in image_gen).
        # We pass the full list — they're short and the LLM picks the relevant ones.
        parts.append(
            "Avoid these AI-slop tells: "
            + "; ".join(channel.anti_patterns)
            + "."
        )
    parts.append("Output JSON only.")
    return " ".join(parts)


def channel_post_messages(
    brand: dict, channel: Channel, user_request: str
) -> list[dict]:
    output_hint = (
        "Output: { title (string ≤ 80 chars), body (markdown string) }."
        if channel.id == "blog"
        else f"Output: {{ {channel.schema_field} (string) }}."
    )
    return [
        {"role": "system", "content": _system_for(channel)},
        {
            "role": "user",
            "content": (
                f"Brand: {brand.get('name', '')}\n"
                f"Description: {brand.get('description') or ''}\n\n"
                f"{_voice_block(brand)}\n"
                f"{_recent_posts_block(brand)}\n\n"
                f"{_reference_brands_block(brand)}\n\n"
                f"{_competitor_block(brand)}\n\n"
                f"{_research_block(brand)}\n\n"
                f"User request: {user_request}\n\n"
                f"{output_hint}"
            ),
        },
    ]
