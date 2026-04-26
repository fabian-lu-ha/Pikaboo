"""LLM-driven storyboard *plan* for the marketing-video surface.

Reads the latest onboarded brand + the most recent campaign bundle and asks
the *planning* model (Gemini 3.1 Pro Preview) to produce a structured plan
for a 12-15s marketing video:

  - narrative: premise, arc beats, tone — the story the video tells
  - cast: 3-5 recurring visual ingredients (character / setting / prop /
    product). Each cast member must justify its existence with a
    `narrative_purpose`; fragmentary or abstract entities (body parts,
    moods, times-of-day, lighting) are not valid ingredients.
  - frames: 4-6 scenes, each with a *visual* prompt (no text content), a
    motion direction (Veo input), a caption, a duration, the cast it
    references, and a 9-cell focal_zone for caption placement.

Total runtime works out to ~12-15s of footage. Each frame becomes one Veo
clip; Remotion concatenates them and overlays brand-typographic captions.

Mirrors the brand-loading pattern in `app.services.agent.loop._load_latest_brand`
without importing it (we don't depend on the agent module for video).
"""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.services.brand_book import load_pic
from app.services.llm.client import chat_json
from app.services.video_gen.cast import CastMember, auto_bind_brand_assets

log = logging.getLogger(__name__)

# Number of keyframes the storyboard always returns. The Remotion side is
# pinned to this count for the demo; tweak both ends together if changed.
FRAME_COUNT = 6

# Per-frame duration bounds we tell the LLM and validate against.
# Veo natively renders 2-8 seconds per clip; the LLM picks within that.
DURATION_MIN_MS = 2000
DURATION_MAX_MS = 4000

# Caption length cap, matched at the API boundary too.
CAPTION_MAX_WORDS = 8


_FOCAL_ZONES: tuple[str, ...] = (
    "tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br",
)
_CAST_KINDS: tuple[str, ...] = ("character", "setting", "prop", "product")
_FRAME_KINDS: tuple[str, ...] = ("live_action", "design_sequence")
_DESIGN_TEMPLATES: tuple[str, ...] = (
    "gradient_kinetic",   # Linear/Vercel release reel — bold gradient + kinetic headline
    "spec_card",          # Apple keynote — huge metric + small label, counter punch
    "ui_zoom",            # Stripe demo — start zoomed-out on screenshot, push into focal region
    "code_window",        # Vercel/GitHub — macOS code window, type-in animation
    "logo_reveal",        # Wieden+Kennedy — wordmark builds + brand stinger flash
    "comparison_split",   # Apple "Switch" — before/after split with desat→full-color reveal
    "text_scroll",        # End-credits scroll — vertical line-by-line drift, overlay or full-bg
    "headline_punch",     # Apple keynote single-headline — overshoot scale + zoom-past exit
    "word_kinetic",       # Wieden+Kennedy multi-word kinetic typography, per-word animations
    "canvas_kinetic",     # HYBRID — nano-banana stylized backdrop + Remotion kinetic typography
)
# Allowed motion variants for canvas_kinetic. Same names as the underlying
# kinetic templates the foreground reuses (HeadlinePunch / TextScroll /
# WordKinetic). Default is `punch` — single hero headline reveal.
_CANVAS_KINETIC_MOTIONS: tuple[str, ...] = ("punch", "scroll", "word_kinetic")
# Motion-graphics overlays Remotion renders ON TOP of each Veo clip.
# These are NOT baked into the video — they're the typography/motion-graphics
# layer that lifts the output above generic AI-stock-video aesthetics.
_EFFECT_KINDS: tuple[str, ...] = (
    "kinetic_text",   # animated word/phrase accent (NOT the caption — caption is always present, this is punctuation)
    "lower_third",    # bottom info bar with title + optional subtitle
    "brand_stinger",  # short brand-color flash with optional wordmark
    "spotlight",      # dim everything except a focal region
    "kinetic_lines",  # animated geometric lines (diagonal/horizontal/underline/frame)
    "data_pop",       # animated number / percentage / metric reveal
)


_STORYBOARD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "aspect": {
            "type": "string",
            "enum": ["16:9", "9:16", "1:1"],
        },
        "narrative": {
            "type": "object",
            "properties": {
                "premise": {"type": "string"},
                "arc": {"type": "string"},
                "tone": {"type": "string"},
            },
            "required": ["premise", "arc", "tone"],
        },
        # Director's brief — the cinematic vision every shot inherits.
        # Authored once at plan time, threaded into every Veo /scene call so
        # the look is unified across all clips. Keep each field concrete
        # (lens, light, grade) — generic vibes ("cinematic", "premium") are
        # rejected at validation time.
        "cinematic_brief": {
            "type": "object",
            "properties": {
                "reference_films": {"type": "string"},
                "lensing": {"type": "string"},
                "lighting": {"type": "string"},
                "palette_grade": {"type": "string"},
                "pacing": {"type": "string"},
                "do_not": {"type": "string"},
            },
            "required": [
                "reference_films",
                "lensing",
                "lighting",
                "palette_grade",
                "pacing",
                "do_not",
            ],
        },
        # Voiceover spec — Gemini TTS reads `script` over the rendered
        # video. `voice_persona` is prepended to the script as a style
        # directive ("Say warmly, slowly..."); `voice_name` picks a
        # built-in Gemini voice.
        "voiceover": {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "voice_persona": {"type": "string"},
                "voice_name": {
                    "type": "string",
                    "enum": [
                        "Aoede", "Charon", "Fenrir", "Kore", "Leda",
                        "Orus", "Puck", "Schedar", "Vindemiatrix", "Zephyr",
                    ],
                },
            },
            "required": ["script", "voice_persona", "voice_name"],
        },
        # Title-card opener — a brand-typographic hook that plays before the
        # first Veo clip. Pure typography, no video. Optional.
        "title_card": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        # End-card with CTA — plays after the last clip. Two-line: headline
        # then call-to-action. Optional.
        "end_card": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "cta": {"type": "string"},
            },
            "required": ["headline", "cta"],
        },
        "cast": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": list(_CAST_KINDS)},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                    "narrative_purpose": {"type": "string"},
                    "neutral_pose_hint": {"type": "string"},
                    "binding": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["brand_asset", "needs_generation"],
                            },
                            "asset_index": {"type": "integer"},
                        },
                        "required": ["type"],
                    },
                },
                "required": [
                    "id",
                    "kind",
                    "role",
                    "description",
                    "narrative_purpose",
                    "binding",
                ],
            },
        },
        "frames": {
            "type": "array",
            "minItems": FRAME_COUNT,
            "maxItems": FRAME_COUNT,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    # Frame kind discriminator. live_action = Veo clip + caption
                    # (the default; legacy frames omit `kind` entirely and
                    # _normalize_storyboard treats them as live_action).
                    # design_sequence = pure-graphic Remotion template, no Veo
                    # clip. The planner picks per beat.
                    "kind": {
                        "type": "string",
                        "enum": list(_FRAME_KINDS),
                    },
                    # live_action: full visual scene description for Veo.
                    # design_sequence: human-readable summary for the editor UI
                    # (the actual content is in `template` + `template_params`).
                    "prompt": {"type": "string"},
                    "motion": {"type": "string"},
                    "caption": {"type": "string"},
                    "duration_ms": {
                        "type": "integer",
                        "minimum": DURATION_MIN_MS,
                        "maximum": DURATION_MAX_MS,
                    },
                    "cast_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "focal_zone": {
                        "type": "string",
                        "enum": list(_FOCAL_ZONES),
                    },
                    # design_sequence-only: which Remotion template to render.
                    # See _DESIGN_TEMPLATES above.
                    "template": {
                        "type": "string",
                        "enum": list(_DESIGN_TEMPLATES),
                    },
                    # design_sequence-only: JSON-encoded params for the template.
                    # Same string-trick as effects.params (Gemini 3 Pro rejects
                    # bare `{"type":"object"}`). _normalize_storyboard parses
                    # it. Per-template key contracts are spelled out in the
                    # system prompt.
                    "template_params": {
                        "type": "string",
                        "description": (
                            "JSON-encoded object of params for this design "
                            "template. Required when kind='design_sequence', "
                            "ignored otherwise."
                        ),
                    },
                    "effects": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "kind": {"type": "string", "enum": list(_EFFECT_KINDS)},
                                "start_ms": {"type": "integer"},
                                "duration_ms": {"type": "integer"},
                                # Gemini 3 Pro's response_schema rejects bare
                                # `{"type": "object"}` (no properties) AND
                                # all-optional objects. We sidestep both by
                                # asking for a JSON-encoded string the LLM
                                # populates per-kind; _normalize_storyboard
                                # parses it. The system prompt documents the
                                # per-kind keys.
                                "params": {
                                    "type": "string",
                                    "description": (
                                        "JSON-encoded object of params for "
                                        "this effect kind. Use the literal "
                                        "string '{}' if no params apply."
                                    ),
                                },
                            },
                            "required": ["id", "kind"],
                        },
                    },
                },
                "required": [
                    "id",
                    "prompt",
                    "motion",
                    "caption",
                    "duration_ms",
                    "cast_refs",
                    "focal_zone",
                ],
            },
        },
    },
    "required": ["aspect", "narrative", "cast", "frames"],
}


