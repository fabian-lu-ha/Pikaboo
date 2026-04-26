"""Provider registry. Add new adapters here as they land."""
from __future__ import annotations

from app.services.kanban.providers.base import KanbanProvider
from app.services.kanban.providers.trello import TrelloProvider

# Jira / Linear / Notion: scaffolding lives in the abstraction; concrete
# adapters land in v2. Add them here when implemented.
_REGISTRY: dict[str, KanbanProvider] = {
    "trello": TrelloProvider(),
}


def get_provider(name: str) -> KanbanProvider:
    impl = _REGISTRY.get(name)
    if impl is None:
        raise ValueError(f"unknown kanban provider: {name!r}")
    return impl


def available_providers() -> list[str]:
    return sorted(_REGISTRY.keys())
