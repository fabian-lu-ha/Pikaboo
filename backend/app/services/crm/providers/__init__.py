"""Provider registry. Add new CRM adapters here as they land."""
from __future__ import annotations

from app.services.crm.providers.base import CRMProvider
from app.services.crm.providers.mock import MockCRMProvider

# HubSpot / Klaviyo / Shopify: scaffold lives in the abstraction; concrete
# adapters land later. Add them here when implemented.
_REGISTRY: dict[str, CRMProvider] = {
    "mock": MockCRMProvider(),
}


def get_provider(name: str) -> CRMProvider:
    impl = _REGISTRY.get(name)
    if impl is None:
        raise ValueError(f"unknown crm provider: {name!r}")
    return impl


def available_providers() -> list[str]:
    return sorted(_REGISTRY.keys())