def _load_latest_brand() -> dict | None:
    """Mirrors `agent.loop._load_latest_brand` — flat dict snapshot."""
    with SessionLocal() as db:
        brand = (
            db.query(models.Brand)
            .filter(models.Brand.onboarded_at.is_not(None))
            .order_by(models.Brand.onboarded_at.desc())
            .first()
        )
        if brand is None:
            return None
        return {
            "id": brand.id,
            "name": brand.name,
            "url": brand.url,
            "description": brand.description,
            "voice_profile": brand.voice_profile,
            "palette": brand.palette,
            "palette_roles": brand.palette_roles,
            "identity": brand.identity,
            "style_profile": brand.style_profile,
            "recent_posts": brand.recent_posts or [],
            "pasted_posts": brand.pasted_posts or "",
            "assets": brand.assets or [],
            "reference_brands": brand.reference_brands or [],
            "handles": brand.handles or {},
        }


def _load_latest_campaign(brand_id: str) -> dict | None:
    """Most-recent campaign bundle for the brand (or any campaign if none
    matches the given brand_id)."""
    with SessionLocal() as db:
        camp = (
            db.query(models.Campaign)
            .filter(models.Campaign.brand_id == brand_id)
            .order_by(models.Campaign.created_at.desc())
            .first()
        )
        if camp is None:
            # Fall back to any campaign if this brand has none — useful in
            # demo flows where the brand was just re-onboarded.
            camp = (
                db.query(models.Campaign)
                .order_by(models.Campaign.created_at.desc())
                .first()
            )
        if camp is None:
            return None
        return {
            "id": camp.id,
            "title": camp.title,
            "bundle": camp.bundle or {},
        }


def _voice_summary(brand: dict) -> str:
    voice = brand.get("voice_profile") or {}
    if not voice:
        return ""
    parts: list[str] = []
    tone = voice.get("tone")
    if tone:
        parts.append(f"Tone: {tone}.")
    phrases = voice.get("recurring_phrases") or []
    if phrases:
        parts.append(f"Recurring phrases: {', '.join(phrases[:8])}.")
    excerpt = voice.get("voice_excerpt")
    if excerpt:
        parts.append(f"Voice excerpt: {excerpt[:240]}")
    return " ".join(parts)


def _campaign_drafts_summary(bundle: dict) -> str:
    """Pull a digest of the multi-channel drafts so the LLM has the same
    ground truth the rest of the campaign was built from."""
    if not bundle:
        return ""
    drafts = bundle.get("drafts") or []
    chunks: list[str] = []
    for d in drafts:
        channel = (d.get("channel") or "").strip()
        body = (d.get("body") or "").strip()
        if not body or not channel:
            continue
        chunks.append(f"[{channel}] {body[:480]}")
        if len(chunks) >= 4:
            break
    if not chunks:
        # Fall back to legacy flat fields if drafts list is empty.
        blog = (bundle.get("blog") or {}).get("body")
        social = ((bundle.get("social") or {}).get("linkedin")) or ""
        if blog:
            chunks.append(f"[blog] {blog[:480]}")
        if social:
            chunks.append(f"[linkedin] {social[:480]}")
    return "\n---\n".join(chunks)


def _palette_block(brand: dict) -> str:
    palette = (brand.get("palette") or [])[:5]
    if not palette:
        return ""
    return f"Brand palette (use sparingly to color the visuals): {', '.join(palette)}."


def _style_block(brand: dict) -> str:
    style = brand.get("style_profile") or {}
    parts: list[str] = []
    mood = style.get("mood")
    if mood:
        parts.append(f"Mood: {mood}.")
    photo = style.get("photographic_vs_illustrated")
    if photo:
        parts.append(f"Treatment: {photo}.")
    composition = style.get("composition")
    if composition:
        parts.append(f"Composition: {composition}.")
    marks = style.get("distinctive_marks") or []
    if marks:
        parts.append(f"Visual signatures: {'; '.join(marks[:3])}.")
    return " ".join(parts)


