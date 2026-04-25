"""Channel registry — defines how the agent drafts per platform.

Each channel has a text format (length + idiom) and optionally an image
slot with a specific aspect + role. The agent loop iterates channels and
produces one text + one image per channel, instead of a fixed
'blog + linkedin + hero' bundle.

Schema is research-grounded — see docs/CHANNEL_PLAYBOOK.md for sourcing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ChannelImage:
    aspect: str               # display aspect ("1.91:1", "1:1", "16:9", "9:16")
    aspect_label: str         # human label ("landscape banner", "square", ...)
    role: str                 # what the image IS ("LinkedIn feed banner", ...)
    target_px: tuple[int, int]  # rendered output dimensions
    gen_aspect: str           # nano-banana-supported aspect (snap if needed)


@dataclass(frozen=True)
class Channel:
    id: str
    label: str
    glyph: str                # short UI mark ("in", "ig", "x", "📰", ...)
    text_kind: Literal["post", "caption", "tweet", "article", "script", "email"]
    word_min: int
    word_max: int
    image: ChannelImage | None
    tint: str                 # hex for UI accent
    schema_field: str         # JSON key in the LLM response
    idiom_notes: str          # 2-3 sentence drafting guidance
    voice_adaptation_note: str  # how the channel modulates brand voice
    anti_patterns: list[str]  # AI-slop tells specific to this channel
    image_composition_note: str = ""  # what the image should look like (composition only)


# Nano-banana-pro supported aspect ratios (verified):
#   1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9
# 1.91:1 is NOT supported — snap LinkedIn banner to 16:9, accept the small crop.

CHANNELS: dict[str, Channel] = {
    "linkedin": Channel(
        id="linkedin",
        label="LinkedIn",
        glyph="in",
        text_kind="post",
        word_min=130,
        word_max=220,
        image=ChannelImage(
            aspect="1.91:1",
            aspect_label="landscape banner",
            role="LinkedIn feed banner",
            target_px=(1200, 627),
            gen_aspect="16:9",  # 1.91:1 unsupported → 16:9 source, optional crop
        ),
        tint="#0a66c2",
        schema_field="post",
        idiom_notes=(
            "Hook in line 1 (provocative question / surprising stat / story teaser) — "
            "first ~210 chars sit above the 'see more' fold and act as the headline. "
            "Body in short 1-2 line paragraphs. End with a concrete CTA. "
            "Hashtags 3-5, at the END only. External links cost reach — drop in first comment if needed."
        ),
        voice_adaptation_note=(
            "80% brand voice + 20% polish. Slightly more formal sentence structure. "
            "Keep recurring_phrases. Swap slang for crisp business prose. "
            "Story arc with one personal beat."
        ),
        anti_patterns=[
            "'I'm excited to announce' / 'I'm thrilled to' openers",
            "hashtag-soup mid-sentence",
            "stock corporate handshake / open-plan office imagery",
            "AI 3D chrome / shiny render aesthetic",
        ],
        image_composition_note=(
            "Editorial banner. Restrained palette (primary + 1 accent). "
            "Strong typographic hierarchy if any text overlay. One focal subject. "
            "Caption-safe negative space. Looks like a magazine cover, not an ad."
        ),
    ),
    "instagram": Channel(
        id="instagram",
        label="Instagram",
        glyph="ig",
        text_kind="caption",
        word_min=60,
        word_max=110,
        image=ChannelImage(
            aspect="1:1",
            aspect_label="square",
            role="Instagram feed post",
            target_px=(1080, 1080),
            gen_aspect="1:1",
        ),
        tint="#e1306c",
        schema_field="caption",
        idiom_notes=(
            "Front-load hook in first 125 chars (everything after = 'more' link). "
            "2-3 short paragraphs with line breaks for visual rhythm. Soft CTA "
            "('save for later', 'tag someone who…'). Hashtags 3-5 in FIRST COMMENT, "
            "not in the caption — Meta deprioritised hashtags in 2026."
        ),
        voice_adaptation_note=(
            "100% brand voice. More emotional, more direct address ('you'), "
            "more line breaks. Recurring phrases up-weighted."
        ),
        anti_patterns=[
            "rendered text-as-button ('LEARN MORE') in image",
            "perfectly symmetric 'logo on background' tile (2018 ad look)",
            "neon AI gradients / shiny chrome 3D",
            "watermarked TikTok re-uploads (Meta deprioritises)",
        ],
        image_composition_note=(
            "Lifestyle, product-in-context, in-hand or on-set. Off-centre composition. "
            "Saturated, full brand palette in play. Warm. Photographic over illustrated "
            "unless brand is illustrated. Room for caption-overlay if any."
        ),
    ),
    "x": Channel(
        id="x",
        label="X",
        glyph="𝕏",
        text_kind="tweet",
        word_min=12,
        word_max=50,
        image=ChannelImage(
            aspect="16:9",
            aspect_label="landscape",
            role="tweet image",
            target_px=(1200, 675),
            gen_aspect="16:9",
        ),
        tint="#0f1419",
        schema_field="tweet",
        idiom_notes=(
            "STRICT 280-character ceiling. ONE distilled thought — a statistic, "
            "a contrarian take, or a quotable line. No threads. Hashtags 0-1 "
            "only if it's a known community tag. External links go in a reply, "
            "not the main post (links cost reach)."
        ),
        voice_adaptation_note=(
            "100% brand voice, distilled. Cut every adjective that isn't doing work. "
            "Single thought, ideally with one stat or sharp claim. Quotable."
        ),
        anti_patterns=[
            "tile with the tweet's own text rendered into the image",
            "screenshot of an article (lazy)",
            "generic AI scenery as wallpaper behind a quote",
            "text crammed corner-to-corner",
        ],
        image_composition_note=(
            "Single statement. Generous negative space. Bold and readable at small "
            "thumbnail size. One product shot, one chart, or one quote card — never all three."
        ),
    ),
    "blog": Channel(
        id="blog",
        label="Blog",
        glyph="📰",
        text_kind="article",
        word_min=350,
        word_max=450,
        image=ChannelImage(
            aspect="16:9",
            aspect_label="landscape",
            role="blog header",
            target_px=(1600, 900),
            gen_aspect="16:9",
        ),
        tint="#22a07a",
        schema_field="body",
        idiom_notes=(
            "Listicle structure: hook → 3-5 numbered or bulleted points → "
            "ONE quotation block (1-2 sentences in quotes/italics) → ONE statistic "
            "callout (specific % or Nx claim) → conclusion + CTA. The quote block + "
            "statistic boost AI-search (GEO) visibility per the KDD 2024 GEO paper. "
            "Markdown."
        ),
        voice_adaptation_note=(
            "100% brand voice, fully expanded. Recurring phrases naturally placed. "
            "Tone matches the brand's published essays."
        ),
        anti_patterns=[
            "title rendered into the header image (H1 is already on the page)",
            "stock-photo of a laptop on a desk",
            "'AI-generated abstract concept of [topic]' — dated",
        ],
        image_composition_note=(
            "Editorial illustration or photograph. Supports the article hierarchy "
            "without competing — soft enough that an H1 reads on top. NO embedded title text."
        ),
    ),
}

DEFAULT_CHANNELS: list[str] = ["linkedin", "instagram", "x", "blog"]


def schema_for(channel: Channel) -> dict:
    """JSON schema Gemini returns for this channel's text draft."""
    if channel.id == "blog":
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {channel.schema_field: {"type": "string"}},
        "required": [channel.schema_field],
        "additionalProperties": False,
    }


