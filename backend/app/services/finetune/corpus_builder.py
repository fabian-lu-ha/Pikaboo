"""Turn a tenant's collected data into a Pioneer-ready JSONL corpus.

The output sits at ``storage/finetune/{brand_id}/corpus.jsonl`` and is
the single artefact the Pioneer client uploads. See PIONEER_FINETUNING.md
§3 and §4 for the format spec and the back-construction trick that keeps
us out of memorise-the-caption territory.

Three sources, in order of signal strength:

* **pasted_posts** — text the user pasted in onboarding. Highest signal,
  always real, often the brand's own best work.
* **recent_posts** — fetched from the brand's social handles. Good
  signal, larger volume, may include lower-effort posts.
* **video_analysis.transcript** — voiceovers from short-form video
  posts. Surprisingly good for spoken-tone training. Chunked into
  caption-sized briefs so the model doesn't try to learn to write
  3-minute monologues.

Plus synthetic expansion from the voice profile to reach the
LIMA-validated 50-200 sweet spot.

Reference brands are intentionally **not** included. Mixing competitor
text trains a hybrid voice. They're handled at inference time as
RAG-style examples instead — see PIONEER_FINETUNING.md §4.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.finetune import deep_scrape, gliner_client, prompts as fprompts
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)

# Aggressive caps. Each reverse-brief is one Gemini call (~3 s, ~$0.005)
# so the bound is wall-clock + cost — but the corpus is the moat, and a
# 300-pair LoRA dataset trained on real brand text dramatically beats a
# 50-pair mostly-synthetic one. Total cost per tenant: ~$1-2 in Gemini.
_REAL_POST_CAP = 120          # social posts (was 30)
_VIDEO_TRANSCRIPT_CAP = 30    # video transcript chunks (was 8)
_DEEP_SCRAPE_CAP = 120        # web-page text chunks (new)
_SYNTHETIC_TARGET = 300       # total target — synth fills the gap (was 50)
_SYNTHETIC_BATCH = 25         # bigger batches → fewer round-trips
_REVERSE_BRIEF_PARALLELISM = 24  # bumped from 8; Gemini Flash handles it


@dataclass
class CorpusResult:
    brand_id: str
    jsonl_path: str
    line_count: int
    breakdown: dict[str, int]


def _split_pasted(pasted: str | None) -> list[str]:
    """Split pasted_posts into individual post bodies.

    Users paste in messy formats — one-per-line, blank-line-separated, or
    one big chunk with bullets. We split on blank lines first; if that
    yields one big chunk we fall back to single-line splits as long as
    each line is at least 60 chars (filtering out URLs and tags).
    """
    if not pasted:
        return []
    cleaned = pasted.strip()
    if not cleaned:
        return []
    chunks = [c.strip() for c in re.split(r"\n\s*\n+", cleaned) if c.strip()]
    if len(chunks) > 1:
        return chunks
    lines = [ln.strip() for ln in cleaned.splitlines() if len(ln.strip()) >= 60]
    if lines:
        return lines
    return [cleaned]


def _video_chunks(transcript: str) -> list[str]:
    """Cut a transcript into caption-sized chunks (~280 chars each)."""
    if not transcript:
        return []
    sents = re.split(r"(?<=[.!?])\s+", transcript.strip())
    chunks: list[str] = []
    current = ""
    for s in sents:
        if not s:
            continue
        if len(current) + len(s) + 1 <= 280:
            current = (current + " " + s).strip()
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= 60]


async def _reverse_brief(
    brand_name: str, platform: str, post_text: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any] | None:
    """Best-effort: failure returns None and the caller skips the pair.

    Throttled by ``sem`` because we now fire 200+ of these per corpus
    build and Gemini's free tier rate-limits hard at high QPS.
    """
    async with sem:
        try:
            return await chat_json(
                fprompts.reverse_brief_messages(brand_name, platform, post_text),
                schema=fprompts.REVERSE_BRIEF_SCHEMA,
            )
        except Exception as e:
            log.warning("reverse_brief failed (%s): %s", platform, e)
            return None


def _post_to_pair(
    system_prompt: str, brief: str, platform: str, post_text: str
) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fprompts.render_user_turn(brief, platform)},
            {
                "role": "assistant",
                "content": fprompts.render_assistant_turn(post_text, [], ""),
            },
        ]
    }


async def _build_real_post_pairs(
    brand_name: str,
    system_prompt: str,
    pasted: list[str],
    posts: list[dict[str, Any]],
    web_chunks: list[tuple[str, str]],  # (chunk_text, source_kind)
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reverse-brief every real piece of brand text we have.

    Sources are ordered by signal strength (pasted > social > video >
    web). Each source is capped independently so a long-tailed sitemap
    doesn't drown out the brand's actual social voice.
    """
    sem = asyncio.Semaphore(_REVERSE_BRIEF_PARALLELISM)
    tasks: list[tuple[str, str, asyncio.Task]] = []

    # 1. Pasted posts (highest-signal — user explicitly chose them).
    for body in pasted[:_REAL_POST_CAP]:
        tasks.append(
            (
                "pasted",
                body,
                asyncio.create_task(
                    _reverse_brief(brand_name, "social", body, sem)
                ),
            )
        )

    # 2. Scraped social posts.
    real_taken = len(tasks)
    for p in posts:
        if real_taken >= _REAL_POST_CAP:
            break
        caption = (p.get("caption") or "").strip()
        platform = p.get("platform") or "social"
        if len(caption) >= 40:
            tasks.append(
                (
                    f"social_{platform}",
                    caption,
                    asyncio.create_task(
                        _reverse_brief(brand_name, platform, caption, sem)
                    ),
                )
            )
            real_taken += 1

    # 3. Video transcript chunks.
    transcripts_taken = 0
    for p in posts:
        if transcripts_taken >= _VIDEO_TRANSCRIPT_CAP:
            break
        va = p.get("video_analysis") or {}
        transcript = (va.get("transcript") or "").strip()
        if not transcript:
            continue
        platform = p.get("platform") or "video"
        for chunk in _video_chunks(transcript)[:3]:
            if transcripts_taken >= _VIDEO_TRANSCRIPT_CAP:
                break
            tasks.append(
                (
                    f"video_{platform}",
                    chunk,
                    asyncio.create_task(
                        _reverse_brief(brand_name, platform, chunk, sem)
                    ),
                )
            )
            transcripts_taken += 1

    # 4. Deep-scraped website text chunks (about, blog, pricing, etc).
    #    We treat them as "web" platform — the model learns to write
    #    long-form brand voice as well as short social-style posts.
    for chunk_text, source_kind in web_chunks[:_DEEP_SCRAPE_CAP]:
        tasks.append(
            (
                f"web_{source_kind}",
                chunk_text,
                asyncio.create_task(
                    _reverse_brief(brand_name, "web", chunk_text, sem)
                ),
            )
        )

    breakdown: dict[str, int] = {}
    pairs: list[dict[str, Any]] = []
    for source, post_text, task in tasks:
        result = await task
        if not result:
            continue
        brief = result.get("brief") or ""
        platform = result.get("platform") or "social"
        if not brief:
            continue
        pairs.append(_post_to_pair(system_prompt, brief, platform, post_text))
        breakdown[source] = breakdown.get(source, 0) + 1
    return pairs, breakdown


