"""Pipeline executor — run a visual node graph end-to-end.

Node kinds:
  * trigger        — head of the pipeline. Output = the trigger payload
                     (manual run, kanban event, shop event, schedule, webhook).
  * source         — pulls real brand data (customers / products / kanban).
  * filter         — case-insensitive substring rule against item JSON.
  * model          — variant-driven LLM call:
                       tag             — classify + tag-count + highlights
                       generate_copy   — draft per-channel copy
                       generate_image  — Gemini image gen
                       personalize     — per-customer email draft
                       summarize       — short narrative summary
  * destination    — variant-driven side effect:
                       log_only          — receipt only (current default)
                       save_campaign     — POST to Campaign row
                       send_email        — create EmailSend rows
                       append_to_library — push asset URLs onto brand.assets

Topological dispatch with Kahn's algorithm. Per-step events
(pipeline.node_started / completed / failed) stream over SSE so the
canvas lights each box live. The Model and Destination nodes accept a
``prompt`` config that overrides the default system prompt — full
freedom for the user, sane defaults when blank.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

from sqlalchemy.orm import Session

from app.db import models
from app.events.bus import bus
from app.events.types import Events
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------- topology


def _topo_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Return node ids in topological order. Cycles raise ValueError."""
    ids = [n["id"] for n in nodes]
    incoming: dict[str, set[str]] = {nid: set() for nid in ids}
    outgoing: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e["from"] in incoming and e["to"] in incoming:
            incoming[e["to"]].add(e["from"])
            outgoing[e["from"]].add(e["to"])

    ready: deque[str] = deque(
        sorted(nid for nid, parents in incoming.items() if not parents)
    )
    order: list[str] = []
    seen: set[str] = set()
    while ready:
        nid = ready.popleft()
        if nid in seen:
            continue
        seen.add(nid)
        order.append(nid)
        for child in sorted(outgoing[nid]):
            incoming[child].discard(nid)
            if not incoming[child] and child not in seen:
                ready.append(child)

    if len(order) != len(ids):
        raise ValueError("pipeline contains a cycle")
    return order


# ----------------------------------------------------------- helpers


