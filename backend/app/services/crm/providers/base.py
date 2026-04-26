"""Abstract CRM provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.services.crm.types import (
    CRMConnection,
    NormalizedCustomer,
    NormalizedEvent,
    NormalizedProduct,
)


class CRMProvider(ABC):
    """Adapter contract. Implementations are dumb data normalizers — they
    MUST NOT classify, score, or emit bus events. ``external_id`` must be
    stable so the sync layer can dedupe."""

    name: str = "base"

    @abstractmethod
    async def test_connection(self, credentials: dict) -> bool:
        """Round-trip the API once; return True iff creds are valid."""

    @abstractmethod
    async def list_customers(
        self, conn: CRMConnection
    ) -> list[NormalizedCustomer]:
        """Return all customers visible to the connected account."""

    @abstractmethod
    async def list_events(
        self,
        conn: CRMConnection,
        customer_external_id: str,
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        """Return engagement events for a single customer."""

    @abstractmethod
    async def list_products(
        self, conn: CRMConnection
    ) -> list[NormalizedProduct]:
        """Return the brand's product catalog."""