async def _build_synthetic_pairs(
    brand_name: str,
    voice_profile: dict[str, Any],
    system_prompt: str,
    target: int,
    vocabulary_hint: str = "",
) -> list[dict[str, Any]]:
    """Ask Gemini to expand the voice profile into ``target`` extra pairs.

    Batches fire IN PARALLEL through a semaphore — sequential was the
    biggest contributor to slow corpus builds. Each batch is still
    capped at _SYNTHETIC_BATCH (~25) because Gemini drifts to generic
    on larger single asks. Quality is preserved; latency is reduced
    ~Nx where N = parallelism.
    """
    if target <= 0:
        return []

    n_batches = (target + _SYNTHETIC_BATCH - 1) // _SYNTHETIC_BATCH
    sem = asyncio.Semaphore(_REVERSE_BRIEF_PARALLELISM)

    async def one_batch(n: int) -> list[dict[str, Any]]:
        async with sem:
            try:
                payload = await chat_json(
                    fprompts.synthetic_pairs_messages(
                        brand_name, voice_profile, n, vocabulary_hint
                    ),
                    schema=fprompts.SYNTHETIC_PAIRS_SCHEMA,
                )
            except Exception as e:
                log.warning("synthetic batch failed: %s", e)
                return []
        items = payload.get("pairs") or []
        out: list[dict[str, Any]] = []
        for item in items:
            brief = (item.get("brief") or "").strip()
            caption = (item.get("caption") or "").strip()
            platform = item.get("platform") or "social"
            if not brief or not caption:
                continue
            assistant = fprompts.render_assistant_turn(
                caption, item.get("hashtags") or [], item.get("cta") or ""
            )
            out.append(
                {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": fprompts.render_user_turn(brief, platform),
                        },
                        {"role": "assistant", "content": assistant},
                    ]
                }
            )
        return out

    sizes = [_SYNTHETIC_BATCH] * (n_batches - 1) + [
        target - _SYNTHETIC_BATCH * (n_batches - 1)
    ]
    results = await asyncio.gather(*(one_batch(s) for s in sizes))
    pairs: list[dict[str, Any]] = []
    for batch_pairs in results:
        pairs.extend(batch_pairs)
    return pairs[:target]


