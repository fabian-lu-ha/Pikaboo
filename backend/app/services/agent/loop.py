"""Agent loop — listens for chat.submitted on the pyee bus and runs the full
draft + image + lift pipeline.

The listener is registered at module-load time via `register_listener()` so
that importing `app.services.agent` from `main.py` is enough to wire it up.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.providers.factory import get_storage
from app.services.agent.channels import (
    Channel,
    extract_text,
    resolve_channels,
    resolve_channels_from_formats,
    schema_for,
)
from app.services.agent.image_gen import generate_channel_image
from app.services.agent.lift import predict_lift
from app.services.agent.prompts import channel_post_messages
from app.services.llm.client import chat_json
from app.services.peec import (
    PeecSnapshot,
    fetch_snapshot,
    get_peec,
    select_target_prompts,
)
from app.services.research import gather_campaign_context

log = logging.getLogger(__name__)

_registered = False


def register_listener() -> None:
    """Idempotent — safe to call multiple times."""
    global _registered
    if _registered:
        return
    bus.on(Events.CHAT_SUBMITTED, _on_chat_submitted)
    _registered = True


async def _on_chat_submitted(payload: dict) -> None:
    try:
        await run_agent(payload)
    except Exception as e:
        log.exception("agent loop crashed: %s", e)
        bus.emit(
            Events.AGENT_FAILED,
            {"error": str(e)[:240]},
        )


async def run_agent(payload: dict) -> None:
    text = (payload.get("text") or "").strip()
    if not text:
        return

    # Optional explicit format ids from the frontend FormatPicker. When set,
    # they override the keyword-based channel heuristic — picking LinkedIn
    # alone produces only a LinkedIn draft, picking LinkedIn + Instagram
    # produces both, and so on.
    raw_formats = payload.get("formats") or []
    requested_formats: list[str] = [
        str(f) for f in raw_formats if isinstance(f, str) and f.strip()
    ]

    brand_data = _load_latest_brand()
    if brand_data is None:
        bus.emit(Events.AGENT_FAILED, {"error": "no onboarded brand"})
        return

    campaign_id = str(uuid4())
    bus.emit(
        Events.AGENT_STARTED,
        {
            "campaign_id": campaign_id,
            "brand_id": brand_data["id"],
            "user_request": text,
        },
    )

    await _step(campaign_id, "reading your voice profile")
    await _step(
        campaign_id,
        f"scanning {len(brand_data['competitors'])} competitors",
    )

    # ── Peec visibility + Tavily research run in parallel ────────────────
    # Both are network-bound, neither blocks the other. Research output
    # gets injected into each channel's drafting prompt so blog/social
    # copy is grounded in fresh sources rather than priors.
    await _step(campaign_id, "fetching peec visibility + live web research")
    peec_result, research_bundle = await asyncio.gather(
        _resolve_target_prompts(campaign_id, brand_data),
        _resolve_research(campaign_id, brand_data, text),
    )
    peec_snapshot, target_prompts = peec_result
    brand_data["_campaign_research"] = research_bundle.to_dict()

    # ── Per-channel drafts in PARALLEL (one text + one image per channel) ──
    # When the user picked explicit formats in the FormatPicker, honour them
    # exactly — no auto-adding `blog` or other channels from brand handles.
    # If the resolution yields nothing (unknown ids only) we fall back to
    # the heuristic so a typo doesn't kill the whole run.
    channels: list[Channel] = []
    if requested_formats:
        channels = resolve_channels_from_formats(requested_formats)
    if not channels:
        channels = resolve_channels(brand_data, text)

    # Inject format-variant hints (e.g. "carousel") into the prompt text so
    # that within a single channel (instagram) the LLM picks up the intended
    # variant. Channel selection itself was already constrained above.
    drafter_text = text
    if requested_formats:
        labels = ", ".join(requested_formats)
        drafter_text = f"{text}\n\n[Output formats requested: {labels}]"

    await _step(
        campaign_id,
        f"drafting {len(channels)} channels in parallel: "
        + ", ".join(c.label for c in channels),
    )
    drafts_for_bundle: list[dict] = await asyncio.gather(
        *(_run_channel(campaign_id, brand_data, channel, drafter_text) for channel in channels)
    )

    blog = next(
        (d for d in drafts_for_bundle if d["channel"] == "blog"), None
    )
    blog_title = (blog or {}).get("title", "") or ""
    blog_body = (blog or {}).get("body", "") or ""
    # Take any non-blog channel's body as the "social" voice sample for lift.
    social_text = next(
        (d["body"] for d in drafts_for_bundle if d["channel"] != "blog" and d.get("body")),
        "",
    )

    # ── Lift ──────────────────────────────────────────────────────────────
    await _step(campaign_id, "predicting lift")
    target_prompt_strings = [
        tp.prompt if hasattr(tp, "prompt") else str(tp)
        for tp in target_prompts
    ]
    lift = predict_lift(
        text,
        target_prompt_strings,
        draft_bodies=[blog_body, social_text],
    )
    bus.emit(
        Events.LIFT_PREDICTED,
        {"campaign_id": campaign_id, **lift},
    )

    # ── Persist + bundle ──────────────────────────────────────────────────
    hero_url = next(
        (d["image_url"] for d in drafts_for_bundle if d.get("image_url")),
        None,
    )
    linkedin_body = next(
        (d["body"] for d in drafts_for_bundle if d["channel"] == "linkedin"),
        social_text,
    )
    bundle = {
        "user_request": text,
        "drafts": drafts_for_bundle,
        # Legacy flat fields kept for any consumer that hasn't migrated.
        "blog": {"title": blog_title, "body": blog_body},
        "social": {"linkedin": linkedin_body},
        "hero_image_url": hero_url,
        "predicted_lift": lift,
        "target_prompts": target_prompt_strings,
        "peec_snapshot": (
            peec_snapshot.to_event_payload()
            if peec_snapshot is not None
            else None
        ),
        "research": research_bundle.to_dict(),
    }

    try:
        # The run-checkpoint listener (services/agent/checkpoints.py) creates
        # the Campaign row eagerly on agent.started and patches it on every
        # progress event, so we use ``merge`` here to upsert without a
        # primary-key collision when this final write races the listener.
        with SessionLocal() as db:
            camp = models.Campaign(
                id=campaign_id,
                brand_id=brand_data["id"],
                title=blog_title or text[:80],
                bundle=bundle,
                predicted_lift=lift.get("lift_percent"),
            )
            db.merge(camp)
            db.commit()
    except Exception as e:
        log.exception("campaign persist failed: %s", e)

    await _step(campaign_id, "done.")
    bus.emit(
        Events.CAMPAIGN_BUNDLED,
        {
            "campaign_id": campaign_id,
            "brand_id": brand_data["id"],
            "title": blog_title or text[:80],
            "bundle": bundle,
        },
    )

    # ── GEO optimization fan-out ─────────────────────────────────────────
    # Once the campaign is bundled and the user can see drafts, kick off
    # GEO gap detection + recommendation in the background. The dashboard's
    # GeoPanel subscribes to the GEO_* events and fills in opportunities
    # without the user lifting a finger. Reuse the snapshot we already
    # fetched so we don't re-hit Peec.
    if peec_snapshot is not None:
        try:
            from app.services.geo.gap_detector import (
                detect_gaps_for_brand,
                scan_for_brand,
            )

            async def _geo_fanout() -> None:
                gap_ids = await detect_gaps_for_brand(
                    brand_data["id"],
                    snapshot=peec_snapshot,
                    source_campaign_id=campaign_id,
                )
                if not gap_ids:
                    return
                # detect_gaps_for_brand already emits GEO_GAP_DETECTED per
                # gap; now spawn the recommender for each.
                from app.services.geo.recommender import recommend_for_gap

                await asyncio.gather(
                    *(_safe(recommend_for_gap, gid) for gid in gap_ids),
                    return_exceptions=False,
                )

            asyncio.create_task(_geo_fanout())
            # Reference scan_for_brand to pacify import-checkers — we use the
            # lower-level path here to avoid double-emitting GEO_SCAN_STARTED.
            _ = scan_for_brand
        except Exception as e:  # noqa: BLE001 — never block campaign on GEO
            log.warning("geo fan-out scheduling failed: %s", e)


async def _safe(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        log.warning("geo fan-out task crashed in %s: %s", fn.__name__, e)
        return None


# ── Helpers ──────────────────────────────────────────────────────────────


async def _run_channel(
    campaign_id: str, brand_data: dict, channel: Channel, user_request: str
) -> dict:
    """Draft text + (optional) image for ONE channel. Emits DRAFT_CREATED for
    each artefact as it lands so the UI fills in progressively. Returns a
    dict for inclusion in the campaign bundle."""
    await _step(campaign_id, f"drafting {channel.label} {channel.text_kind}")
    text_draft = await _safe_chat_json(
        channel_post_messages(brand_data, channel, user_request),
        schema_for(channel),
        brand_id=brand_data.get("id"),
    )
    title, body = extract_text(channel, text_draft)
    bus.emit(
        Events.DRAFT_CREATED,
        {
            "campaign_id": campaign_id,
            "channel": channel.id,
            "title": title or channel.label,
            "preview": body[:240],
            "body": body,
        },
    )

    image_url: str | None = None
    if channel.image is not None:
        await _step(
            campaign_id,
            f"generating {channel.image.aspect_label} image for {channel.label}",
        )
        image_url = await _try_channel_image(
            campaign_id, brand_data, channel, user_request
        )
        if image_url:
            bus.emit(
                Events.DRAFT_CREATED,
                {
                    "campaign_id": campaign_id,
                    "channel": f"{channel.id}_image",
                    "title": f"{channel.label} {channel.image.aspect_label}",
                    "preview": image_url,
                    "body": image_url,
                },
            )
        else:
            # Always emit a marker — even on failure — so the frontend stops
            # showing "generating image…" forever. Empty body/preview is the
            # signal that this channel's image is unavailable. The actual
            # reason (no GEMINI_API_KEY, quota, safety block, storage write
            # failed) is in the server log warnings from _try_channel_image.
            await _step(
                campaign_id,
                f"image unavailable for {channel.label} — see server logs",
            )
            bus.emit(
                Events.DRAFT_CREATED,
                {
                    "campaign_id": campaign_id,
                    "channel": f"{channel.id}_image",
                    "title": f"{channel.label} image unavailable",
                    "preview": "",
                    "body": "",
                },
            )

    return {
        "channel": channel.id,
        "label": channel.label,
        "kind": channel.text_kind,
        "title": title,
        "body": body,
        "image_url": image_url,
        "image_aspect": channel.image.aspect if channel.image else None,
    }


async def _step(campaign_id: str, label: str) -> None:
    bus.emit(
        Events.AGENT_STEP,
        {
            "campaign_id": campaign_id,
            "id": str(uuid4()),
            "label": label,
            "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        },
    )
    await asyncio.sleep(0.05)


async def _safe_chat_json(
    messages: list[dict], schema: dict, brand_id: str | None = None
) -> dict | None:
    try:
        return await chat_json(messages, schema=schema, brand_id=brand_id)
    except Exception as e:
        log.warning("agent draft chat_json failed: %s", e)
        return None


async def _try_channel_image(
    campaign_id: str,
    brand_data: dict,
    channel: Channel,
    user_request: str,
) -> str | None:
    try:
        image_bytes = await generate_channel_image(
            brand_data, channel, user_request
        )
    except Exception as e:
        log.warning("channel image gen failed [%s]: %s", channel.id, e)
        return None
    if not image_bytes:
        return None
    try:
        storage = get_storage()
        key = f"campaigns/{campaign_id}/{channel.id}.png"
        await storage.put(key, image_bytes, "image/png")
        return await storage.get_url(key)
    except Exception as e:
        log.warning("channel image store failed [%s]: %s", channel.id, e)
        return None


def _placeholder_target_prompts(brand_data: dict) -> list[str]:
    """Mock fallback when Peec isn't configured / available."""
    name = (brand_data.get("name") or "").split()[0] or "the product"
    desc = (brand_data.get("description") or "")[:80].rstrip(".")
    return [
        f"best alternatives to {name}",
        f"{name} vs Salesforce" if "crm" in desc.lower() else f"{name} vs the leader",
        f"how to {desc.split(' ', 1)[0].lower() or 'pick'} {name.lower()} alternatives",
    ][:3]


