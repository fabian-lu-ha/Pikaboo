"""Classify normalized card events into business-meaningful signals.

Rule-based for v0.5: column-name + label match. LLM fallback for ambiguous
cards is a v2 deferral. The agent loop subscribes to the bus events emitted
here and never imports a provider.
"""
from __future__ import annotations

import logging

from app.events.bus import bus
from app.events.types import Events
from app.services.kanban.types import (
    CardEvent,
    CardEventType,
    KanbanSignal,
    NormalizedCard,
    SignalKind,
)

log = logging.getLogger(__name__)


SHIPPED_COLUMN_TOKENS = (
    "done", "shipped", "released", "deployed", "live", "complete",
)
IN_FLIGHT_COLUMN_TOKENS = (
    "doing", "in progress", "in-progress", "wip", "review", "qa", "testing",
)
MARKETING_TOKENS = (
    "marketing", "growth", "campaign", "launch", "press", "pr", "content",
)


def _matches(haystack: str, needles: tuple[str, ...]) -> bool:
    h = (haystack or "").lower()
    return any(n in h for n in needles)


def _is_marketing_card(card: NormalizedCard) -> bool:
    if _matches(card.board_name, MARKETING_TOKENS):
        return True
    return any(_matches(label, MARKETING_TOKENS) for label in card.labels)


def classify(event: CardEvent) -> SignalKind | None:
    """Map a CardEvent to a SignalKind, or None if it isn't actionable."""
    card = event.card
    if event.type == CardEventType.DELETED:
        return None

    if _is_marketing_card(card):
        return SignalKind.MARKETING_ACTIVE

    if event.type == CardEventType.COMPLETED:
        return SignalKind.FEATURE_SHIPPED
    if event.type == CardEventType.MOVED and _matches(
        card.column, SHIPPED_COLUMN_TOKENS
    ):
        return SignalKind.FEATURE_SHIPPED

    if _matches(card.column, IN_FLIGHT_COLUMN_TOKENS):
        return SignalKind.FEATURE_IN_FLIGHT

    return None


_EVENT_BY_KIND = {
    SignalKind.FEATURE_SHIPPED: Events.KANBAN_FEATURE_SHIPPED,
    SignalKind.FEATURE_IN_FLIGHT: Events.KANBAN_FEATURE_IN_FLIGHT,
    SignalKind.MARKETING_ACTIVE: Events.KANBAN_MARKETING_ACTIVE,
}


async def handle_event(brand_id: str, event: CardEvent) -> KanbanSignal | None:
    """Classify a card event and emit the matching bus event."""
    kind = classify(event)
    if kind is None:
        log.debug(
            "kanban.signal: %s on card %s did not match any signal",
            event.type.value,
            event.card.external_id,
        )
        return None

    signal = KanbanSignal(
        kind=kind,
        brand_id=brand_id,
        card=event.card,
        reason=f"column={event.card.column!r} type={event.type.value}",
    )

    bus.emit(
        _EVENT_BY_KIND[kind],
        {
            "brand_id": brand_id,
            "provider": event.card.provider,
            "kind": kind.value,
            "reason": signal.reason,
            "card": {
                "external_id": event.card.external_id,
                "title": event.card.title,
                "description": event.card.description,
                "url": event.card.url,
                "labels": event.card.labels,
                "column": event.card.column,
                "board_name": event.card.board_name,
            },
        },
    )
    return signal
