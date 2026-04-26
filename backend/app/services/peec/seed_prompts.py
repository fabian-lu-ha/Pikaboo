"""Seed a Peec project with prompts in one shot.

Two-stage seeding so we always get *something* into the project even
when the LLM is offline:

  1. **Accept Peec's own AI suggestions** — free, contextual to the
     project's own brand, arrive pre-tagged. We pull these first so
     we don't waste Gemini calls when Peec has already drafted good
     candidates.
  2. **Top up with Gemini-generated prompts** grounded in the brand's
     name, description, and competitor list — only if stage 1 didn't
     fill the requested target.

Without prompts in the project, ``/reports/brands`` stays empty and
every GEO action downstream is a no-op. This module is the missing
bootstrap.

Used by:
  - The ``ONBOARDING_COMPLETED`` listener — auto-seeds new brands so
    the user never has to log into the Peec dashboard manually.
  - ``POST /api/geo/seed-prompts`` — manual override exposed in the
    GeoPanel header.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


class PeecSeedError(Exception):
    pass


@dataclass
class SeededPrompt:
    id: str
    text: str
    source: str  # "suggestion" | "generated"


_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "intent": {"type": "string"},
                },
                "required": ["text"],
            },
        }
    },
    "required": ["prompts"],
}


async def seed_prompts(
    *,
    target_count: int = 12,
    brand_name: str | None = None,
    brand_description: str | None = None,
    competitors: list[str] | None = None,
    country_code: str = "US",
) -> list[SeededPrompt]:
    """Bring the Peec project up to ``target_count`` live prompts.

    Returns the list of prompts created (or accepted from suggestions)
    in this call. Idempotent — if the project already has ≥ target_count
    prompts, returns an empty list and does nothing. Raises PeecSeedError
    when the API key isn't set; logs and skips on per-prompt failures.
    """
    if not settings.peec_api_key:
        raise PeecSeedError("PEEC_API_KEY not set")

    base = settings.peec_base_url.rstrip("/") + "/customer/v1"
    headers = {
        "x-api-key": settings.peec_api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }

    seeded: list[SeededPrompt] = []
    async with httpx.AsyncClient(timeout=30) as client:
        existing = await _list_prompts(client, base, headers)
        slots_open = max(0, target_count - len(existing))
        if slots_open == 0:
            log.info(
                "peec.seed_prompts: project already has %s prompts (target=%s); nothing to do",
                len(existing),
                target_count,
            )
            return seeded

        # Stage 1 — accept up to slots_open existing suggestions.
        accepted = await _accept_suggestions(
            client, base, headers, max_accept=slots_open
        )
        seeded.extend(accepted)

        # Stage 2 — top up with Gemini-generated prompts if still short.
        slots_open = max(
            0, target_count - len(existing) - len(seeded)
        )
        if slots_open > 0:
            generated = await _generate_and_create(
                client,
                base,
                headers,
                count=slots_open,
                brand_name=brand_name or "",
                brand_description=brand_description or "",
                competitors=competitors or [],
                country_code=country_code,
            )
            seeded.extend(generated)

    log.info(
        "peec.seed_prompts: seeded %s prompts (suggestion=%s, generated=%s)",
        len(seeded),
        sum(1 for s in seeded if s.source == "suggestion"),
        sum(1 for s in seeded if s.source == "generated"),
    )
    return seeded


async def _list_prompts(
    client: httpx.AsyncClient, base: str, headers: dict
) -> list[dict]:
    r = await client.get(f"{base}/prompts?limit=200", headers=headers)
    r.raise_for_status()
    return (r.json() or {}).get("data", []) or []


async def _accept_suggestions(
    client: httpx.AsyncClient,
    base: str,
    headers: dict,
    *,
    max_accept: int,
) -> list[SeededPrompt]:
    if max_accept <= 0:
        return []
    try:
        r = await client.get(
            f"{base}/prompts/suggestions?limit={max_accept * 2}",
            headers=headers,
        )
        r.raise_for_status()
    except Exception as e:
        log.warning("peec.seed: list suggestions failed: %s", e)
        return []

    suggestions = (r.json() or {}).get("data", []) or []
    out: list[SeededPrompt] = []
    for s in suggestions[:max_accept]:
        sid = s.get("id")
        text = ""
        msgs = s.get("messages") or []
        if msgs and isinstance(msgs[0], dict):
            text = msgs[0].get("content", "")
        if not sid:
            continue
        try:
            r = await client.post(
                f"{base}/prompts/suggestions/{sid}/accept", headers=headers
            )
            if r.status_code in (200, 201):
                pid = (r.json() or {}).get("id") or sid
                out.append(SeededPrompt(id=pid, text=text, source="suggestion"))
            else:
                log.warning(
                    "peec.seed: accept suggestion %s failed %s: %s",
                    sid, r.status_code, r.text[:140],
                )
        except Exception as e:
            log.warning("peec.seed: accept suggestion %s crashed: %s", sid, e)
    return out


async def _generate_and_create(
    client: httpx.AsyncClient,
    base: str,
    headers: dict,
    *,
    count: int,
    brand_name: str,
    brand_description: str,
    competitors: list[str],
    country_code: str,
) -> list[SeededPrompt]:
    """Use Gemini to author N realistic search prompts customers would
    ask the answer engines about this brand's category, then POST each
    to Peec."""
    prompts_text = await _generate_prompt_texts(
        count=count,
        brand_name=brand_name,
        brand_description=brand_description,
        competitors=competitors,
    )
    out: list[SeededPrompt] = []
    for text in prompts_text[:count]:
        body = {"text": text[:200], "country_code": country_code}
        try:
            r = await client.post(
                f"{base}/prompts", headers=headers, json=body
            )
            if r.status_code in (200, 201):
                pid = (r.json() or {}).get("id") or ""
                out.append(SeededPrompt(id=pid, text=text, source="generated"))
            else:
                log.warning(
                    "peec.seed: create prompt failed %s: %s",
                    r.status_code, r.text[:140],
                )
        except Exception as e:
            log.warning("peec.seed: create prompt crashed: %s", e)
    return out


async def _generate_prompt_texts(
    *,
    count: int,
    brand_name: str,
    brand_description: str,
    competitors: list[str],
) -> list[str]:
    if not brand_name and not brand_description:
        return _fallback_prompts("tools", count)

    system = (
        "You are generating search prompts that real customers would ask "
        "answer engines (ChatGPT, Perplexity, Gemini, Claude, Google AI "
        "Overviews) about a brand's CATEGORY. These prompts will be "
        "monitored by a GEO tool to track how the brand surfaces.\n\n"
        "Constraints:\n"
        f"1) Generate exactly {count} prompts.\n"
        "2) Each prompt is 1-15 words, max 200 chars, English.\n"
        "3) Mix intent types: definitional ('what is...'), comparison "
        "('X vs Y'), best-of ('best ... for ...'), use-case ('how do I ...'), "
        "and price/segment-bound ('best ... under $X', 'best ... for "
        "small teams').\n"
        "4) DO NOT mention the BRAND name in the prompts — these track "
        "category-level visibility, so the brand needs to *win* the prompt "
        "by being the answer, not by being asked about by name.\n"
        "5) Reference competitor names sparingly — at most 2 prompts may "
        "use a competitor name in a 'X vs Y' comparison.\n"
        "Return JSON matching the schema."
    )
    facts = (
        f"BRAND: {brand_name}\n"
        f"DESCRIPTION: {brand_description or '(no description)'}\n"
        f"COMPETITORS: {', '.join(competitors) if competitors else '(none)'}"
    )
    try:
        out = await chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": facts},
            ],
            schema=_GENERATION_SCHEMA,
        )
        raw = out.get("prompts") or []
        texts: list[str] = []
        for r in raw:
            if isinstance(r, dict):
                t = (r.get("text") or "").strip()
                if t:
                    texts.append(t)
            elif isinstance(r, str) and r.strip():
                texts.append(r.strip())
        return texts
    except Exception as e:
        log.warning("peec.seed: gemini prompt generation failed: %s", e)
        return _fallback_prompts(brand_description, count)


def _fallback_prompts(description: str, count: int) -> list[str]:
    """Static template — used only when the LLM is unavailable."""
    base = (description or "").lower().strip() or "tools"
    templates = [
        f"best {base}",
        f"top {base} 2026",
        f"{base} alternatives",
        f"how to choose {base}",
        f"{base} for small teams",
        f"{base} for enterprise",
        f"what is the most reliable {base}",
        f"{base} pricing comparison",
        f"is there a free {base}",
        f"open source {base}",
        f"best {base} on the market",
        f"{base} vs the competition",
    ]
    return templates[:count]