def _flat_items(inputs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for inp in inputs:
        out.extend(inp.get("items") or [])
    return out


def _brand_dict(brand: models.Brand) -> dict:
    """Compact dict view of Brand used by prompt builders + image gen."""
    return {
        "id": brand.id,
        "name": brand.name,
        "url": brand.url,
        "description": brand.description,
        "voice_profile": brand.voice_profile or {},
        "identity": brand.identity or {},
        "palette": brand.palette or [],
        "palette_roles": brand.palette_roles or [],
        "logo_url": brand.logo_url,
        "screenshots": brand.screenshots or [],
        "assets": brand.assets or [],
        "recent_posts": brand.recent_posts or [],
        "reference_brands": brand.reference_brands or [],
        "research": brand.research or {},
    }


# ----------------------------------------------------------- triggers


async def _run_trigger(
    _db: Session,
    _brand_id: str,
    node: dict,
    _inputs: list[dict],
    trigger_payload: dict | None,
) -> dict:
    """Pass trigger payload through. ``items`` carries downstream rows.

    For variants that produce a single record (a kanban card move, a
    cart-abandoned event), ``items`` will hold that one record so a
    downstream filter / model / destination treats it like any other row.
    For ``manual`` runs, items is empty and the next source node is
    expected to fetch the dataset.
    """
    cfg = node.get("config") or {}
    variant = str(cfg.get("variant") or "manual")
    payload = trigger_payload or {}
    return {
        "kind": "trigger_payload",
        "variant": variant,
        "items": list(payload.get("items") or []),
        "raw": payload,
    }


# ----------------------------------------------------------- source


async def _run_source(
    db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    """Pull real brand data. If a trigger upstream already produced items
    (e.g. one specific kanban card), narrow to that scope; otherwise
    fetch the full dataset for the configured provider.
    """
    cfg = node.get("config") or {}
    provider = str(cfg.get("provider") or "CRM Export · Mock")
    p_lower = provider.lower()

    upstream = _flat_items(inputs)
    if upstream:
        # Trigger or earlier filter narrowed the scope — pass it through.
        return {
            "kind": "items",
            "source": provider,
            "items": upstream,
            "scoped_from_upstream": True,
        }

    if "kanban" in p_lower or "trello" in p_lower or "jira" in p_lower:
        rows = (
            db.query(models.KanbanCard)
            .filter(models.KanbanCard.brand_id == brand_id)
            .order_by(models.KanbanCard.moved_at.desc().nullslast())
            .limit(50)
            .all()
        )
        items = [
            {
                "id": r.external_id,
                "title": r.title or "",
                "description": r.description or "",
                "column": r.column,
                "labels": r.labels or [],
            }
            for r in rows
        ]
        return {"kind": "items", "source": provider, "items": items}

    if "klaviyo" in p_lower or "hubspot" in p_lower or "crm" in p_lower:
        rows = (
            db.query(models.Customer)
            .filter(models.Customer.brand_id == brand_id)
            .limit(200)
            .all()
        )
        items = [
            {
                "id": r.id,
                "email": r.email,
                "name": r.name,
                "city": r.city,
                "country": r.country,
                "tags": r.tags or [],
                "total_spend_cents": r.total_spend_cents or 0,
                "last_active_at": (
                    r.last_active_at.isoformat() if r.last_active_at else None
                ),
            }
            for r in rows
        ]
        return {"kind": "items", "source": provider, "items": items}

    products = (
        db.query(models.Product)
        .filter(models.Product.brand_id == brand_id)
        .limit(50)
        .all()
    )
    items = [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "price_cents": p.price_cents,
            "category": p.category,
        }
        for p in products
    ]
    return {"kind": "items", "source": provider, "items": items}


# ----------------------------------------------------------- filter


async def _run_filter(
    _db: Session, _brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    cfg = node.get("config") or {}
    rule = str(cfg.get("rule") or "").strip().lower()
    strict = bool(cfg.get("strict"))

    items = _flat_items(inputs)
    if not rule:
        return {"kind": "items", "items": items, "filter_rule": rule}

    kept = [it for it in items if rule in json.dumps(it, default=str).lower()]
    if not kept and not strict:
        kept = items
    return {
        "kind": "items",
        "items": kept,
        "filter_rule": rule,
        "kept_count": len(kept),
        "dropped_count": len(items) - len(kept),
    }


# ----------------------------------------------------------- model variants


async def _model_tag(
    _db: Session, brand_id: str, node: dict, items: list[dict]
) -> dict:
    cfg = node.get("config") or {}
    version = cfg.get("version") or "default"
    threshold = cfg.get("threshold") or 75
    tags = cfg.get("tags") or []
    custom_prompt = (cfg.get("prompt") or "").strip()

    sample = items[:25]
    default_system = (
        f"You are an analyst node in a marketing pipeline. Model: {version}. "
        f"Confidence threshold: {threshold}%. "
        f"Extract these tags from the input rows: {tags or ['theme']}. "
        "Return STRICT JSON only."
    )
    system = custom_prompt or default_system
    user = json.dumps({"row_count": len(items), "sample": sample}, default=str)
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tag_counts": {
                "type": "object",
                "additionalProperties": {"type": "integer"},
            },
            "highlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "reason"],
                },
            },
        },
        "required": ["summary", "tag_counts", "highlights"],
    }

    try:
        parsed = await chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=schema,
            brand_id=brand_id,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline.model.tag failed: %s", e)
        parsed = {
            "summary": f"model {version} unavailable: {e}",
            "tag_counts": {},
            "highlights": [],
        }
    return {
        "kind": "model_output",
        "variant": "tag",
        "model_version": version,
        "row_count": len(items),
        "tag_counts": parsed.get("tag_counts") or {},
        "highlights": parsed.get("highlights") or [],
        "summary": parsed.get("summary") or "",
        "items": items,
    }