async def _resolve_research(
    campaign_id: str, brand_data: dict, user_request: str
):
    """Tavily campaign research — fail-soft. Returns a CampaignResearch
    bundle (possibly empty) so the caller can always serialize it into the
    campaign and pass it through to draft prompts."""
    try:
        return await gather_campaign_context(
            campaign_id=campaign_id,
            brand_id=brand_data.get("id"),
            brand_name=brand_data.get("name") or "the brand",
            description=brand_data.get("description"),
            user_request=user_request,
        )
    except Exception:
        log.exception("campaign research crashed")
        from app.services.research.orchestrator import CampaignResearch
        from datetime import datetime as _dt, timezone as _tz

        return CampaignResearch(
            campaign_id=campaign_id,
            brand_id=brand_data.get("id"),
            user_request=user_request,
            fetched_at=_dt.now(_tz.utc).isoformat(),
            error="research crashed",
        )


async def _resolve_target_prompts(
    campaign_id: str, brand_data: dict
) -> tuple[PeecSnapshot | None, list]:
    """Try Peec for real target prompts + visibility data. Fall back to mock
    on any failure / missing key. Always emits one of two events so the UI
    knows whether the demo data is real or mocked."""
    peec = get_peec()
    if peec is None:
        await _step(campaign_id, "peec api key not set — using mock prompts")
        bus.emit(
            Events.AGENT_PEEC_UNAVAILABLE,
            {"campaign_id": campaign_id, "reason": "no api key"},
        )
        return None, _placeholder_target_prompts(brand_data)

    await _step(campaign_id, "fetching peec visibility snapshot")
    try:
        snap = await fetch_snapshot(brand_data)
    except Exception as e:
        log.warning("peec fetch_snapshot crashed: %s", e)
        snap = None

    if snap is None:
        bus.emit(
            Events.AGENT_PEEC_UNAVAILABLE,
            {"campaign_id": campaign_id, "reason": "fetch failed"},
        )
        return None, _placeholder_target_prompts(brand_data)

    targets = select_target_prompts(snap, k=3)
    bus.emit(
        Events.AGENT_PEEC_DATA_FETCHED,
        {
            "campaign_id": campaign_id,
            "brand_id": brand_data.get("id"),
            "snapshot": snap.to_event_payload(),
            "target_prompts": [
                {
                    "prompt": tp.prompt,
                    "competitor_winning": tp.competitor_winning,
                    "own_visibility": tp.own_visibility,
                    "score": tp.score,
                }
                for tp in targets
            ],
        },
    )
    if not targets:
        # snapshot succeeded but no absent prompts — reuse mock so the agent
        # still has something to ground drafts in.
        return snap, _placeholder_target_prompts(brand_data)
    return snap, targets


def _load_latest_brand() -> dict | None:
    """Read the most-recently-onboarded brand into a plain dict (so we can
    drop the session before the long-running LLM/image work)."""
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
            "research": brand.research or {},
            "competitors": [
                {
                    "name": c.name,
                    "url": c.url,
                    "reason": c.reason,
                }
                for c in brand.competitors
            ],
        }


# Auto-register when the module is imported.
register_listener()
