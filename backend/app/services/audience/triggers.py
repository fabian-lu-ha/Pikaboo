"""Auto-plan trigger dispatcher.

Subscribes to the in-process event bus and, when a relevant signal lands
for a customer, calls ``campaign_planner.plan_campaign`` to create a
``draft`` Campaign. The campaign does NOT auto-launch; the human still
hits "Send all" in the drawer. This is "AI surfaces, human approves".

Rules registered:
  * ``cart_abandoned``         — listens to ``AUDIENCE_SHOP_EVENT_TRIGGERED``
  * ``subscription_lapsed``    — listens to ``AUDIENCE_SHOP_EVENT_TRIGGERED``
  * ``new_arrival_in_category`` — listens to ``CUSTOMER_EVENT_INSERTED``
                                   (not yet emitted; rule is wired but inert
                                   until the signal source lights up)

Recent fires are kept in a small in-memory ring buffer (last 50 across
all rules and brands) so the UI's "Triggers panel" has something to
render without a persistence layer. Restarts wipe history; events are
still in the bus log if anyone needs forensic detail later.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events

log = logging.getLogger(__name__)


# Rule definitions. ``debounce_seconds`` is the minimum gap between two
# fires for the same (brand_id, customer_id, rule_id) tuple — prevents a
# noisy CRM webhook from spamming the planner. ``listens_to`` is the
# event name the dispatcher wires this rule onto.
TRIGGER_RULES: dict[str, dict[str, Any]] = {
    "cart_abandoned": {
        "id": "cart_abandoned",
        "label": "Cart abandoned",
        "description": (
            "When a customer abandons a cart, plan a 3-touch recovery "
            "campaign as a draft."
        ),
        "enabled": True,
        "debounce_seconds": 60 * 60,  # one fire per hour per customer
        "listens_to": Events.AUDIENCE_SHOP_EVENT_TRIGGERED,
        "shop_event_kind": "cart_abandoned",
    },
    "subscription_lapsed": {
        "id": "subscription_lapsed",
        "label": "Subscription lapsed",
        "description": (
            "When a subscription lapses, plan a reactivation campaign."
        ),
        "enabled": True,
        "debounce_seconds": 60 * 60 * 24,  # one fire per day per customer
        "listens_to": Events.AUDIENCE_SHOP_EVENT_TRIGGERED,
        "shop_event_kind": "subscription_lapsed",
    },
    "new_arrival_in_category": {
        "id": "new_arrival_in_category",
        "label": "New arrival in category",
        "description": (
            "When a new product lands in a customer's top category, "
            "plan a launch campaign."
        ),
        "enabled": False,  # off by default — needs a launch-event source
        "debounce_seconds": 60 * 60 * 24 * 3,
        "listens_to": None,  # wired when a launch event source ships
        "shop_event_kind": None,
    },
}

_RECENT_FIRES: deque[dict] = deque(maxlen=50)
_LAST_FIRE_AT: dict[tuple[str, str, str], datetime] = {}
_REGISTERED = False


def enabled_rules() -> list[dict]:
    """Return rule rows for the Triggers panel. Ordered by rule id."""
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "description": r["description"],
            "enabled": bool(r["enabled"]),
            "debounce_seconds": int(r["debounce_seconds"]),
        }
        for r in TRIGGER_RULES.values()
    ]


def set_rule_enabled(rule_id: str, enabled: bool) -> dict:
    rule = TRIGGER_RULES.get(rule_id)
    if rule is None:
        raise ValueError(f"unknown trigger rule: {rule_id}")
    rule["enabled"] = bool(enabled)
    return {
        "id": rule["id"],
        "enabled": rule["enabled"],
    }


def recent_fires(brand_id: str | None, limit: int = 20) -> list[dict]:
    out = [
        f for f in _RECENT_FIRES if not brand_id or f.get("brand_id") == brand_id
    ]
    return list(reversed(out))[:limit]


def _record_fire(payload: dict) -> None:
    entry = dict(payload)
    entry.setdefault(
        "fired_at", datetime.now(timezone.utc).isoformat()
    )
    _RECENT_FIRES.append(entry)


def _debounce_key(
    brand_id: str, customer_id: str, rule_id: str
) -> tuple[str, str, str]:
    return (brand_id, customer_id, rule_id)


def _within_debounce(rule: dict, brand_id: str, customer_id: str) -> bool:
    key = _debounce_key(brand_id, customer_id, rule["id"])
    last = _LAST_FIRE_AT.get(key)
    if last is None:
        return False
    delta = (datetime.now(timezone.utc) - last).total_seconds()
    return delta < int(rule["debounce_seconds"])


def _stamp_fire(rule: dict, brand_id: str, customer_id: str) -> None:
    _LAST_FIRE_AT[_debounce_key(brand_id, customer_id, rule["id"])] = (
        datetime.now(timezone.utc)
    )


async def _plan_async(
    brand_id: str,
    customer_id: str,
    rule_id: str,
) -> None:
    """Run the planner with a fresh DB session.

    pyee dispatches in the event loop; we never want to block it on the
    LLM call, so this is async by construction. Failures are logged but
    swallowed — a planning blow-up should never crash the upstream
    shop-event handler.
    """
    from app.services.audience.campaign_planner import plan_campaign

    db = SessionLocal()
    try:
        result = await plan_campaign(
            db,
            brand_id,
            "customer",
            customer_id,
            rule_id,
        )
        _record_fire(
            {
                "brand_id": brand_id,
                "customer_id": customer_id,
                "trigger": rule_id,
                "campaign_id": result.get("campaign_id"),
            }
        )
        bus.emit(
            Events.CAMPAIGN_TRIGGER_FIRED,
            {
                "brand_id": brand_id,
                "customer_id": customer_id,
                "trigger": rule_id,
                "campaign_id": result.get("campaign_id"),
            },
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "trigger %s: plan_campaign failed for brand=%s customer=%s",
            rule_id,
            brand_id,
            customer_id,
        )
    finally:
        db.close()


def _on_shop_event(payload: dict) -> None:
    """Handler for ``AUDIENCE_SHOP_EVENT_TRIGGERED``.

    Routes to whichever shop-kind rule matches (cart_abandoned or
    subscription_lapsed). Respects per-rule enable + debounce. Schedules
    the planner asynchronously on the running loop.
    """
    if not isinstance(payload, dict):
        return
    kind = payload.get("kind")
    brand_id = payload.get("brand_id")
    customer_id = payload.get("customer_id")
    if not (kind and brand_id and customer_id):
        return

    matching = [
        r for r in TRIGGER_RULES.values() if r.get("shop_event_kind") == kind
    ]
    for rule in matching:
        if not rule["enabled"]:
            continue
        if _within_debounce(rule, brand_id, customer_id):
            log.info(
                "trigger %s: debounced for brand=%s customer=%s",
                rule["id"],
                brand_id,
                customer_id,
            )
            continue
        _stamp_fire(rule, brand_id, customer_id)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                _plan_async(brand_id, customer_id, rule["id"])
            )
        except RuntimeError:
            # No running loop (e.g. test harness firing the bus from a
            # sync context). Fall back to a one-shot run; shouldn't happen
            # in production paths but keeps the dispatcher robust.
            asyncio.run(_plan_async(brand_id, customer_id, rule["id"]))


def register() -> None:
    """Attach the bus listeners. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    bus.on(Events.AUDIENCE_SHOP_EVENT_TRIGGERED, _on_shop_event)
    _REGISTERED = True
    log.info(
        "audience.triggers: registered %d rule(s)",
        sum(1 for r in TRIGGER_RULES.values() if r["enabled"]),
    )