async def _model_summarize(
    _db: Session, brand_id: str, node: dict, items: list[dict]
) -> dict:
    cfg = node.get("config") or {}
    custom_prompt = (cfg.get("prompt") or "").strip()
    bullets = int(cfg.get("bullets") or 3)
    default_system = (
        "You are a marketing analyst. Summarize the input rows in "
        f"{bullets} crisp bullets and one one-sentence headline. "
        "Return STRICT JSON only."
    )
    system = custom_prompt or default_system
    user = json.dumps(
        {"row_count": len(items), "sample": items[:30]}, default=str
    )
    schema = {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["headline", "bullets"],
    }
    try:
        parsed = await chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=schema,
            brand_id=brand_id,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline.model.summarize failed: %s", e)
        parsed = {"headline": f"summarize failed: {e}", "bullets": []}
    return {
        "kind": "model_output",
        "variant": "summarize",
        "headline": parsed.get("headline") or "",
        "bullets": parsed.get("bullets") or [],
        "summary": parsed.get("headline") or "",
        "row_count": len(items),
        "items": items,
    }


async def _model_generate_copy(
    db: Session, brand_id: str, node: dict, items: list[dict]
) -> dict:
    """Channel-aware copy generation. Calls the same prompt machinery the
    agent loop uses so the brand voice + research grounding apply."""
    from app.services.agent import channels as ch
    from app.services.agent import prompts as agent_prompts

    cfg = node.get("config") or {}
    channel_id = str(cfg.get("channel") or "linkedin")
    user_prompt = str(cfg.get("user_request") or "").strip()
    custom_prompt = (cfg.get("prompt") or "").strip()

    brand = db.get(models.Brand, brand_id)
    if brand is None:
        return {
            "kind": "model_output",
            "variant": "generate_copy",
            "drafts": [],
            "summary": "brand not found",
            "items": items,
        }

    channel = ch.CHANNELS.get(channel_id) or ch.CHANNELS.get("linkedin")
    if channel is None:
        return {
            "kind": "model_output",
            "variant": "generate_copy",
            "drafts": [],
            "summary": f"unknown channel {channel_id}",
            "items": items,
        }

    if not user_prompt:
        # Synthesize a request from the upstream items so an empty config
        # still produces something — pulls the first 5 row titles/keys.
        previews = []
        for it in items[:5]:
            previews.append(
                it.get("title")
                or it.get("name")
                or it.get("description")
                or json.dumps(it)[:80]
            )
        user_prompt = (
            f"Write a {channel.id} {channel.text_kind} based on the latest "
            f"items: {', '.join(p for p in previews if p)}"
            if previews
            else f"Write a {channel.id} {channel.text_kind} for {brand.name}."
        )

    brand_data = _brand_dict(brand)
    messages = agent_prompts.channel_post_messages(
        brand_data, channel, user_prompt
    )
    if custom_prompt:
        # User-overridden system prompt replaces the default channel system,
        # but we keep the user-message (with brand context) intact.
        messages = [
            {"role": "system", "content": custom_prompt},
            messages[1],
        ]

    schema = ch.schema_for(channel)
    try:
        parsed = await chat_json(
            messages=messages, schema=schema, brand_id=brand_id
        )
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline.model.generate_copy failed: %s", e)
        return {
            "kind": "model_output",
            "variant": "generate_copy",
            "drafts": [],
            "summary": f"generate_copy failed: {e}",
            "items": items,
        }

    title, body = ch.extract_text(channel, parsed)
    draft = {
        "channel": channel.id,
        "label": channel.label,
        "kind": channel.text_kind,
        "title": title,
        "body": body,
        "image_url": None,
        "image_aspect": (channel.image.aspect if channel.image else None),
    }
    return {
        "kind": "model_output",
        "variant": "generate_copy",
        "channel": channel.id,
        "drafts": [draft],
        "title": title,
        "body": body,
        "summary": title or body[:140],
        "user_request": user_prompt,
        "items": items,
    }


