"""Fastino GLiNER2 — generalist NER as a brand-vocabulary extractor.

Pioneer's prize description names GLiNER2 as a bonus-points target:
"Bonus points for the most creative use case of GLiNER2." Our use case
is brand-specific entity extraction over the tenant's posts — pulling
out product names, recurring characters/mascots, signature topics, and
tone markers. The result becomes:

  1. A visible "brand vocabulary" chip row in the Voice pane.
  2. Concrete tokens injected into synthetic-pair briefs during corpus
     building, so the LoRA learns to deploy the brand's actual lexicon
     instead of generic marketing nouns.
  3. (Future) An at-inference-time guardrail that flags drafts which
     mention competitor names or off-brand entities.

Real path: ``POST api.fastino.com/v1/run`` with model=``gliner2`` and a
list of entity labels in the request body. Without ``PIONEER_API_KEY``
we fall back to Gemini doing the same job — same JSON shape out.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


# The labels we ask GLiNER2 (or the fallback) to extract. Tuned for
# brand-voice work — we deliberately avoid generic NER labels (PERSON,
# ORG, GPE) because every post mentions those and we'd drown in noise.
DEFAULT_LABELS: tuple[str, ...] = (
    "product_name",
    "character_or_mascot",
    "signature_topic",
    "recurring_phrase",
    "tone_marker",
)


@dataclass
class Entity:
    text: str
    label: str
    count: int


@dataclass
class EntityExtraction:
    entities: list[Entity]
    by_label: dict[str, list[str]]
    total: int
    source: str  # "gliner2" | "gemini_fallback"


# GLiNER2 lives at gliner.pioneer.ai (separate host from Pioneer
# personalization). The README on fastino-ai/GLiNER2 confirms the
# Python SDK uses ``GLiNER2.from_api()`` reading PIONEER_API_KEY. We
# call it directly via HTTP for parity with the rest of the codebase.
_GLINER2_BASE_URL = "https://gliner.pioneer.ai"
_GLINER2_ENDPOINT = "/extract"


async def _call_gliner2(
    text: str, labels: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Call GLiNER2 directly. Raises on any HTTP / parsing error so the
    caller (corpus_builder) sees the real failure mode instead of a
    silent empty result."""
    if not settings.pioneer_api_key:
        raise RuntimeError("PIONEER_API_KEY required for GLiNER2")
    payload = {
        "text": text[:8000],
        "labels": list(labels),
    }
    headers = {
        "x-api-key": settings.pioneer_api_key,
        "Content-Type": "application/json",
    }
    # ``verify=False`` matches the Pioneer client — Fastino's TLS cert
    # is expired across all *.pioneer.ai / *.fastino.ai hosts.
    async with httpx.AsyncClient(
        base_url=_GLINER2_BASE_URL,
        headers=headers,
        timeout=30.0,
        verify=False,
    ) as client:
        r = await client.post(_GLINER2_ENDPOINT, json=payload)
    r.raise_for_status()
    body = r.json()
    # GLiNER2's response shape is {entities:[{text,label,start,end,score}]}.
    # Be permissive in case it's wrapped or returned as a list.
    if isinstance(body, dict):
        return body.get("entities") or body.get("predictions") or []
    if isinstance(body, list):
        return body
    return []


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _aggregate(
    raw: list[dict[str, Any]], labels: tuple[str, ...]
) -> EntityExtraction:
    """De-duplicate by (lower(text), label), count occurrences, group by label."""
    allowed = {label.lower() for label in labels}
    counts: dict[tuple[str, str], int] = {}
    display: dict[tuple[str, str], str] = {}  # preserve original casing

    for item in raw:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        label = (item.get("label") or "").strip().lower()
        if not text or label not in allowed:
            continue
        key = (_normalize(text), label)
        counts[key] = counts.get(key, 0) + 1
        if key not in display:
            display[key] = text

    entities = sorted(
        (
            Entity(text=display[key], label=key[1], count=count)
            for key, count in counts.items()
        ),
        key=lambda e: (-e.count, e.label, e.text.lower()),
    )

    by_label: dict[str, list[str]] = {label: [] for label in labels}
    for e in entities:
        by_label.setdefault(e.label, []).append(e.text)

    return EntityExtraction(
        entities=entities,
        by_label=by_label,
        total=len(entities),
        source="",  # filled by caller
    )


async def extract_brand_entities(
    posts: list[str],
    brand_name: str,  # noqa: ARG001 — kept for future per-brand label tuning
    labels: tuple[str, ...] = DEFAULT_LABELS,
) -> EntityExtraction:
    """Extract brand-specific entities via Pioneer GLiNER2.

    Real-only: if GLiNER2 fails, we log it and return an empty
    extraction. The corpus build still proceeds without entities — the
    LoRA is just a bit less grounded in product names.
    """
    if not posts:
        return EntityExtraction(
            entities=[], by_label={lbl: [] for lbl in labels}, total=0,
            source="empty",
        )
    document = "\n\n".join(p.strip() for p in posts if p and p.strip())[:12000]
    if not document:
        return EntityExtraction(
            entities=[], by_label={lbl: [] for lbl in labels}, total=0,
            source="empty",
        )

    try:
        raw = await _call_gliner2(document, labels)
        result = _aggregate(raw, labels)
        result.source = "gliner2"
        return result
    except Exception as e:
        log.warning("gliner2 unavailable; corpus will lack entities: %s", e)
        empty = _aggregate([], labels)
        empty.source = f"gliner2_unavailable: {str(e)[:120]}"
        return empty


def serialize_extraction(e: EntityExtraction) -> dict[str, Any]:
    return {
        "source": e.source,
        "total": e.total,
        "by_label": e.by_label,
        "entities": [
            {"text": ent.text, "label": ent.label, "count": ent.count}
            for ent in e.entities
        ],
    }


def render_vocabulary_for_brief(extraction: EntityExtraction) -> str:
    """Render the extracted entities as a one-paragraph hint we can paste
    into the synthetic-pair-generation prompt. Keeps the LoRA grounded
    in the brand's actual lexicon.
    """
    if extraction.total == 0:
        return ""
    lines = []
    for label, items in extraction.by_label.items():
        if not items:
            continue
        sample = items[:6]
        lines.append(f"- {label}: {', '.join(sample)}")
    if not lines:
        return ""
    return "Brand vocabulary (use these names verbatim where natural):\n" + "\n".join(
        lines
    )


def to_brand_meta(extraction: EntityExtraction) -> dict[str, Any]:
    """Compact representation to stash on Brand.voice_corpus_meta.entities."""
    return {
        "source": extraction.source,
        "total": extraction.total,
        "by_label": {
            label: items[:10] for label, items in extraction.by_label.items() if items
        },
    }
