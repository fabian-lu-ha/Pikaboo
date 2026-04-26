"""Backfill CRM customers, events, and products into the DB.

Provider-agnostic. The HTTP endpoint in ``api/audience.py`` calls
``import_all`` here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models
from app.events.bus import bus
from app.events.types import Events
from app.services.crm.providers import get_provider
from app.services.crm.types import (
    CRMConnection,
    NormalizedCustomer,
    NormalizedEvent,
    NormalizedProduct,
)

log = logging.getLogger(__name__)


def _connection_from_brand(
    brand: models.Brand, provider: str
) -> CRMConnection | None:
    blob = (brand.crm_connections or {}).get(provider)
    if not blob:
        return None
    creds = dict(blob.get("credentials") or {})
    # Mock provider keys its deterministic seed off brand_id; inject so the
    # adapter doesn't have to know about ORM concepts.
    creds.setdefault("brand_id", brand.id)
    return CRMConnection(provider=provider, credentials=creds)


def _persist_customer(
    db: Session, brand_id: str, c: NormalizedCustomer
) -> models.Customer:
    # Stash multi-touch attribution under known keys in the existing
    # ``attributes`` JSON. Customer table has no dedicated columns for these.
    merged_attrs = {
        **(c.attributes or {}),
        "acquisition": dict(c.acquisition or {}),
        "touchpoints": list(c.touchpoints or []),
    }
    existing = (
        db.query(models.Customer)
        .filter_by(
            brand_id=brand_id, provider=c.provider, external_id=c.external_id
        )
        .one_or_none()
    )
    if existing is not None:
        existing.email = c.email
        existing.name = c.name
        existing.phone = c.phone
        existing.city = c.city
        existing.country = c.country
        existing.attributes = merged_attrs
        existing.tags = c.tags
        existing.signup_at = c.signup_at
        return existing
    row = models.Customer(
        brand_id=brand_id,
        provider=c.provider,
        external_id=c.external_id,
        email=c.email,
        name=c.name,
        phone=c.phone,
        city=c.city,
        country=c.country,
        attributes=merged_attrs,
        tags=c.tags,
        signup_at=c.signup_at,
    )
    db.add(row)
    db.flush()
    return row


def _replace_events(
    db: Session,
    brand_id: str,
    customer: models.Customer,
    events: list[NormalizedEvent],
) -> int:
    """Replace this customer's events wholesale. Mock data is deterministic so
    re-import is idempotent; for live providers we'd delta by occurred_at."""
    db.query(models.CustomerEvent).filter_by(
        brand_id=brand_id, customer_id=customer.id
    ).delete(synchronize_session=False)
    for e in events:
        db.add(
            models.CustomerEvent(
                brand_id=brand_id,
                customer_id=customer.id,
                kind=e.kind,
                occurred_at=e.occurred_at,
                payload=e.payload,
            )
        )
    return len(events)


def _replace_products(
    db: Session, brand_id: str, provider: str, products: list[NormalizedProduct]
) -> int:
    """Replace the product catalog wholesale per (brand, provider)."""
    db.query(models.Product).filter_by(brand_id=brand_id).filter(
        models.Product.sku.isnot(None)
    ).delete(synchronize_session=False)
    # Simpler: nuke all products for the brand (single-source assumption today).
    db.query(models.Product).filter_by(brand_id=brand_id).delete(
        synchronize_session=False
    )
    for p in products:
        db.add(
            models.Product(
                brand_id=brand_id,
                sku=p.sku,
                name=p.name,
                description=p.description,
                price_cents=p.price_cents,
                image_url=p.image_url,
                category=p.category,
                tags=p.tags,
            )
        )
    return len(products)


def _aggregate_customer_stats(events: list[NormalizedEvent]) -> tuple[int, datetime | None]:
    spend = 0
    last_active: datetime | None = None
    for e in events:
        if e.kind == "purchase":
            spend += int((e.payload or {}).get("amount_cents") or 0)
        if last_active is None or e.occurred_at > last_active:
            last_active = e.occurred_at
    return spend, last_active


async def import_all(
    db: Session, brand_id: str, provider: str
) -> dict:
    """Pull customers + events + products and upsert. Returns counts."""
    brand = db.get(models.Brand, brand_id)
    if brand is None:
        log.warning("crm.import: brand %s not found", brand_id)
        return {"customer_count": 0, "product_count": 0, "event_count": 0}

    conn = _connection_from_brand(brand, provider)
    if conn is None:
        log.warning(
            "crm.import: no %s connection for brand %s", provider, brand_id
        )
        return {"customer_count": 0, "product_count": 0, "event_count": 0}

    impl = get_provider(provider)

    bus.emit(
        Events.AUDIENCE_IMPORT_STARTED,
        {"brand_id": brand_id, "provider": provider},
    )

    customers = await impl.list_customers(conn)
    products = await impl.list_products(conn)

    product_count = _replace_products(db, brand_id, provider, products)

    total_events = 0
    for nc in customers:
        row = _persist_customer(db, brand_id, nc)
        events = await impl.list_events(conn, nc.external_id)
        n = _replace_events(db, brand_id, row, events)
        total_events += n
        spend, last_active = _aggregate_customer_stats(events)
        row.total_spend_cents = spend
        row.last_active_at = last_active

    blob = (brand.crm_connections or {}).get(provider, {})
    blob["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    brand.crm_connections = {
        **(brand.crm_connections or {}),
        provider: blob,
    }
    db.add(brand)
    db.commit()

    payload = {
        "brand_id": brand_id,
        "provider": provider,
        "customer_count": len(customers),
        "product_count": product_count,
        "event_count": total_events,
    }
    bus.emit(Events.AUDIENCE_CUSTOMERS_IMPORTED, payload)
    return {
        "customer_count": len(customers),
        "product_count": product_count,
        "event_count": total_events,
    }