async def _model_generate_image(
    db: Session, brand_id: str, node: dict, items: list[dict]
) -> dict:
    """Generate one channel image using the existing nano-banana wrapper."""
    from app.config import settings
    from app.services.agent import channels as ch
    from app.services.agent import image_gen
    from pathlib import Path
    from uuid import uuid4

    cfg = node.get("config") or {}
    channel_id = str(cfg.get("channel") or "instagram")
    user_prompt = str(cfg.get("prompt") or "").strip()

    brand = db.get(models.Brand, brand_id)
    if brand is None:
        return {
            "kind": "model_output",
            "variant": "generate_image",
            "image_url": None,
            "summary": "brand not found",
            "items": items,
        }
    channel = ch.CHANNELS.get(channel_id) or ch.CHANNELS.get("instagram")
    if channel is None or channel.image is None:
        return {
            "kind": "model_output",
            "variant": "generate_image",
            "image_url": None,
            "summary": f"channel {channel_id} has no image slot",
            "items": items,
        }

    if not user_prompt:
        user_prompt = f"Hero image for {brand.name} — bold, on-brand"

    img_bytes = await image_gen.generate_channel_image(
        _brand_dict(brand), channel, user_prompt
    )
    if not img_bytes:
        return {
            "kind": "model_output",
            "variant": "generate_image",
            "image_url": None,
            "summary": "image generation returned empty",
            "items": items,
        }

    images_dir = Path(settings.storage_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    fname = f"pipeline-{uuid4().hex[:12]}.png"
    out = images_dir / fname
    out.write_bytes(img_bytes)
    image_url = f"/api/storage/images/{fname}"
    return {
        "kind": "model_output",
        "variant": "generate_image",
        "image_url": image_url,
        "channel": channel.id,
        "aspect": channel.image.aspect if channel.image else None,
        "user_request": user_prompt,
        "summary": f"generated {channel.id} image",
        "items": items,
    }


async def _model_personalize(
    db: Session, brand_id: str, node: dict, items: list[dict]
) -> dict:
    """Iterate over upstream customer rows, run personalize_for_customer."""
    from app.services.audience.personalization import personalize_for_customer

    cfg = node.get("config") or {}
    user_prompt = (cfg.get("user_request") or "").strip() or None
    max_n = int(cfg.get("max_customers") or 5)

    customer_ids: list[str] = []
    for it in items[:max_n]:
        cid = it.get("id") if isinstance(it, dict) else None
        if isinstance(cid, str) and cid:
            customer_ids.append(cid)

    drafts: list[dict] = []
    errors: list[str] = []
    for cid in customer_ids:
        try:
            res = await personalize_for_customer(
                db, brand_id, cid, user_prompt=user_prompt
            )
            drafts.append(
                {
                    "customer_id": cid,
                    "subject": res.get("subject") or "",
                    "body": res.get("body") or "",
                    "html_body": res.get("html_body") or "",
                    "recommended_product_ids": res.get(
                        "recommended_product_ids", []
                    ),
                }
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cid}: {e}")
            log.warning("pipeline.model.personalize %s failed: %s", cid, e)

    return {
        "kind": "model_output",
        "variant": "personalize",
        "drafts": drafts,
        "errors": errors,
        "summary": f"personalized {len(drafts)} of {len(customer_ids)}",
        "row_count": len(drafts),
        "items": items,
    }


_MODEL_VARIANTS: dict[str, Callable[..., Awaitable[dict]]] = {
    "tag": _model_tag,
    "summarize": _model_summarize,
    "generate_copy": _model_generate_copy,
    "generate_image": _model_generate_image,
    "personalize": _model_personalize,
}


async def _run_model(
    db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    cfg = node.get("config") or {}
    variant = str(cfg.get("variant") or "tag")
    handler = _MODEL_VARIANTS.get(variant) or _model_tag
    items = _flat_items(inputs)
    return await handler(db, brand_id, node, items)


# ----------------------------------------------------------- destination variants


async def _dest_log_only(
    _db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    cfg = node.get("config") or {}
    target = str(cfg.get("target") or "Log")
    fmt = str(cfg.get("format") or "JSON")
    items = _flat_items(inputs)
    merged: dict[str, Any] = {"summary": "", "tag_counts": {}, "highlights": []}
    drafts: list[dict] = []
    for inp in inputs:
        if inp.get("kind") == "model_output":
            merged["summary"] = inp.get("summary") or merged["summary"]
            merged["tag_counts"] = (
                inp.get("tag_counts") or merged["tag_counts"]
            )
            merged["highlights"] = (
                inp.get("highlights") or merged["highlights"]
            )
            for d in inp.get("drafts") or []:
                drafts.append(d)
    return {
        "kind": "destination_receipt",
        "variant": "log_only",
        "target": target,
        "format": fmt,
        "brand_id": brand_id,
        "record_count": len(items),
        "summary": merged["summary"],
        "tag_counts": merged["tag_counts"],
        "highlights": merged["highlights"],
        "drafts": drafts[:8],
        "wrote_at": _now_iso(),
        "preview": items[:5],
    }


async def _dest_save_campaign(
    db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    """Persist a Campaign row from the merged upstream output.

    Uses the same Campaign table the dashboard's Recent Runs reads from,
    so a successful pipeline run is visible in the same surface as agent-
    generated campaigns.
    """
    cfg = node.get("config") or {}
    title = str(cfg.get("title") or "").strip()
    items = _flat_items(inputs)
    drafts: list[dict] = []
    summary_parts: list[str] = []
    image_url: str | None = None
    for inp in inputs:
        if inp.get("kind") != "model_output":
            continue
        summary_parts.append(str(inp.get("summary") or ""))
        for d in inp.get("drafts") or []:
            drafts.append(d)
        if inp.get("image_url") and not image_url:
            image_url = str(inp.get("image_url"))

    final_title = (
        title
        or (drafts[0].get("title") if drafts else None)
        or (summary_parts[0] if summary_parts else None)
        or f"Pipeline run {_now_iso()[:16]}"
    )

    bundle = {
        "user_request": str(cfg.get("user_request") or "Pipeline run"),
        "drafts": drafts,
        "hero_image_url": image_url,
        "predicted_lift": None,
        "target_prompts": [],
        "source": "pipeline",
        "pipeline_summary": " · ".join([s for s in summary_parts if s])[:400],
    }
    campaign = models.Campaign(
        brand_id=brand_id,
        title=final_title[:200],
        bundle=bundle,
        trigger="pipeline",
        status="draft",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    return {
        "kind": "destination_receipt",
        "variant": "save_campaign",
        "target": "Campaign",
        "campaign_id": campaign.id,
        "title": campaign.title,
        "draft_count": len(drafts),
        "summary": bundle["pipeline_summary"],
        "drafts": drafts,
        "wrote_at": _now_iso(),
        "record_count": len(items),
    }


async def _dest_send_email(
    db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    """Create one EmailSend row per personalize-style draft.

    Honors the same "queued" status the audience dispatcher uses — emails
    aren't actually sent in dev, but they appear in the EmailSend log
    exactly like a real dispatch would.
    """
    cfg = node.get("config") or {}
    fallback_subject = str(
        cfg.get("subject") or "Update from your favorite brand"
    )

    sends: list[dict] = []
    for inp in inputs:
        if inp.get("kind") != "model_output":
            continue
        for draft in inp.get("drafts") or []:
            cid = draft.get("customer_id")
            subject = draft.get("subject") or draft.get("title") or fallback_subject
            body = draft.get("body") or ""
            html_body = draft.get("html_body") or None
            target_kind = "customer" if cid else "broadcast"
            target_id = cid or brand_id
            row = models.EmailSend(
                brand_id=brand_id,
                target_kind=target_kind,
                target_id=target_id,
                subject=subject[:200],
                body=body,
                html_body=html_body,
                status="queued",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            sends.append(
                {
                    "id": row.id,
                    "customer_id": cid,
                    "subject": subject,
                    "status": row.status,
                }
            )
            bus.emit(
                Events.AUDIENCE_EMAIL_DISPATCHED,
                {
                    "brand_id": brand_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "recipient_count": 1,
                },
            )

    return {
        "kind": "destination_receipt",
        "variant": "send_email",
        "target": "EmailSend",
        "record_count": len(sends),
        "sends": sends,
        "summary": f"queued {len(sends)} emails",
        "wrote_at": _now_iso(),
    }


async def _dest_append_to_library(
    db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    """Append generated image URLs onto brand.assets so the asset library
    surfaces pipeline-generated visuals next to manually-uploaded ones.
    """
    urls: list[str] = []
    for inp in inputs:
        if inp.get("kind") == "model_output" and inp.get("image_url"):
            urls.append(str(inp["image_url"]))
    if not urls:
        return {
            "kind": "destination_receipt",
            "variant": "append_to_library",
            "target": "brand.assets",
            "record_count": 0,
            "summary": "no image URLs upstream",
            "wrote_at": _now_iso(),
        }
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        return {
            "kind": "destination_receipt",
            "variant": "append_to_library",
            "target": "brand.assets",
            "record_count": 0,
            "summary": "brand not found",
            "wrote_at": _now_iso(),
        }
    existing = list(brand.assets or [])
    additions = [
        {"url": u, "source": "pipeline", "added_at": _now_iso()}
        for u in urls
        if u not in {(a.get("url") if isinstance(a, dict) else a) for a in existing}
    ]
    brand.assets = existing + additions
    db.add(brand)
    db.commit()
    return {
        "kind": "destination_receipt",
        "variant": "append_to_library",
        "target": "brand.assets",
        "record_count": len(additions),
        "added_urls": urls,
        "summary": f"appended {len(additions)} assets",
        "wrote_at": _now_iso(),
    }


_DEST_VARIANTS: dict[str, Callable[..., Awaitable[dict]]] = {
    "log_only": _dest_log_only,
    "save_campaign": _dest_save_campaign,
    "send_email": _dest_send_email,
    "append_to_library": _dest_append_to_library,
}


async def _run_destination(
    db: Session, brand_id: str, node: dict, inputs: list[dict]
) -> dict:
    cfg = node.get("config") or {}
    variant = str(cfg.get("variant") or "log_only")
    handler = _DEST_VARIANTS.get(variant) or _dest_log_only
    return await handler(db, brand_id, node, inputs)


# ----------------------------------------------------------- main loop


async def execute(
    db: Session,
    pipeline_id: str,
    trigger_payload: dict | None = None,
) -> dict:
    """Run a pipeline by id. ``trigger_payload`` is forwarded to any
    ``trigger`` node and exposed in the run.result. Manual runs pass None.
    """
    p: models.Pipeline | None = db.get(models.Pipeline, pipeline_id)
    if p is None:
        raise ValueError(f"pipeline not found: {pipeline_id}")

    nodes = list(p.nodes or [])
    edges = list(p.edges or [])
    if not nodes:
        raise ValueError("pipeline has no nodes")

    run = models.PipelineRun(
        pipeline_id=p.id,
        brand_id=p.brand_id,
        status="running",
        node_states={n["id"]: "pending" for n in nodes},
        logs=[],
        result={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    bus.emit(
        Events.PIPELINE_RUN_STARTED,
        {
            "pipeline_id": p.id,
            "run_id": run.id,
            "brand_id": p.brand_id,
            "node_count": len(nodes),
            "trigger": (trigger_payload or {}).get("trigger") or "manual",
        },
    )

    try:
        order = _topo_sort(nodes, edges)
    except ValueError as e:
        run.status = "failed"
        run.error = str(e)
        run.finished_at = _now()
        db.add(run)
        db.commit()
        bus.emit(
            Events.PIPELINE_RUN_FAILED,
            {"pipeline_id": p.id, "run_id": run.id, "error": str(e)},
        )
        return {"id": run.id, "status": "failed", "error": str(e)}

    by_id = {n["id"]: n for n in nodes}
    parents: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e["from"] in by_id and e["to"] in by_id:
            parents[e["to"]].append(e["from"])

    outputs: dict[str, dict] = {}
    states: dict[str, str] = {n["id"]: "pending" for n in nodes}
    logs: list[dict] = []

    for nid in order:
        node = by_id[nid]
        kind = str(node.get("kind") or "").lower()
        states[nid] = "running"
        run.node_states = dict(states)
        db.add(run)
        db.commit()
        bus.emit(
            Events.PIPELINE_NODE_STARTED,
            {
                "pipeline_id": p.id,
                "run_id": run.id,
                "node_id": nid,
                "kind": kind,
                "name": node.get("name"),
                "variant": (node.get("config") or {}).get("variant"),
            },
        )

        in_payloads = [outputs[pid] for pid in parents[nid] if pid in outputs]
        try:
            if kind == "trigger":
                out = await _run_trigger(
                    db, p.brand_id, node, in_payloads, trigger_payload
                )
            elif kind == "source":
                out = await _run_source(db, p.brand_id, node, in_payloads)
            elif kind == "filter":
                out = await _run_filter(db, p.brand_id, node, in_payloads)
            elif kind == "model":
                out = await _run_model(db, p.brand_id, node, in_payloads)
            elif kind == "destination":
                out = await _run_destination(db, p.brand_id, node, in_payloads)
            else:
                raise ValueError(f"unknown node kind: {kind}")
        except Exception as e:  # noqa: BLE001
            log.exception("pipeline node %s failed", nid)
            states[nid] = "failed"
            logs.append(
                {
                    "node_id": nid,
                    "level": "error",
                    "msg": str(e),
                    "at": _now_iso(),
                }
            )
            run.node_states = dict(states)
            run.logs = list(logs)
            run.status = "failed"
            run.error = str(e)
            run.finished_at = _now()
            db.add(run)
            db.commit()
            bus.emit(
                Events.PIPELINE_NODE_FAILED,
                {
                    "pipeline_id": p.id,
                    "run_id": run.id,
                    "node_id": nid,
                    "error": str(e),
                },
            )
            bus.emit(
                Events.PIPELINE_RUN_FAILED,
                {"pipeline_id": p.id, "run_id": run.id, "error": str(e)},
            )
            return {"id": run.id, "status": "failed", "error": str(e)}

        outputs[nid] = out
        states[nid] = "completed"
        log_entry = {
            "node_id": nid,
            "level": "info",
            "kind": kind,
            "preview": _preview_for_log(out),
            "at": _now_iso(),
        }
        logs.append(log_entry)
        run.node_states = dict(states)
        run.logs = list(logs)
        db.add(run)
        db.commit()
        bus.emit(
            Events.PIPELINE_NODE_COMPLETED,
            {
                "pipeline_id": p.id,
                "run_id": run.id,
                "node_id": nid,
                "kind": kind,
                "preview": log_entry["preview"],
            },
        )

        # Yield so SSE consumers see node updates as the run progresses.
        await asyncio.sleep(0)

    leaves = [
        nid for nid in order
        if not any(e["from"] == nid for e in edges)
    ]
    final_id = next(
        (
            nid for nid in reversed(order)
            if (by_id[nid].get("kind") == "destination" and nid in outputs)
        ),
        leaves[-1] if leaves else order[-1],
    )
    final = outputs.get(final_id, {})

    run.status = "completed"
    run.result = final
    run.finished_at = _now()
    db.add(run)
    db.commit()
    bus.emit(
        Events.PIPELINE_RUN_COMPLETED,
        {
            "pipeline_id": p.id,
            "run_id": run.id,
            "duration_ms": int(
                (run.finished_at - run.started_at).total_seconds() * 1000
            ),
            "result": final,
        },
    )

    return {
        "id": run.id,
        "status": "completed",
        "result": final,
        "node_states": dict(states),
    }


def _preview_for_log(out: dict) -> dict:
    if not isinstance(out, dict):
        return {"value": str(out)[:200]}
    preview = {
        k: v
        for k, v in out.items()
        if k not in ("items", "preview", "drafts", "highlights", "tag_counts", "raw")
    }
    items = out.get("items")
    if isinstance(items, Iterable):
        try:
            preview["item_count"] = len(items)  # type: ignore[arg-type]
        except TypeError:
            pass
    drafts = out.get("drafts")
    if isinstance(drafts, list):
        preview["draft_count"] = len(drafts)
    return preview
