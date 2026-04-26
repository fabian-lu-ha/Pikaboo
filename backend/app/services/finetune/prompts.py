"""Prompt templates for the corpus builder.

Two LLM calls live here:

* ``reverse_brief_messages`` — given a real post, ask Gemini to
  reconstruct the marketing brief that would have produced it. This is
  the trick that lets us train the model on instruction→post pairs
  rather than "predict the next caption" — fine-tuning on instructions
  is what actually transfers voice. See PIONEER_FINETUNING.md §4.

* ``synthetic_pairs_messages`` — given the brand's voice profile,
  generate N (brief, post) pairs grounded in the recurring phrases,
  do/don'ts, and voice excerpt. Used to bump the corpus to the LIMA
  sweet spot when the tenant has only a handful of real posts.
"""

from __future__ import annotations

import json
from typing import Any


REVERSE_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "platform": {"type": "string"},
        "audience": {"type": "string"},
        "goal": {"type": "string"},
        "length": {"type": "string"},
        "brief": {"type": "string"},
    },
    "required": ["platform", "audience", "goal", "length", "brief"],
    "additionalProperties": False,
}


def reverse_brief_messages(
    brand_name: str, platform: str, post_text: str
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a marketing analyst. Given a published post, "
                "reconstruct the 1–2 sentence brief a marketing manager "
                "would have written to produce it. Stay concrete — "
                "name the audience, the goal, and the constraints. "
                "Output JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Brand: {brand_name}\n"
                f"Platform: {platform}\n\n"
                f"Published post:\n\"\"\"\n{post_text[:1800]}\n\"\"\"\n\n"
                "Return: platform (echo), audience (1 phrase — who is this "
                "for?), goal (awareness | engagement | conversion | "
                "announcement | community | other), length (one of: "
                "tweet | caption | short | medium | long), brief (1-2 "
                "sentences in the imperative mood — exactly what a manager "
                "would Slack to a copywriter)."
            ),
        },
    ]


SYNTHETIC_PAIRS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string"},
                    "brief": {"type": "string"},
                    "caption": {"type": "string"},
                    "hashtags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "cta": {"type": "string"},
                },
                "required": [
                    "platform",
                    "brief",
                    "caption",
                    "hashtags",
                    "cta",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["pairs"],
    "additionalProperties": False,
}


def synthetic_pairs_messages(
    brand_name: str,
    voice_profile: dict[str, Any],
    n: int,
    vocabulary_hint: str = "",
) -> list[dict[str, str]]:
    """Ask Gemini to expand the voice profile into N synthetic pairs.

    These are *not* hallucinated training data — they're grounded in the
    voice excerpt + do/don'ts + recurring phrases. When a GLiNER2-derived
    ``vocabulary_hint`` is supplied, it's pasted into the system prompt
    so the synthetic posts use the brand's actual product names and
    recurring phrases verbatim, not generic stand-ins. Quality drops
    once N exceeds ~30 per call; the orchestrator chunks larger asks.
    """
    profile_text = json.dumps(voice_profile, ensure_ascii=False, indent=2)
    vocabulary_block = (
        f"\n\n{vocabulary_hint}" if vocabulary_hint else ""
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a senior copywriter trained on a brand's voice "
                "profile. Generate diverse, realistic marketing pairs "
                "(brief → post) in this voice. Each post must respect "
                "the recurring phrases, do/don'ts, and the cadence in "
                "the voice excerpt. Vary platform, audience, goal, and "
                "tone within the brand's range. Output JSON only."
                + vocabulary_block
            ),
        },
        {
            "role": "user",
            "content": (
                f"Brand: {brand_name}\n\n"
                f"Voice profile:\n{profile_text}\n\n"
                f"Return {n} pairs. Use a mix of platforms "
                "(instagram, linkedin, x, blog_intro, email_subject). "
                "Briefs must be 1-2 sentences imperative. Captions must "
                "feel like the brand wrote them — never generic. "
                "Hashtags optional (empty array allowed). CTA can be "
                "an empty string when the format doesn't take one."
            ),
        },
    ]


def voice_system_prompt(brand_name: str, voice_profile: dict[str, Any]) -> str:
    """The system prompt that goes on every JSONL line.

    This is the prompt Pioneer trains *the model* to obey, and it's also
    what we'll send at inference time. Keep it stable across pairs — if
    the system prompt drifts between training rows, the LoRA learns
    "ignore the system prompt" instead of "obey this voice".
    """
    tone = (voice_profile.get("tone") or "").strip()
    recurring = voice_profile.get("recurring_phrases") or []
    do = voice_profile.get("do") or []
    dont = voice_profile.get("dont") or []
    excerpt = (voice_profile.get("voice_excerpt") or "").strip()

    parts = [
        f"You write in the voice of {brand_name}.",
    ]
    if tone:
        parts.append(f"Tone: {tone}")
    if recurring:
        parts.append("Recurring phrases: " + " · ".join(recurring[:10]))
    if do:
        parts.append("Always: " + " · ".join(do[:8]))
    if dont:
        parts.append("Never: " + " · ".join(dont[:8]))
    if excerpt:
        parts.append(f"Voice sample: {excerpt}")
    parts.append(
        'When asked for a draft, return JSON of the form '
        '{"caption": "...", "hashtags": [...], "cta": "..."}. '
        "Hashtags array may be empty. CTA may be an empty string."
    )
    return "\n\n".join(parts)


def render_user_turn(brief: str, platform: str) -> str:
    return f"Platform: {platform}\nBrief: {brief}".strip()


def render_assistant_turn(
    caption: str, hashtags: list[str] | None, cta: str | None
) -> str:
    """Render the assistant turn as JSON — matches what chat_json expects."""
    return json.dumps(
        {
            "caption": caption,
            "hashtags": hashtags or [],
            "cta": cta or "",
        },
        ensure_ascii=False,
    )