def _corpus_dir(brand_id: str) -> Path:
    base = Path(settings.storage_dir) / "finetune" / brand_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def _set_phase(
    brand_id: str, *, status: str | None = None, stage: str | None = None
) -> None:
    """Write phase progress straight to the brand row.

    The worker subprocess can't reach the parent's pyee bus, so the
    only way to surface progress to the UI is by writing to the DB.
    Frontend polls /api/finetune/status every 2s.
    """
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return
        if status:
            row.voice_model_status = status
        if stage is not None:
            meta = dict(row.voice_corpus_meta or {})
            meta["current_stage"] = stage
            row.voice_corpus_meta = meta
        db.add(row)
        db.commit()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


async def build_corpus(brand_id: str) -> CorpusResult | None:
    """Read the tenant, build the JSONL, persist meta on the Brand row.

    Returns ``None`` (and emits ``voice.corpus_failed``) when there's no
    voice profile yet — the corpus depends on it for the system prompt
    and for synthetic expansion.
    """
    # We DON'T emit VOICE_CORPUS_BUILDING here — the deep-scrape phase
    # comes first chronologically, so emitting "corpus building" up
    # front would make the UI flip backwards (deep_scraping → corpus
    # building → ... wait no, deep_scraping again). Order: deep_scraping
    # first, corpus_building once we've started reverse-briefing.

    with SessionLocal() as db:
        brand = db.get(models.Brand, brand_id)
        if brand is None:
            bus.emit(
                Events.VOICE_CORPUS_FAILED,
                {"brand_id": brand_id, "error": "brand not found"},
            )
            return None
        brand_name = brand.name or "the brand"
        brand_url = brand.url
        voice_profile = dict(brand.voice_profile or {})
        pasted_raw = brand.pasted_posts
        recent_posts = list(brand.recent_posts or [])

    if not voice_profile.get("tone") and not voice_profile.get("voice_excerpt"):
        bus.emit(
            Events.VOICE_CORPUS_FAILED,
            {
                "brand_id": brand_id,
                "error": "no voice_profile yet — finish onboarding first",
            },
        )
        return None

    system_prompt = fprompts.voice_system_prompt(brand_name, voice_profile)
    pasted = _split_pasted(pasted_raw)

    # Phase 1 — Deep brand-surface scrape. Pulls voice signal from
    # /about, /blog, /pricing, /features, sitemap.xml, RSS feeds, and
    # any in-domain links from the homepage. ~10-30 s for a typical
    # site; the result is the dominant source for the corpus when the
    # tenant has few social posts.
    deep_chunks: list[tuple[str, str]] = []
    deep_meta: dict[str, Any] = {}
    if brand_url:
        _set_phase(
            brand_id,
            status="deep_scraping",
            stage=f"crawling {brand_url} — sitemap, RSS, /about, /blog…",
        )
        bus.emit(
            Events.VOICE_DEEP_SCRAPING,
            {"brand_id": brand_id, "url": brand_url},
        )
        try:
            scrape_result = await deep_scrape.deep_scrape(brand_url)
        except Exception as e:
            log.exception("deep_scrape failed: %s", e)
            scrape_result = None
        # Save deep_scrape stats to meta IMMEDIATELY so the UI can
        # show pages-fetched / chunks-found stats during the long
        # corpus build phase, not just after it finishes.
        if scrape_result is not None:
            with SessionLocal() as db:
                row = db.get(models.Brand, brand_id)
                if row is not None:
                    meta = dict(row.voice_corpus_meta or {})
                    meta["deep_scrape"] = {
                        "discovered_urls": scrape_result.discovered_urls,
                        "fetched_pages": scrape_result.fetched_pages,
                        "text_chunks": scrape_result.text_chunks,
                        "by_kind": scrape_result.by_kind,
                    }
                    row.voice_corpus_meta = meta
                    db.add(row)
                    db.commit()
        if scrape_result is not None:
            for page in scrape_result.pages:
                for chunk in page.chunks:
                    deep_chunks.append((chunk, page.kind))
            deep_meta = deep_scrape.serialize_result(scrape_result)
            bus.emit(
                Events.VOICE_DEEP_SCRAPED,
                {
                    "brand_id": brand_id,
                    "domain": scrape_result.domain,
                    "discovered_urls": scrape_result.discovered_urls,
                    "fetched_pages": scrape_result.fetched_pages,
                    "text_chunks": scrape_result.text_chunks,
                    "by_kind": scrape_result.by_kind,
                },
            )

    # Phase 2 — GLiNER2 entity extraction. Now runs over EVERYTHING
    # (pasted + social + scraped web) so the brand vocabulary covers
    # the full surface, not just what the brand happens to tweet.
    _set_phase(brand_id, stage="extracting brand vocabulary via GLiNER2…")
    all_text_for_entities = list(pasted)
    for p in recent_posts:
        cap = (p.get("caption") or "").strip()
        if cap:
            all_text_for_entities.append(cap)
    for chunk, _ in deep_chunks[:60]:  # entity-extraction has its own cap
        all_text_for_entities.append(chunk)
    extraction = await gliner_client.extract_brand_entities(
        all_text_for_entities, brand_name
    )
    vocabulary_hint = gliner_client.render_vocabulary_for_brief(extraction)

    # Phase 3 — Reverse-brief every real piece of brand text in
    # parallel (semaphore-throttled). This is the slow phase (~30-90s
    # of Gemini calls), so we emit corpus_building NOW so the UI
    # transitions out of deep_scraping.
    real_input_count = (
        len(pasted)
        + sum(1 for p in recent_posts if (p.get("caption") or "").strip())
        + len(deep_chunks)
    )
    _set_phase(
        brand_id,
        status="corpus_building",
        stage=f"reverse-briefing {real_input_count} real text chunks…",
    )
    bus.emit(Events.VOICE_CORPUS_BUILDING, {"brand_id": brand_id})
    real_pairs, breakdown = await _build_real_post_pairs(
        brand_name, system_prompt, pasted, recent_posts, deep_chunks
    )

    # Phase 4 — Top up to _SYNTHETIC_TARGET with grounded synthetics.
    synth_target = max(0, _SYNTHETIC_TARGET - len(real_pairs))
    if synth_target > 0:
        _set_phase(
            brand_id,
            stage=f"synthesising {synth_target} extra pairs grounded in voice profile…",
        )
    synth_pairs = await _build_synthetic_pairs(
        brand_name, voice_profile, system_prompt, synth_target, vocabulary_hint
    )
    if synth_pairs:
        breakdown["synthetic"] = len(synth_pairs)

    rows = real_pairs + synth_pairs
    if not rows:
        bus.emit(
            Events.VOICE_CORPUS_FAILED,
            {"brand_id": brand_id, "error": "no usable training data"},
        )
        return None

    out_path = _corpus_dir(brand_id) / "corpus.jsonl"
    _write_jsonl(out_path, rows)

    meta = {
        "line_count": len(rows),
        "breakdown": breakdown,
        "jsonl_path": str(out_path),
        "system_prompt_preview": system_prompt[:500],
        "entities": gliner_client.to_brand_meta(extraction),
        "deep_scrape": {
            "discovered_urls": deep_meta.get("discovered_urls", 0),
            "fetched_pages": deep_meta.get("fetched_pages", 0),
            "text_chunks": deep_meta.get("text_chunks", 0),
            "by_kind": deep_meta.get("by_kind", {}),
            # Drop heavy `pages` array from DB to keep the meta small.
        },
    }
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is not None:
            row.voice_corpus_meta = meta
            row.voice_model_status = "corpus_built"
            db.add(row)
            db.commit()

    bus.emit(
        Events.VOICE_CORPUS_BUILT,
        {
            "brand_id": brand_id,
            "line_count": len(rows),
            "breakdown": breakdown,
            "jsonl_path": str(out_path),
        },
    )
    log.info(
        "corpus built: brand=%s lines=%d breakdown=%s",
        brand_id,
        len(rows),
        breakdown,
    )
    return CorpusResult(
        brand_id=brand_id,
        jsonl_path=str(out_path),
        line_count=len(rows),
        breakdown=breakdown,
    )
