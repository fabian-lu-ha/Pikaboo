"""Backfill + webhook → signal plumbing.

Provider-agnostic. The HTTP webhook endpoint in ``api/kanban.py`` calls
``handle_webhook`` here; the connect/sync flow calls ``backfill``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.events.bus import bus
from app.events.types import Events
from app.services.kanban.providers import get_provider
from app.services.kanban.signals import handle_event
from app.services.kanban.types import (
    CardEvent,
    CardEventType,
    NormalizedCard,
    ProviderConnection,
)

log = logging.getLogger(__name__)


def _parse_iso(s: Any) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _connection_from_brand(
    brand: models.Brand, provider: str
) -> ProviderConnection | None:
    blob = (brand.kanban_connections or {}).get(provider)
    if not blob:
        return None
    return ProviderConnection(
        provider=provider,
        credentials=blob.get("credentials") or {},
        selected_boards=list(blob.get("selected_boards") or []),
        webhook_id=blob.get("webhook_id"),
        last_synced_at=_parse_iso(blob.get("last_synced_at")),
    )


def _persist_card(
    db: Session, brand_id: str, card: NormalizedCard
) -> None:
    """Upsert a card row keyed by (brand_id, provider, external_id)."""
    existing = (
        db.query(models.KanbanCard)
        .filter_by(
            brand_id=brand_id,
            provider=card.provider,
            external_id=card.external_id,
        )
        .one_or_none()
    )
    if existing is not None:
        existing.board_id = card.board_id
        existing.board_name = card.board_name
        existing.column = card.column
        existing.title = card.title
        existing.description = card.description
        existing.labels = card.labels
        existing.due_date = card.due_date
        existing.moved_at = card.moved_at
        existing.url = card.url
    else:
        db.add(
            models.KanbanCard(
                brand_id=brand_id,
                provider=card.provider,
                external_id=card.external_id,
                board_id=card.board_id,
                board_name=card.board_name,
                column=card.column,
                title=card.title,
                description=card.description,
                labels=card.labels,
                due_date=card.due_date,
                moved_at=card.moved_at,
                url=card.url,
            )
        )


async def backfill(
    db: Session,
    brand_id: str,
    provider: str,
    days: int = 30,
) -> int:
    """Pull recent cards for every selected board and emit signals.

    Returns the number of cards persisted (not the number of signals fired —
    most cards classify to no signal under the rule heuristics)."""
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        log.warning("kanban.backfill: brand %s not found", brand_id)
        return 0

    conn = _connection_from_brand(brand, provider)
    if conn is None:
        log.warning(
            "kanban.backfill: no %s connection for brand %s",
            provider,
            brand_id,
        )
        return 0

    impl = get_provider(provider)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    bus.emit(
        Events.KANBAN_SYNC_STARTED,
        {"brand_id": brand_id, "provider": provider, "since_days": days},
    )

    total = 0
    for board_id in conn.selected_boards:
        try:
            cards = await impl.list_cards(conn, board_id, since=since)
        except Exception as e:  # noqa: BLE001
            log.exception(
                "kanban.backfill: list_cards failed for %s/%s: %s",
                provider,
                board_id,
                e,
            )
            continue
        for card in cards:
            _persist_card(db, brand_id, card)
            total += 1
            event = CardEvent(
                type=CardEventType.UPDATED,
                card=card,
                received_at=datetime.now(timezone.utc),
            )
            await handle_event(brand_id, event)

    blob = (brand.kanban_connections or {}).get(provider, {})
    blob["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    brand.kanban_connections = {
        **(brand.kanban_connections or {}),
        provider: blob,
    }
    db.add(brand)
    db.commit()

    bus.emit(
        Events.KANBAN_SYNCED,
        {"brand_id": brand_id, "provider": provider, "card_count": total},
    )
    return total


async def handle_webhook(
    db: Session,
    provider: str,
    brand_id: str,
    payload: dict,
    headers: dict,
) -> bool:
    """Route a provider webhook payload through the signal layer."""
    impl = get_provider(provider)

    try:
        event = await impl.parse_webhook(payload, headers, secret=None)
    except Exception as e:  # noqa: BLE001 — bad signature, malformed payload
        log.warning(
            "kanban.webhook: %s parse failed for brand %s: %s",
            provider,
            brand_id,
            e,
        )
        return False

    if event is None:
        return False

    _persist_card(db, brand_id, event.card)
    db.commit()

    await handle_event(brand_id, event)
    return True