def extract_text(channel: Channel, draft: dict | None) -> tuple[str, str]:
    """Returns (title, body) for any channel."""
    if not draft:
        return "", ""
    if channel.id == "blog":
        return str(draft.get("title", "")), str(draft.get("body", ""))
    return "", str(draft.get(channel.schema_field, ""))


_WORD_HINTS: dict[str, list[str]] = {
    "linkedin": ["linkedin", "li post", "linked in"],
    "instagram": ["instagram", "ig", "insta", "reel"],
    "x": ["twitter", "tweet", "x post", " x ", " x,"],
    "blog": ["blog", "article", "blog post"],
}


def resolve_channels(
    brand_data: dict, user_text: str
) -> list[Channel]:
    """Pick the channels to draft for, in priority order.

    Priority:
      1. Explicit channel mentions in the user's request — `for LinkedIn + IG`
         picks {linkedin, instagram}.
      2. Brand's known publishing handles — if `brand.handles` has linkedin/x,
         include those + always include `blog` as a default text channel.
      3. Fallback to DEFAULT_CHANNELS (linkedin, instagram, x, blog).
    """
    text_lower = " " + (user_text or "").lower() + " "

    explicit: list[Channel] = []
    seen: set[str] = set()
    for cid, hints in _WORD_HINTS.items():
        for h in hints:
            if re.search(r"\b" + re.escape(h.strip()) + r"\b", text_lower):
                if cid not in seen:
                    explicit.append(CHANNELS[cid])
                    seen.add(cid)
                break
    if explicit:
        return explicit

    handles = brand_data.get("handles") or {}
    chosen: list[Channel] = []
    for cid in ("linkedin", "instagram", "x"):
        if cid in handles and cid not in seen:
            chosen.append(CHANNELS[cid])
            seen.add(cid)
    if "blog" not in seen:
        chosen.append(CHANNELS["blog"])
        seen.add("blog")
    if chosen:
        return chosen

    return [CHANNELS[c] for c in DEFAULT_CHANNELS]
