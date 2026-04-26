"""Provider-agnostic CRM data shapes.

Provider adapters return ``NormalizedCustomer`` / ``NormalizedEvent`` /
``NormalizedProduct``. The sync layer upserts them into the DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NormalizedCustomer:
    provider: str
    external_id: str
    email: str
    name: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    attributes: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    signup_at: datetime | None = None
    # Multi-touch attribution. ``acquisition`` is the first-touch source +
    # campaign + utm + landing page + referrer. ``touchpoints`` is an ordered
    # journey beyond the first touch (return visits, newsletter clicks, etc.).
    acquisition: dict = field(default_factory=dict)
    touchpoints: list[dict] = field(default_factory=list)


@dataclass
class NormalizedEvent:
    external_customer_id: str
    # email_open | email_click | purchase | page_view | support_msg |
    # cart_abandoned | subscription_lapsed
    kind: str
    occurred_at: datetime
    payload: dict = field(default_factory=dict)


@dataclass
class NormalizedProduct:
    provider: str
    external_id: str
    name: str
    sku: str | None = None
    description: str | None = None
    price_cents: int = 0
    image_url: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class CRMConnection:
    """Per-brand, per-provider connection. Persisted under
    ``brands.crm_connections`` (a JSON dict keyed by provider name)."""

    provider: str
    credentials: dict
    last_synced_at: datetime | None = None
