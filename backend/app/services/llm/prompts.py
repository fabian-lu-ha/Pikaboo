VOICE_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "tone": {"type": "string"},
        "recurring_phrases": {"type": "array", "items": {"type": "string"}},
        "do": {"type": "array", "items": {"type": "string"}},
        "dont": {"type": "array", "items": {"type": "string"}},
        "voice_excerpt": {"type": "string"},
    },
    "required": ["tone", "recurring_phrases", "do", "dont", "voice_excerpt"],
    "additionalProperties": False,
}


def voice_profile_messages(
    brand_name: str,
    body_markdown: str,
    pasted_posts: str | None = None,
) -> list[dict]:
    body = (body_markdown or "")[:3000]
    posts_block = ""
    if pasted_posts:
        cleaned = pasted_posts.strip()[:2500]
        if cleaned:
            posts_block = (
                f"\n\nUser-provided posts (highest signal — these are how "
                f"the brand actually writes today):\n\n{cleaned}\n"
            )
    return [
        {
            "role": "system",
            "content": (
                "You are a brand-voice analyst. Given a company's website copy "
                "(and optionally a few of their best posts), extract a structured "
                "profile of how they talk. Be specific, not generic. Quote "
                "phrases verbatim where helpful. When the user provides posts, "
                "weight those more heavily than the marketing site copy — they "
                "are how the brand actually writes day-to-day. Output JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Company: {brand_name}\n\n"
                f"Site copy (markdown):\n\n{body}"
                f"{posts_block}\n"
                "Return: tone (1-3 sentences), recurring_phrases (5-10), "
                "do (5 short imperatives — things they always do), "
                "dont (5 things they avoid), "
                "voice_excerpt (one short paragraph in their exact voice, "
                "written by you)."
            ),
        },
    ]


COMPETITORS_SCHEMA = {
    "type": "object",
    "properties": {
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "url", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["competitors"],
    "additionalProperties": False,
}


def competitors_messages(
    brand_name: str, description: str | None, body_markdown: str
) -> list[dict]:
    body = (body_markdown or "")[:2500]
    return [
        {
            "role": "system",
            "content": (
                "You are a competitive analyst. Given a company's profile, list "
                "5 credible direct competitors. Use real, specific companies "
                "with active public websites (homepage, blog, product pages). "
                "Do NOT guess at speculative or newly-registered domain names — "
                "if you're unsure a company exists, skip it. "
                "No phrasing like 'large incumbents such as X.' Output JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Company: {brand_name}\n"
                f"Description: {description or '(unknown)'}\n\n"
                f"Site copy:\n\n{body}\n\n"
                "Return 5 competitors with: name, url (best guess at root domain, "
                "e.g. 'https://linear.app'), reason (one sentence — why they "
                "compete)."
            ),
        },
    ]