def _described_assets_block(brand_id: str | None, assets: list) -> str:
    """Render the brand's uploaded assets as a planner-friendly bulleted
    list, decorated with each asset's AI-authored description (when one
    exists in the Asset table). Empty string when no assets have been
    described yet — caller falls back to the count-only legacy block.

    The KEY thing: ``index`` refers to the position in the ``brand.assets``
    list, NOT the Asset table row id. The planner emits
    ``binding.asset_index`` against this index, and ``auto_bind_brand_assets``
    resolves it back to the URL via ``brand.assets[N]``.
    """
    if not assets or not brand_id:
        return ""
    # Build a URL → Asset row map so we can look up descriptions for each
    # brand.assets entry without N round-trips.
    url_set: set[str] = set()
    asset_urls: list[str] = []
    for entry in assets:
        url = entry if isinstance(entry, str) else (
            (entry.get("url") or entry.get("asset_url") or "")
            if isinstance(entry, dict) else ""
        )
        if isinstance(url, str) and url:
            asset_urls.append(url)
            url_set.add(url)
        else:
            asset_urls.append("")  # keep index alignment

    if not url_set:
        return ""

    with SessionLocal() as db:
        rows = (
            db.query(models.Asset)
            .filter(
                models.Asset.brand_id == brand_id,
                models.Asset.url.in_(url_set),
            )
            .all()
        )
    by_url = {r.url: r for r in rows}

    lines: list[str] = []
    any_described = False
    for i, url in enumerate(asset_urls):
        if not url:
            continue
        row = by_url.get(url)
        ck = (row.cast_kind if row else "") or "?"
        label = (row.label if row else "") or ""
        desc = (row.description if row else "") or ""
        if desc:
            any_described = True
        # Compact one-liner: index | cast_kind | label | description.
        # Keep description punchy — the planner doesn't need the whole
        # paragraph, the lookup will pull the full row at scene-build time.
        bits = [str(i), ck, label, (desc[:240] or "(not yet described)")]
        lines.append("  " + " | ".join(b for b in bits if b))

    # Only return the block when AT LEAST ONE asset has a real description —
    # otherwise the planner sees nothing useful and we should fall back to
    # the legacy "you have N assets" hint.
    if not any_described:
        return ""
    return "\n".join(lines)


