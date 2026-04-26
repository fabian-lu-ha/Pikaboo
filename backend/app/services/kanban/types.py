"""Provider-agnostic kanban data shapes.

The provider layer emits ``NormalizedCard`` / ``CardEvent``; the signal layer
consumes them and emits ``KanbanSignal`` (and the matching bus event).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CardEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    MOVED = "moved"
    COMPLETED = "completed"
    DELETED = "deleted"


class SignalKind(str, Enum):
    FEATURE_SHIPPED = "feature_shipped"
    FEATURE_IN_FLIGHT = "feature_in_flight"
    MARKETING_ACTIVE = "marketing_active"


@dataclass
class NormalizedCard:
    provider: str
    external_id: str
    board_id: str
    board_name: str
    column: str
    title: str
    description: str = ""
    labels: list[str] = field(default_factory=list)
    assignee: str | None = None
    due_date: datetime | None = None
    moved_at: datetime | None = None
    url: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class CardEvent:
    type: CardEventType
    card: NormalizedCard
    previous_column: str | None = None
    received_at: datetime | None = None


@dataclass
class KanbanSignal:
    kind: SignalKind
    brand_id: str
    card: NormalizedCard
    confidence: float = 1.0
    reason: str = ""


@dataclass
class ProviderConnection:
    """Per-brand, per-provider connection. Persisted under
    ``brands.kanban_connections`` (a JSON dict keyed by provider name)."""

    provider: str
    credentials: dict
    selected_boards: list[str] = field(default_factory=list)
    webhook_id: str | None = None
    last_synced_at: datetime | None = None
