"""Abstract provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.kanban.types import (
    CardEvent,
    NormalizedCard,
    ProviderConnection,
)


class KanbanProvider(ABC):
    """Adapter contract. Implementations are dumb data normalizers — they
    MUST NOT classify cards or emit bus events. That's the signal layer's
    job. ``external_id`` must be stable so the sync layer can dedupe."""

    name: str = "base"

    @abstractmethod
    async def test_connection(self, credentials: dict) -> bool:
        """Round-trip the API once; return True iff creds are valid."""

    @abstractmethod
    async def list_boards(self, conn: ProviderConnection) -> list[dict]:
        """Return ``[{id, name, url}, ...]`` for the connected account."""

    @abstractmethod
    async def list_cards(
        self,
        conn: ProviderConnection,
        board_id: str,
        since: Any | None = None,
    ) -> list[NormalizedCard]:
        """All cards on a board, optionally filtered by recent activity."""

    @abstractmethod
    async def register_webhook(
        self,
        conn: ProviderConnection,
        callback_url: str,
        board_id: str,
    ) -> str:
        """Register a webhook on the source. Return provider webhook id."""

    @abstractmethod
    async def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        secret: str | None = None,
    ) -> CardEvent | None:
        """Verify signature and decode payload into a ``CardEvent``.

        Return ``None`` for heartbeat / unrelated payloads. Raise on
        signature failure — never trust unverified payloads.
        """