def _build_messages(
    brand: dict,
    campaign: dict | None,
    *,
    segment: dict | None = None,
) -> list[dict]:
    name = brand.get("name") or "the brand"
    description = (brand.get("description") or "").strip()

    user_request = ""
    drafts_block = ""
    campaign_title = ""
    if campaign is not None:
        bundle = campaign.get("bundle") or {}
        user_request = (bundle.get("user_request") or "").strip()
        drafts_block = _campaign_drafts_summary(bundle)
        campaign_title = (campaign.get("title") or "").strip()

    system = (
        "You are an auteur director planning a 12-15 second marketing film "
        "at the production level of an Apple, Wieden+Kennedy, or Spike Jonze "
        "spot. Each frame becomes a real video clip rendered by Veo (a "
        "generative video model); Remotion concatenates the clips with a "
        "short opacity crossfade and overlays captions in the brand's "
        "typography. Your job is to plan (1) the cinematic brief — the "
        "overall film direction every shot must inherit, (2) the narrative, "
        "(3) the recurring visual cast, and (4) the per-scene direction.\n\n"
        "NETFLIX-/CINEMA-GRADE BAR: this is not a stock-template TikTok. "
        "Every prompt must read like a DP's shot list — concrete lens, "
        "concrete light, concrete blocking, concrete color. Reject vague "
        "vibes ('cinematic', 'premium', 'modern feel') — name the film "
        "language: focal length, contrast ratio, key/fill direction, grade.\n\n"
        "CRITICAL — NO TEXT IN VISUALS: prompts and motion descriptions must "
        "describe ONLY the visual scene — never include text, words, "
        "headlines, captions, subtitles, slogans, or typography that should "
        "appear *inside* the video. Captions are a separate field, layered "
        "on top of the rendered clips by the compositor.\n\n"
        "DIRECTOR'S CINEMATIC BRIEF — the auteur's vision threaded through "
        "every shot. Author this BEFORE the narrative and the frames. Each "
        "field must be one to three concrete sentences:\n"
        "- reference_films: 2-3 named touchstones the spot should feel like "
        "  ('Apple iPhone holiday spot 2023, Spike Jonze Apple HomePod, "
        "  Wieden+Kennedy Nike auteur work'). Concrete references — not "
        "  genres.\n"
        "- lensing: focal length and depth-of-field language ('35-50mm "
        "  spherical primes, shallow DOF on subject, no fish-eye, no GoPro "
        "  distortion'). Anamorphic only if the brand voice supports it.\n"
        "- lighting: key direction, fill ratio, motivation ('soft window "
        "  key from camera-left, warm tungsten practicals as fill, hard rim "
        "  on hair from background'). Name the light source.\n"
        "- palette_grade: the color science ('warm shadows lifted, "
        "  desaturated highlights, 2:1 contrast, Kodak Portra-style "
        "  midtones'). Concrete grade language.\n"
        "- pacing: 'patient — long takes, motion is human-scale, no MTV "
        "  cuts'. Or whatever rhythm fits the brand.\n"
        "- do_not: an EXPLICIT anti-list of AI-video failure modes to "
        "  forbid in every shot. ALWAYS include: 'no offscreen hand or "
        "  appendage entering frame', 'no phone-style pinch zoom or "
        "  smartphone-camera interaction', 'no glove-puppet artifacts', "
        "  'no UI overlays or browser chrome', 'no AI-stock-photo gloss', "
        "  'no jittery handheld tremor that signals AI video', 'no invented "
        "  characters or props that aren't in the keyframe'. Add brand-"
        "  specific don'ts as needed.\n\n"
        "NARRATIVE: after the cinematic_brief, articulate the story:\n"
        "- premise: one sentence — what's this video about?\n"
        "- arc: how does the 12-15s unfold? hook → setup → reveal → proof "
        "  → CTA, or a variant that fits the brand voice.\n"
        "- tone: the emotional register (calm confidence, playful, "
        "  technical pride, etc).\n\n"
        "NO TRANSITION SHOTS: each frame is a self-contained shot of 2-4 "
        "seconds. Do NOT plan 'transition frames', 'dissolve shots', or "
        "'blending sequences' — Veo cannot render those reliably and "
        "Remotion already crossfades 12 frames between adjacent shots. "
        "Plan SHOTS, not the seams between them.\n\n"
        "VOICEOVER — a Gemini-TTS narration is muxed onto the final video. "
        "Author the voiceover at plan time so it pairs with the visual arc:\n"
        "- script: the narration the voice will read. Target 30-45 words "
        "  for a 12-15s spot (~2.8 words per second of comfortable read). "
        "  Brand voice. Conversational copy, not slogan stacking. Should "
        "  *complement* the on-screen captions, not duplicate them word-for-"
        "  word — captions punctuate, voiceover narrates. Plain text, no "
        "  stage directions, no SSML, no '[pause]' markers.\n"
        "- voice_persona: a short style directive Gemini TTS reads as a "
        "  prefix instruction ('warm and confident, low register, patient "
        "  pacing, slight smile in the voice'). One sentence. Match the "
        "  brand tone.\n"
        "- voice_name: one of Aoede, Charon, Fenrir, Kore, Leda, Orus, "
        "  Puck, Schedar, Vindemiatrix, Zephyr. Charon = deep authoritative "
        "  male; Kore = warm grounded female; Aoede = bright energetic "
        "  female; Puck = playful male; Zephyr = airy neutral. Pick one "
        "  whose default register matches voice_persona.\n\n"
        "INGREDIENTS / CAST — LOGICAL ENTITIES ONLY: identify 3-5 'cast "
        "members' that recur across frames. Cast members must be "
        "RECOGNIZABLE entities a viewer could point at and name:\n"
        "- characters (typically 1-2): coherent people. Full face, hair, "
        "  body, outfit — not body parts (no 'hands', no 'eyes'), not "
        "  abstract emotions, not silhouettes.\n"
        "- settings (1-2): full locations a viewer would describe in one "
        "  sentence (a cafe interior, a workshop, a kitchen). Not 'good "
        "  lighting' or 'morning vibe' — those are scene state, not cast.\n"
        "- props/products (0-2): hero objects with a definable shape "
        "  (the brand's flagship product, a specific bag, a labeled bottle). "
        "  Not 'a sense of momentum' or 'something delicious'.\n"
        "FORBIDDEN as cast: body parts, emotions, lighting moods, weather, "
        "times-of-day, abstract concepts, ambient atmospheres. Each cast "
        "member must include a `narrative_purpose` field — one sentence "
        "justifying why this entity recurs and what it carries through the "
        "story. If you can't write a clear narrative_purpose, the entity "
        "is not a cast member.\n\n"
        "Frames cite cast members using bracket markers in the prompt, e.g.: "
        "`[CHAR:char_protagonist] sits at the window of [SETTING:setting_cafe]`. "
        "Every frame must also list its cast_refs as an array of cast IDs.\n\n"
        "TEXT-FREE DESCRIPTIONS: when describing cast members and their "
        "settings, do NOT include text-laden elements: no menu boards, no "
        "neon signs reading anything, no slogan apparel, no labeled equipment, "
        "no branded packaging copy. Settings should be clean canvases — the "
        "compositor lays text on top.\n\n"
        "BRAND ASSET BINDING: if a cast member IS the brand's actual product, "
        "founder headshot, or logo, set binding.type='brand_asset' and "
        "binding.asset_index to the 0-based index in brand.assets. The system "
        "uses that uploaded asset directly. Otherwise, set "
        "binding.type='needs_generation' — the system pre-generates a neutral "
        "reference sheet from your description.\n\n"
        "FOCAL ZONE: each frame has a `focal_zone` naming where the primary "
        "subject sits in a 9-cell grid: tl, tc, tr (top row), ml, mc, mr "
        "(middle row), bl, bc, br (bottom row). The compositor uses this to "
        "place captions in the opposite quadrant.\n\n"
        "MOTION DIRECTION: each frame includes a `motion` field — the camera "
        "and subject motion you want Veo to render. Use the language of a "
        "professional DP: dolly-in, push-in, slow pan, locked-off, slider "
        "left, gimbal walk, rack focus. Examples:\n"
        "- 'slow dolly-in 35mm from medium to close-up; subject sits still'\n"
        "- 'locked-off tripod; subject reaches across frame for the product'\n"
        "- 'slider left at human pace; the setting breathes, no subject "
        "  motion'\n"
        "FORBIDDEN motion: phone-style 'pinch zoom', smartphone-camera "
        "interaction, an offscreen hand entering frame to touch the subject, "
        "AI-jitter handheld tremor, time-lapse, teleporting cuts, or any "
        "'someone holds a phone up to the subject' framing. Veo's default "
        "behavior on weak prompts is to insert a hand zooming on the "
        "subject — explicitly forbid that in your motion field for every "
        "shot. Per-clip motion is real-time within the clip's duration_ms.\n\n"
        "EFFECTS — motion-graphics overlays Remotion renders ON TOP of each "
        "Veo clip. These lift the output above generic AI-stock-video "
        "aesthetics. Use 0-2 effects per shot, SPARINGLY — they're visual "
        "punctuation, not constant embellishment. NEVER bake text into the "
        "clip; effects render text in Remotion. Available kinds:\n"
        "- kinetic_text: animated word accent (one or two words). NOT the "
        "  caption — caption is the main read, this is punctuation. Use for "
        "  hooks, reveals, punchlines. params: {text, zone (9-cell), size}.\n"
        "- lower_third: bottom info bar with title + optional subtitle. Use "
        "  for source citations, attributions, 'as seen in' credits. "
        "  params: {title, subtitle?}.\n"
        "- brand_stinger: ~0.3s brand-color flash with optional wordmark. "
        "  Use as a sharper rhythm punctuation between beats. params: {text?}.\n"
        "- spotlight: dim everything except a focal region. Use for product "
        "  close-ups, 'look here' beats. params: {zone, radius}.\n"
        "- kinetic_lines: animated geometric lines as stylistic texture. "
        "  params: {pattern: diagonal|horizontal|underline|frame}.\n"
        "- data_pop: animated number/percentage/metric reveal. Use when the "
        "  shot makes a quantitative claim. params: {value, zone, variant?}.\n"
        "Each effect needs a stable id ('e0', 'e1', ...). start_ms and "
        "duration_ms are optional (default: spans the full shot). `params` "
        "is a regular JSON object whose keys depend on `kind` (per the list "
        "above) — emit it inline, e.g. \"params\": {\"text\": \"Hello\", "
        "\"zone\": \"tc\"}. Use {} if the kind takes no params.\n\n"
        "FRAME KIND — every frame is one of two kinds:\n"
        "- 'live_action': a Veo-rendered cinema shot (the default). Use for "
        "  the bulk of beats — narrative action, hero moments, character/"
        "  product reveals.\n"
        "- 'design_sequence': a pure-graphic Remotion template, no Veo. Use "
        "  these to BREAK UP the live-action with high-contrast graphic "
        "  beats — like Apple keynote spec slides between B-roll, or Linear "
        "  release-reel kinetic typography between live shots. Aim for ~25-"
        "  35% of frames as design_sequence (1-2 of 6) for a punchy edit. "
        "  Skip them entirely for documentary-tone brands.\n"
        "  design_sequence (now): includes canvas_kinetic — a hybrid where "
        "  nano-banana generates a stylized concept-art backdrop and "
        "  Remotion layers kinetic typography on top. Pick this for hero "
        "  abstract beats where neither a real shot nor a flat graphic "
        "  fits.\n\n"
        "DESIGN SEQUENCE TEMPLATES — pick `template` per design frame and "
        "fill `template_params` as a JSON-ENCODED STRING (same trick as "
        "effects.params). Per-template shapes:\n"
        "- gradient_kinetic — Linear/Vercel release reel. Bold gradient bg "
        "  + headline reveals letter-by-letter. params: "
        "  '{\"headline\": \"3-7 words\", \"subtitle\": \"optional small line\"}'\n"
        "- spec_card — Apple keynote. HUGE numerical value with small label. "
        "  Counter-style number reveal. params: "
        "  '{\"value\": \"M7\" or \"3.5×\" or \"$1,200\", \"label\": \"short caption\", "
        "  \"unit\": \"optional /sec\", \"theme\": \"light\"|\"dark\"}'\n"
        "- ui_zoom — Stripe demo. Push from full screenshot into a focal "
        "  region. params: '{\"image_url\": \"https://...\" or null (uses brand "
        "  asset 0), \"focus_zone\": \"tl|tc|tr|ml|mc|mr|bl|bc|br\", "
        "  \"label\": \"optional pointer text\"}'\n"
        "- code_window — Vercel/GitHub. macOS code window with type-in. "
        "  params: '{\"lines\": [\"line 1\", \"line 2\", ...], \"language\": \"ts\"|"
        "  \"py\"|\"go\"|..., \"theme\": \"light\"|\"dark\"}'. 4-8 short lines.\n"
        "- logo_reveal — Wieden+Kennedy. Wordmark builds char-by-char with "
        "  brand-color flash. params: '{\"wordmark\": \"BRAND NAME\" (default: "
        "  brand.name), \"tagline\": \"optional one-liner\", "
        "  \"theme\": \"light\"|\"dark\"}'\n"
        "- comparison_split — Apple Switch. Before/after split, desat→full "
        "  color. params: '{\"before\": {\"label\": \"Old way\"}, "
        "  \"after\": {\"label\": \"New way\"}, \"orientation\": \"v\"|\"h\"}'. "
        "  Add image_url per side if showing real assets.\n"
        "- text_scroll — End-credits-style vertical scroll. Use for value "
        "  prop walls, manifesto lists, feature roll-calls. params: "
        "  '{\"lines\": [\"line 1\", \"line 2\", ...], "
        "  \"theme\": \"overlay\"|\"full\"}'. 5-12 short lines. theme='overlay' "
        "  is transparent (sits on top of a Veo frame, dramatic effect); "
        "  theme='full' is solid brand-color background.\n"
        "- headline_punch — Apple-keynote single-headline punch. Overshoot "
        "  scale-in, hold, zoom-past exit (reads like the line punches "
        "  through the lens). params: '{\"headline\": \"3-5 words\", "
        "  \"subheadline\": \"optional supporting line\"}'. Hero moments only.\n"
        "- word_kinetic — Wieden+Kennedy multi-word kinetic typography. "
        "  Each word animates independently. params: "
        "  '{\"words\": [{\"text\": \"Run\", \"style\": \"bold\", \"color\": "
        "  \"accent\", \"enter\": \"slide\"}, ...]}'. 3-6 words; per-word "
        "  style ∈ bold|italic|caps; color ∈ accent|text|background; "
        "  enter ∈ rotate|scale|slide|flip. Words appear on a 6-8 frame "
        "  stagger; exit synchronously.\n"
        "- canvas_kinetic — HYBRID concept-art beat. Nano-banana generates "
        "  a stylized illustrated backdrop (NOT real footage, NOT a flat "
        "  gradient), Remotion overlays kinetic typography on top. Use for "
        "  hero abstract beats where neither a Veo cinema shot nor a flat "
        "  graphic feels right — concept art, exploded-view product "
        "  visualization, cosmic / abstract scenes that complement kinetic "
        "  text. params: '{\"canvas_prompt\": \"1-2 sentences describing "
        "  the illustrated bg — stylized, non-photoreal, abstract or "
        "  concept-art, with negative space for text overlays. e.g. \\\"An "
        "  exploded isometric view of a silicon chip floating in deep "
        "  cobalt space, fractal circuit traces radiating outward, aurora "
        "  glow\\\"\", \"headline\": \"3-5 words\", \"motion\": "
        "  \"punch\"|\"scroll\"|\"word_kinetic\", \"subtitle\": \"optional "
        "  small line\"}'. Pick \"punch\" for single-headline reveals, "
        "  \"scroll\" for multi-line manifesto vibes, \"word_kinetic\" for "
        "  kinetic typography breakdowns.\n"
        "When kind='design_sequence': prompt should be a 1-sentence summary "
        "(\"Spec slide: M7 chip, 3.5× faster\") and motion can be empty — "
        "the template handles its own motion. cast_refs is empty; effects "
        "are still allowed (kinetic_text and brand_stinger pair well).\n\n"
        "TITLE CARD + END CARD: bookend the video with two pure-typography "
        "beats rendered by Remotion (no Veo clip):\n"
        "- title_card.text: 3-6 words. The brand hook that opens the video. "
        "  Sets the promise before the action starts. Brand voice — punchy, "
        "  not a slogan tagline, not a question.\n"
        "- end_card.headline: 3-7 words. The resolution after the last clip. "
        "  In brand voice. Pairs with the CTA.\n"
        "- end_card.cta: 1-3 words. What the viewer should do next "
        "  ('Try it free', 'Shop the drop', 'Read the case'). Brand voice.\n"
        "Both fields are typographic-only — no Veo clip is rendered for "
        "them. They are NOT counted in the 6 frames.\n\n"
        f"Return exactly {FRAME_COUNT} frames. Each frame:\n"
        "- prompt: 2-3 sentences describing the *visual scene* in concrete "
        "  film-language (subject + blocking, composition + framing, light "
        "  source + direction, palette/grade), with [CAST:id] markers for "
        "  every recurring ingredient. The shot must inherit the "
        "  cinematic_brief — same lensing, same lighting, same grade as "
        "  the rest of the film. No text/letters/words baked into the "
        "  scene.\n"
        "- motion: 1 sentence of camera + subject motion direction for Veo. "
        "  Use DP language (dolly, push-in, pan, slider, locked-off). Never "
        "  imply a phone-camera interaction or an offscreen hand.\n"
        f"- caption: at most {CAPTION_MAX_WORDS} words in the brand voice. "
        "  This is what users will read on screen — punchy, specific, in voice.\n"
        f"- duration_ms: integer between {DURATION_MIN_MS} and "
        f"  {DURATION_MAX_MS} (longer for hero/closing frames, "
        "  shorter for transitional ones).\n"
        "- id: 'f0', 'f1', ..., 'f5' in order.\n"
        "- cast_refs: array of cast IDs that appear in this frame.\n"
        "- focal_zone: one of tl|tc|tr|ml|mc|mr|bl|bc|br.\n"
        "- effects: array (0-3 entries). Each: {id, kind, params, "
        "  start_ms?, duration_ms?}. Use sparingly — most shots will have "
        "  0 or 1 effect; 2-3 only for hero moments.\n\n"
        "The 6 frames should narratively pace the arc you wrote in narrative. "
        "Aspect should default to '16:9' unless the campaign clearly screams "
        "vertical (mobile-first, Reels-style, TikTok feel) — then use '9:16'. "
        "Output JSON only."
    )

    user_lines: list[str] = [
        f"Brand: {name}",
    ]
    # Inject the brand picture book FIRST so the cinematic_brief and frame
    # prompts the planner authors inherit the evergreen visual identity.
    # Storyboard is the layer immediately below PIC.md in the hierarchy:
    # PIC.md (brand) → cinematic_brief (storyboard) → per-frame prompt.
    pic_md = load_pic(str(brand.get("id") or "").strip())
    if pic_md:
        user_lines.append(
            "BRAND PICTURE BOOK (PIC.md) — every frame, every cinematic_brief "
            "field, every voiceover line you author MUST be consistent with "
            "this evergreen identity. Do not contradict it; if a campaign "
            "would push outside the picture book, narrow the campaign, not "
            "the book.\n\n"
            f"{pic_md}"
        )
    if description:
        user_lines.append(f"Description: {description}")
    voice = _voice_summary(brand)
    if voice:
        user_lines.append(voice)
    palette_block = _palette_block(brand)
    if palette_block:
        user_lines.append(palette_block)
    style_block = _style_block(brand)
    if style_block:
        user_lines.append(style_block)

    if campaign_title:
        user_lines.append(f"\nCampaign: {campaign_title}")
    if user_request:
        user_lines.append(f"User request driving the campaign: {user_request}")
    if drafts_block:
        user_lines.append("Channel drafts (for narrative grounding):\n" + drafts_block)

    # ── Target audience (optional) ──────────────────────────────────────
    # When the caller passes a segment, the planner is told to tailor
    # everything — cinematic_brief, frames, voiceover script — to that
    # specific cohort. The most important signal is feature_focus: the
    # one product feature these users care about above all others. The
    # planner is instructed to make that feature the visual hero of
    # frames 2-4 and to write the voiceover script directly to a user
    # of that feature.
    if segment:
        seg_name = segment.get("name") or "the target segment"
        seg_size = int(segment.get("size") or 0)
        seg_desc = (segment.get("description") or "").strip()
        seg_rationale = (segment.get("rationale") or "").strip()
        feature_focus = (segment.get("feature_focus") or "").strip()
        # Order top features by contributor count (distinct customers
        # using each), falling back to event count.
        contributors = segment.get("contributor_counts") or {}
        events = segment.get("feature_stats") or {}
        ranked_features = sorted(
            events.keys(),
            key=lambda f: (contributors.get(f, 0), events.get(f, 0)),
            reverse=True,
        )[:5]
        feature_lines = [
            f"  - {f}: {contributors.get(f, 0)} customers, "
            f"{events.get(f, 0)} events"
            for f in ranked_features
        ]
        target_block = [
            "TARGET AUDIENCE — this video is being generated for one "
            "specific customer segment. Tailor EVERYTHING (cinematic_brief, "
            "narrative, frame prompts, voiceover script, captions, end-card "
            "CTA) to land with this audience specifically. Do NOT write a "
            "generic spot.",
            f"Segment name: {seg_name}",
            f"Segment size: {seg_size} customer(s)",
        ]
        if seg_desc:
            target_block.append(f"Segment description: {seg_desc}")
        if seg_rationale:
            target_block.append(f"Why they cluster: {seg_rationale}")
        if feature_focus:
            target_block.append(
                f"FEATURE FOCUS: '{feature_focus}'. This is the product "
                f"feature these customers use most — make it the visual "
                f"hero of frames 2-4 (or whichever frames are mid-arc), "
                f"and the voiceover script must speak directly to a user "
                f"of '{feature_focus}'. The end-card CTA should reinforce "
                f"that feature ('Try {feature_focus} free', 'Master "
                f"{feature_focus}', etc) unless the brand voice clearly "
                f"prefers a softer ask."
            )
        if feature_lines:
            target_block.append(
                "Top features used by this segment:\n"
                + "\n".join(feature_lines)
            )
        user_lines.append("\n".join(target_block))

    assets = brand.get("assets") or []
    if assets:
        # Decorate Brand.assets with AI-authored descriptions from the Asset
        # table (when present) so the planner picks the RIGHT asset per
        # cast member instead of guessing by index. Each line names the
        # asset_index, label, cast_kind hint, and the visual description.
        described_block = _described_assets_block(brand.get("id"), assets)
        if described_block:
            user_lines.append(
                "\nThe brand has the following uploaded asset(s). Each line "
                "is `index | cast_kind | label | description`. When a cast "
                "member you author MATCHES one of these (a person photo for "
                "a 'character', a real product for a 'product', etc), set "
                "binding.type='brand_asset' and binding.asset_index to that "
                "row's index. Otherwise use binding.type='needs_generation' "
                "so the system synthesizes a neutral reference sheet:\n"
                + described_block
            )
        else:
            user_lines.append(
                f"\nThe brand has {len(assets)} uploaded asset(s) at indexes "
                f"0..{len(assets) - 1}. Use these as binding.asset_index for cast "
                "members that ARE the brand's actual product / logo / founder "
                "photos (the photo is real and may legitimately contain brand "
                "text — that's fine). Synthesized cast (stand-in protagonist, "
                "generic settings, generic props) should use "
                "binding.type='needs_generation'."
            )

    user_lines.append(
        f"\nReturn JSON with shape: {{ aspect: '16:9'|'9:16'|'1:1', "
        f"cast: [...], frames: [{FRAME_COUNT} entries with id, prompt, "
        "caption, duration_ms, cast_refs, focal_zone] }."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def _normalize_storyboard(raw: dict, brand: dict | None = None) -> dict:
    """Defensively clamp + tidy the LLM's output into the response contract.

    Cast normalization:
      - drops members without a non-empty unique id
      - drops members without a non-empty narrative_purpose (logical-
        ingredient enforcement — fragmentary entities like 'hands' rarely
        survive this filter because the LLM can't justify them)
      - clamps kind to one of ("character", "setting", "prop", "product")
      - normalizes binding (defaults to needs_generation)
      - runs auto_bind_brand_assets to validate brand_asset.asset_index and
        write canonical_url for valid bindings

    Frame normalization (extends prior behavior):
      - drops cast_refs that don't reference a valid cast id
      - defaults focal_zone to 'mc' if missing/invalid
      - keeps motion as a passthrough string (Veo input)
    """
    aspect = (raw.get("aspect") or "16:9").strip()
    if aspect not in ("16:9", "9:16", "1:1"):
        aspect = "16:9"

    # ── Narrative ────────────────────────────────────────────────────────
    narrative_raw = raw.get("narrative") or {}
    if not isinstance(narrative_raw, dict):
        narrative_raw = {}
    narrative = {
        "premise": str(narrative_raw.get("premise") or "").strip()[:600],
        "arc": str(narrative_raw.get("arc") or "").strip()[:1200],
        "tone": str(narrative_raw.get("tone") or "").strip()[:240],
    }

    # ── Cinematic brief ──────────────────────────────────────────────────
    # The director's vision threaded into every Veo /scene call. Always
    # include the baseline anti-AI-slop rules in `do_not` even if the LLM
    # forgets — these are the failure modes Veo reliably exhibits.
    brief_raw = raw.get("cinematic_brief") or {}
    if not isinstance(brief_raw, dict):
        brief_raw = {}
    BASELINE_DONT = (
        "No offscreen hand or appendage entering frame. "
        "No phone-style pinch zoom or smartphone-camera interaction. "
        "No glove-puppet artifacts. No UI overlays or browser chrome. "
        "No AI-stock-photo gloss. No jittery handheld tremor. "
        "No invented characters or props that aren't in the keyframe."
    )
    do_not_text = str(brief_raw.get("do_not") or "").strip()
    if BASELINE_DONT.split(".")[0].lower() not in do_not_text.lower():
        do_not_text = (do_not_text + " " + BASELINE_DONT).strip() if do_not_text else BASELINE_DONT
    cinematic_brief = {
        "reference_films": str(brief_raw.get("reference_films") or "").strip()[:600],
        "lensing": str(brief_raw.get("lensing") or "").strip()[:400],
        "lighting": str(brief_raw.get("lighting") or "").strip()[:400],
        "palette_grade": str(brief_raw.get("palette_grade") or "").strip()[:400],
        "pacing": str(brief_raw.get("pacing") or "").strip()[:300],
        "do_not": do_not_text[:1200],
    }

    # ── Voiceover spec ───────────────────────────────────────────────────
    # 30-45 words is the comfortable read length for 12-15s. Cap at 90
    # words so an over-eager planner doesn't generate narration that runs
    # past the video duration.
    VALID_VOICES = {
        "Aoede", "Charon", "Fenrir", "Kore", "Leda",
        "Orus", "Puck", "Schedar", "Vindemiatrix", "Zephyr",
    }
    voiceover_raw = raw.get("voiceover") or {}
    if not isinstance(voiceover_raw, dict):
        voiceover_raw = {}
    vo_script = str(voiceover_raw.get("script") or "").strip()
    vo_words = vo_script.split()
    if len(vo_words) > 90:
        vo_script = " ".join(vo_words[:90])
    vo_persona = str(voiceover_raw.get("voice_persona") or "").strip()[:240]
    vo_voice = str(voiceover_raw.get("voice_name") or "").strip()
    if vo_voice not in VALID_VOICES:
        vo_voice = "Charon"  # safe brand-narrator default
    voiceover = {
        "script": vo_script[:1200],
        "voice_persona": vo_persona,
        "voice_name": vo_voice,
    }

    # ── Title card / end card ────────────────────────────────────────────
    # Optional bookends. Word caps mirror caption rules so they fit on
    # screen at the brand's caption typography.
    title_card_raw = raw.get("title_card") or {}
    title_card: dict | None = None
    if isinstance(title_card_raw, dict):
        text = str(title_card_raw.get("text") or "").strip()
        if text:
            words = text.split()
            if len(words) > 8:
                text = " ".join(words[:8])
            title_card = {"text": text[:80]}

    end_card_raw = raw.get("end_card") or {}
    end_card: dict | None = None
    if isinstance(end_card_raw, dict):
        headline = str(end_card_raw.get("headline") or "").strip()
        cta = str(end_card_raw.get("cta") or "").strip()
        if headline or cta:
            h_words = headline.split()
            if len(h_words) > 9:
                headline = " ".join(h_words[:9])
            c_words = cta.split()
            if len(c_words) > 4:
                cta = " ".join(c_words[:4])
            end_card = {"headline": headline[:90], "cta": cta[:40]}

    # ── Cast normalization ────────────────────────────────────────────────
    cast_raw = raw.get("cast") or []
    if not isinstance(cast_raw, list):
        cast_raw = []

    seen_ids: set[str] = set()
    cast: list[CastMember] = []
    for c in cast_raw:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        if not cid or cid in seen_ids:
            continue

        # Logical-ingredient gate: narrative_purpose must be present and
        # non-trivial. Fragmentary entities (body parts, vibes, etc.) tend
        # to fail this because the LLM can't articulate why they recur.
        narrative_purpose = str(c.get("narrative_purpose") or "").strip()
        if len(narrative_purpose) < 8:
            log.info(
                "normalize: dropping cast %r — missing narrative_purpose", cid
            )
            continue

        seen_ids.add(cid)
        kind_raw = str(c.get("kind") or "character").strip().lower()
        kind = kind_raw if kind_raw in _CAST_KINDS else "character"

        binding_raw = c.get("binding") or {}
        if not isinstance(binding_raw, dict):
            binding_raw = {}
        b_type = str(binding_raw.get("type") or "").strip()
        binding: dict = {"type": "needs_generation"}
        if b_type == "brand_asset":
            binding = {"type": "brand_asset"}
            ai = binding_raw.get("asset_index")
            if isinstance(ai, int):
                binding["asset_index"] = ai

        member: CastMember = {
            "id": cid,
            "kind": kind,  # type: ignore[typeddict-item]
            "role": str(c.get("role") or "").strip()[:120],
            "description": str(c.get("description") or "").strip()[:2000],
            "narrative_purpose": narrative_purpose[:600],  # type: ignore[typeddict-item]
            "neutral_pose_hint": str(c.get("neutral_pose_hint") or "").strip()[:600],
            "binding": binding,  # type: ignore[typeddict-item]
            "canonical_url": None,
        }
        cast.append(member)

    if brand is not None:
        cast = auto_bind_brand_assets(brand, cast)

    valid_cast_ids = {c["id"] for c in cast}

    # ── Frame normalization ──────────────────────────────────────────────
    frames_raw = raw.get("frames") or []
    if not isinstance(frames_raw, list):
        frames_raw = []

    frames: list[dict] = []
    for idx, f in enumerate(frames_raw[:FRAME_COUNT]):
        if not isinstance(f, dict):
            continue
        prompt = str(f.get("prompt") or "").strip()
        motion = str(f.get("motion") or "").strip()
        caption = str(f.get("caption") or "").strip()
        # Caption word cap — soft trim if model overshoots.
        words = caption.split()
        if len(words) > CAPTION_MAX_WORDS:
            caption = " ".join(words[:CAPTION_MAX_WORDS])
        try:
            duration = int(f.get("duration_ms") or 2400)
        except (TypeError, ValueError):
            duration = 2400
        duration = max(DURATION_MIN_MS, min(DURATION_MAX_MS, duration))
        frame_id = str(f.get("id") or f"f{idx}").strip() or f"f{idx}"

        refs_raw = f.get("cast_refs") or []
        if not isinstance(refs_raw, list):
            refs_raw = []
        cast_refs = [
            str(r)
            for r in refs_raw
            if isinstance(r, str) and r in valid_cast_ids
        ]

        focal_zone = str(f.get("focal_zone") or "mc").strip().lower()
        if focal_zone not in _FOCAL_ZONES:
            focal_zone = "mc"

        # Effects normalization — drop unknown kinds, clamp to 3 per shot.
        effects_raw = f.get("effects") or []
        if not isinstance(effects_raw, list):
            effects_raw = []
        effects: list[dict] = []
        seen_eids: set[str] = set()
        for eidx, eff in enumerate(effects_raw[:3]):
            if not isinstance(eff, dict):
                continue
            kind = str(eff.get("kind") or "").strip().lower()
            if kind not in _EFFECT_KINDS:
                continue
            eid = str(eff.get("id") or f"{frame_id}_e{eidx}").strip()
            if not eid or eid in seen_eids:
                eid = f"{frame_id}_e{eidx}"
            seen_eids.add(eid)
            # Schema asks for a JSON-encoded string (Gemini 3 Pro can't take
            # a bare object type). Accept dicts too for backwards-compat with
            # earlier runs / a forgiving LLM.
            params_raw = eff.get("params")
            params: dict = {}
            if isinstance(params_raw, dict):
                params = params_raw
            elif isinstance(params_raw, str) and params_raw.strip():
                try:
                    parsed = json.loads(params_raw)
                    if isinstance(parsed, dict):
                        params = parsed
                except (ValueError, TypeError):
                    params = {}
            entry: dict = {"id": eid, "kind": kind, "params": params}
            try:
                if eff.get("start_ms") is not None:
                    entry["start_ms"] = max(0, int(eff["start_ms"]))
                if eff.get("duration_ms") is not None:
                    entry["duration_ms"] = max(60, int(eff["duration_ms"]))
            except (TypeError, ValueError):
                pass
            effects.append(entry)

        # Frame kind discriminator. Default = live_action so legacy
        # storyboards (no `kind` field) continue to route through the Veo
        # branch with no behavior change. design_sequence frames carry an
        # extra `template` + `template_params` payload that the Remotion
        # SequenceRouter consumes.
        kind_raw = str(f.get("kind") or "live_action").strip().lower()
        kind = kind_raw if kind_raw in _FRAME_KINDS else "live_action"

        template: str | None = None
        template_params: dict | None = None
        if kind == "design_sequence":
            t_raw = str(f.get("template") or "").strip().lower()
            if t_raw not in _DESIGN_TEMPLATES:
                # Unknown template → downgrade to live_action so the frame
                # still renders. Logged so we can spot LLM drift over time.
                log.info(
                    "normalize: frame %s has unknown template %r — "
                    "downgrading to live_action",
                    frame_id, t_raw,
                )
                kind = "live_action"
            else:
                template = t_raw
                # Same JSON-string trick as effects.params (Gemini 3 Pro
                # rejects bare object schemas). Accept dicts too for forgiving
                # LLM output.
                tp_raw = f.get("template_params")
                if isinstance(tp_raw, dict):
                    template_params = tp_raw
                elif isinstance(tp_raw, str) and tp_raw.strip():
                    try:
                        parsed = json.loads(tp_raw)
                        if isinstance(parsed, dict):
                            template_params = parsed
                    except (ValueError, TypeError):
                        template_params = None
                if template_params is None:
                    template_params = {}
                # canvas_kinetic guard: requires a non-empty canvas_prompt at
                # plan time (the URL is filled at /render time). Validate
                # motion against the allowed enum, default to 'punch'. If the
                # canvas_prompt is missing, downgrade to gradient_kinetic so
                # the frame still renders with the headline/subtitle.
                if template == "canvas_kinetic":
                    cp = str(template_params.get("canvas_prompt") or "").strip()
                    if not cp:
                        log.warning(
                            "normalize: canvas_kinetic frame %s missing "
                            "canvas_prompt — downgrading to gradient_kinetic",
                            frame_id,
                        )
                        template = "gradient_kinetic"
                        # Strip the canvas-only params; keep headline/subtitle.
                        template_params = {
                            k: v
                            for k, v in template_params.items()
                            if k in ("headline", "subtitle")
                        }
                    else:
                        motion = str(template_params.get("motion") or "").strip().lower()
                        if motion not in _CANVAS_KINETIC_MOTIONS:
                            template_params["motion"] = "punch"
                        else:
                            template_params["motion"] = motion
                # Normalizer guarantees the template field is present inside
                # params too — Remotion's discriminated union expects it.
                template_params.setdefault("template", template)

        frame_entry: dict = {
            "id": frame_id,
            "kind": kind,
            "prompt": prompt[:2000],
            "motion": motion[:600],
            "caption": caption[:120],
            "duration_ms": duration,
            "cast_refs": cast_refs,
            "focal_zone": focal_zone,
            "effects": effects,
        }
        if kind == "design_sequence":
            frame_entry["template"] = template
            frame_entry["template_params"] = template_params

        frames.append(frame_entry)

    # If the LLM under-delivered, pad with neutral live_action frames so the
    # contract is always exactly FRAME_COUNT entries.
    while len(frames) < FRAME_COUNT:
        idx = len(frames)
        frames.append(
            {
                "id": f"f{idx}",
                "kind": "live_action",
                "prompt": "Editorial brand shot — soft-lit, restrained palette, single focal subject, generous negative space.",
                "motion": "static, ambient — subtle camera drift only.",
                "caption": "",
                "duration_ms": 2400,
                "cast_refs": [],
                "focal_zone": "mc",
                "effects": [],
            }
        )

    return {
        "aspect": aspect,
        "narrative": narrative,
        "cinematic_brief": cinematic_brief,
        "voiceover": voiceover,
        "title_card": title_card,
        "end_card": end_card,
        "cast": cast,
        "frames": frames,
    }


def _load_segment_context(brand_id: str, segment_id: str | None) -> dict | None:
    """Load the planner-relevant view of a segment + its feature stats.

    Returns None when no segment is targeted, the segment doesn't exist, or
    it doesn't belong to this brand. The planner prompt is built without a
    segment block in any of those cases — same shape as before, no breakage.
    """
    if not segment_id:
        return None
    with SessionLocal() as db:
        seg = db.get(models.Segment, segment_id)
        if seg is None or seg.brand_id != brand_id:
            return None
        # Re-aggregate the feature stats live so a freshly-attached segment
        # member is reflected immediately. Cheaper than waiting for the
        # next /segments/propose pass.
        from app.services.audience.feature_usage import (
            compute_segment_feature_stats,
        )

        stats = compute_segment_feature_stats(db, seg.id)
        return {
            "id": seg.id,
            "name": seg.name or "",
            "description": seg.description or "",
            "rationale": seg.rationale or "",
            "size": len(seg.customer_ids or []),
            # feature_focus on the row wins when present (it's what the
            # human / segmentation LLM committed to); the live re-agg is
            # the fallback so older segments still get a focus.
            "feature_focus": seg.feature_focus or stats["focus"],
            "feature_stats": stats["stats"],
            "contributor_counts": stats["contributor_counts"],
        }


async def suggest_storyboard(segment_id: str | None = None) -> dict:
    """Pull latest brand + latest campaign and return a storyboard with cast.

    Returns a dict with shape:
      { aspect, cast: [{id, kind, role, description, neutral_pose_hint,
                        binding: {type, asset_index?}, canonical_url}],
        frames: [{id, prompt, caption, duration_ms, cast_refs, focal_zone}],
        segment: {...} | None  # echoed back when targeting was requested }

    Cast members already have brand_asset bindings auto-resolved against
    `brand.assets` (canonical_url filled in for valid bindings; invalid
    bindings fall back to needs_generation).

    When ``segment_id`` is provided AND the segment belongs to the latest
    brand, the planner sees a "TARGET AUDIENCE" block naming the segment's
    feature_focus + size and is told to hero that feature in the visuals
    + voiceover. Different segments → different ad spots from the same
    brand and campaign.

    Raises:
        LookupError: no onboarded brand exists yet.
    """
    brand = _load_latest_brand()
    if brand is None:
        raise LookupError("no onboarded brand found")

    campaign = _load_latest_campaign(brand["id"])
    segment = _load_segment_context(brand["id"], segment_id)
    messages = _build_messages(brand, campaign, segment=segment)
    # Use the heavier planning model — narrative + cast bible benefits from
    # the deeper reasoning. Frame/scene prompts themselves are downstream.
    # NOTE: Gemini 3 Pro Preview's response_schema validator rejects this
    # storyboard schema (consistent 400 INVALID_ARGUMENT in production —
    # bisected April 2026). Each sub-schema passes alone; the combination of
    # cast + frames + 2+ small typed objects exceeds whatever complexity
    # threshold the new validator enforces, even at ~3KB total. We opt out of
    # response_schema and lean on the system prompt + _normalize_storyboard
    # for shape enforcement. The schema constant above is retained as
    # human-readable documentation of the contract.
    raw = await chat_json(
        messages,
        schema=_STORYBOARD_SCHEMA,
        model=settings.gemini_planning_model,
        force_no_schema=True,
    )
    out = _normalize_storyboard(raw, brand=brand)
    # Echo back the segment context the planner saw (or null) so the
    # caller can persist it on the Storyboard row + show it in the UI.
    out["segment"] = segment
    return out
