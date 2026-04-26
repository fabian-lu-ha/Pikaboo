"""HubSpot CRM provider — pulls real Contacts, Engagement Events, and Products
through the HubSpot v3 API.

Auth: Private App access tokens (``Authorization: Bearer pat-...``). Frontend
posts the token as ``credentials.api_key`` and ``connect_crm`` round-trips it
through ``test_connection`` before persisting.

Scope: this adapter is a *normalizer* — no scoring, no DB writes, no event
emission. ``crm/sync.py`` is the only thing that mutates the DB.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.crm.providers.base import CRMProvider
from app.services.crm.types import (
    CRMConnection,
    NormalizedCustomer,
    NormalizedEvent,
    NormalizedProduct,
)

log = logging.getLogger(__name__)


HUBSPOT_BASE_URL = "https://api.hubapi.com"

# Per-call timeout. HubSpot's contact/event endpoints usually answer in < 1s
# but we leave headroom for cold accounts.
HTTP_TIMEOUT_SECONDS = 20.0

# Cap how much we pull on first import so the modal's "connect & import"
# button doesn't sit spinning for a minute on a large account. Easy to lift
# later when we add real pagination + a background sync worker.
MAX_CONTACTS = 100
MAX_PRODUCTS = 100
MAX_EVENTS_PER_CONTACT = 50

# Properties we ask HubSpot to include on each contact. Most accounts have
# these populated; missing values come back as None and we map to None.
CONTACT_PROPERTIES = [
    "email",
    "firstname",
    "lastname",
    "phone",
    "city",
    "country",
    "createdate",
    "lastmodifieddate",
    "lifecyclestage",
    "hs_lead_status",
    "hs_analytics_source",
    "hs_analytics_source_data_1",
    "hs_analytics_source_data_2",
    "hs_analytics_first_url",
    "hs_analytics_first_referrer",
    "hs_analytics_first_timestamp",
]

PRODUCT_PROPERTIES = [
    "name",
    "description",
    "price",
    "hs_sku",
    "hs_images",
    "hs_product_type",
]

# Map HubSpot's analytics source enum onto the same source strings the mock
# provider emits, so downstream segmentation and personalization see one
# vocabulary regardless of provider. Unknown values fall through to "direct".
HUBSPOT_SOURCE_MAP: dict[str, str] = {
    "ORGANIC_SEARCH": "organic_search",
    "PAID_SEARCH": "google_ads",
    "PAID_SOCIAL": "meta_ads",
    "SOCIAL_MEDIA": "meta_ads",
    "EMAIL_MARKETING": "newsletter",
    "REFERRALS": "referral_partner",
    "DIRECT_TRAFFIC": "direct",
    "OTHER_CAMPAIGNS": "direct",
    "OFFLINE": "direct",
}

# HubSpot Engagement-Event types we care about. The Events API emits dozens
# of internal types; we only forward the ones that map cleanly onto the
# normalized engagement vocabulary used by segmentation/personalization.
EVENT_KIND_MAP: dict[str, str] = {
    "pe_hs_email_open": "email_open",
    "pe_hs_email_click": "email_click",
    "pe_email_open": "email_open",
    "pe_email_click": "email_click",
    "e_visited_page": "page_view",
    "e_clicked_link": "email_click",
    "pe_hs_chat_message_sent": "support_msg",
    "pe_conversations_message_sent": "support_msg",
}


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _parse_iso(value: Any) -> datetime | None:
    """HubSpot returns ISO strings with a ``Z`` suffix. Tolerate ``None`` and
    odd shapes since live data is messy."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_cents(price_raw: Any) -> int:
    """HubSpot stores price as a string of dollars (e.g. ``"48.00"``).
    Convert to cents, returning 0 on anything we can't parse."""
    if price_raw in (None, ""):
        return 0
    try:
        return int(round(float(price_raw) * 100))
    except (TypeError, ValueError):
        return 0


def _full_name(first: str | None, last: str | None, email: str | None) -> str | None:
    parts = [p for p in (first, last) if p]
    if parts:
        return " ".join(parts)
    if email:
        return email.split("@", 1)[0]
    return None


def _normalize_acquisition(props: dict[str, Any]) -> dict[str, Any]:
    """Translate ``hs_analytics_*`` properties onto the same shape the mock
    provider produces, so the audience UI can render consistent attribution
    chips regardless of source."""
    raw_source = (props.get("hs_analytics_source") or "").upper()
    return {
        "source": HUBSPOT_SOURCE_MAP.get(raw_source, "direct"),
        "campaign": props.get("hs_analytics_source_data_2"),
        "utm_source": props.get("hs_analytics_source_data_1") or "",
        "utm_medium": "",
        "utm_campaign": props.get("hs_analytics_source_data_2") or "",
        "utm_content": "",
        "utm_term": "",
        "first_touch_url": props.get("hs_analytics_first_url") or "",
        "referrer": props.get("hs_analytics_first_referrer") or "",
    }


def _contact_to_normalized(item: dict[str, Any]) -> NormalizedCustomer | None:
    """Translate one HubSpot contact record into our shared shape. Returns
    ``None`` if the contact has no email — emails are our only stable
    addressable handle for personalization."""
    props = item.get("properties") or {}
    email = props.get("email")
    if not email:
        return None
    first = props.get("firstname")
    last = props.get("lastname")
    signup_at = _parse_iso(
        props.get("createdate") or props.get("hs_analytics_first_timestamp")
    )
    acquisition = _normalize_acquisition(props)
    touchpoints: list[dict] = []
    if signup_at:
        touchpoints.append(
            {
                "source": acquisition["source"],
                "campaign": acquisition["campaign"],
                "at": signup_at.isoformat(),
                "action": "first_visit",
            }
        )

    tags: list[str] = []
    lifecycle = props.get("lifecyclestage")
    if lifecycle:
        tags.append(str(lifecycle))
    lead_status = props.get("hs_lead_status")
    if lead_status:
        tags.append(str(lead_status).lower())

    return NormalizedCustomer(
        provider="hubspot",
        external_id=str(item.get("id")),
        email=email,
        name=_full_name(first, last, email),
        phone=props.get("phone"),
        city=props.get("city"),
        country=props.get("country"),
        attributes={
            "lifecyclestage": lifecycle,
            "lead_status": lead_status,
            "hubspot_id": str(item.get("id")),
        },
        tags=tags,
        signup_at=signup_at,
        acquisition=acquisition,
        touchpoints=touchpoints,
    )


def _product_to_normalized(item: dict[str, Any]) -> NormalizedProduct | None:
    props = item.get("properties") or {}
    name = props.get("name")
    if not name:
        return None
    images_raw = props.get("hs_images") or ""
    image_url = None
    if isinstance(images_raw, str) and images_raw:
        # HubSpot stores hs_images as a semicolon-separated list of URLs.
        first = images_raw.split(";")[0].strip()
        image_url = first or None
    return NormalizedProduct(
        provider="hubspot",
        external_id=str(item.get("id")),
        name=name,
        sku=props.get("hs_sku"),
        description=props.get("description"),
        price_cents=_to_cents(props.get("price")),
        image_url=image_url,
        category=props.get("hs_product_type"),
        tags=[],
    )


def _event_to_normalized(
    raw: dict[str, Any], external_customer_id: str
) -> NormalizedEvent | None:
    """Forward only events we have a clean mapping for — the Engagement
    Events API exposes ~40 event types and most are noise for our purposes."""
    event_type = raw.get("eventType") or raw.get("event_type") or ""
    kind = EVENT_KIND_MAP.get(event_type)
    if kind is None:
        return None
    occurred = _parse_iso(raw.get("occurredAt") or raw.get("occurred_at"))
    if occurred is None:
        return None
    payload_raw = raw.get("properties") or {}
    payload: dict[str, Any] = {}
    if kind in ("email_open", "email_click"):
        subject = payload_raw.get("hs_email_subject") or payload_raw.get("subject")
        if subject:
            payload["subject"] = subject
        link = payload_raw.get("hs_link_url") or payload_raw.get("hs_url")
        if link and kind == "email_click":
            payload["link"] = link
    elif kind == "page_view":
        path = payload_raw.get("hs_url") or payload_raw.get("page_url")
        if path:
            payload["path"] = path
    elif kind == "support_msg":
        payload["channel"] = "chat"
    return NormalizedEvent(
        external_customer_id=external_customer_id,
        kind=kind,
        occurred_at=occurred,
        payload=payload,
    )


class HubSpotCRMProvider(CRMProvider):
    """HubSpot Private App adapter. One token == one portal."""

    name = "hubspot"

    async def test_connection(self, credentials: dict) -> bool:
        api_key = (credentials or {}).get("api_key", "").strip()
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(
                base_url=HUBSPOT_BASE_URL,
                timeout=HTTP_TIMEOUT_SECONDS,
                headers=_auth_headers(api_key),
            ) as client:
                resp = await client.get("/account-info/v3/details")
                return resp.status_code == 200
        except httpx.HTTPError as e:
            log.warning("hubspot.test_connection failed: %s", e)
            return False

    async def list_customers(
        self, conn: CRMConnection
    ) -> list[NormalizedCustomer]:
        api_key = (conn.credentials or {}).get("api_key", "").strip()
        if not api_key:
            return []
        out: list[NormalizedCustomer] = []
        params = {
            "limit": min(MAX_CONTACTS, 100),
            "properties": ",".join(CONTACT_PROPERTIES),
            "archived": "false",
        }
        try:
            async with httpx.AsyncClient(
                base_url=HUBSPOT_BASE_URL,
                timeout=HTTP_TIMEOUT_SECONDS,
                headers=_auth_headers(api_key),
            ) as client:
                resp = await client.get("/crm/v3/objects/contacts", params=params)
                resp.raise_for_status()
                body = resp.json() or {}
                for item in body.get("results") or []:
                    norm = _contact_to_normalized(item)
                    if norm is not None:
                        out.append(norm)
                    if len(out) >= MAX_CONTACTS:
                        break
        except httpx.HTTPError as e:
            log.exception("hubspot.list_customers failed: %s", e)
            return []
        return out

    async def list_events(
        self,
        conn: CRMConnection,
        customer_external_id: str,
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        api_key = (conn.credentials or {}).get("api_key", "").strip()
        if not api_key:
            return []
        params: dict[str, Any] = {
            "objectType": "contact",
            "objectId": customer_external_id,
            "limit": MAX_EVENTS_PER_CONTACT,
        }
        if since is not None:
            params["occurredAfter"] = since.astimezone(timezone.utc).isoformat()
        out: list[NormalizedEvent] = []
        try:
            async with httpx.AsyncClient(
                base_url=HUBSPOT_BASE_URL,
                timeout=HTTP_TIMEOUT_SECONDS,
                headers=_auth_headers(api_key),
            ) as client:
                resp = await client.get("/events/v3/events", params=params)
                if resp.status_code == 404:
                    # Some HubSpot tiers don't expose the events API. Treat
                    # as "no events" rather than failing the whole import.
                    return []
                resp.raise_for_status()
                body = resp.json() or {}
                for raw in body.get("results") or []:
                    norm = _event_to_normalized(raw, customer_external_id)
                    if norm is not None:
                        out.append(norm)
        except httpx.HTTPError as e:
            log.warning(
                "hubspot.list_events for contact %s failed: %s",
                customer_external_id,
                e,
            )
            return []
        return out

    async def list_products(
        self, conn: CRMConnection
    ) -> list[NormalizedProduct]:
        api_key = (conn.credentials or {}).get("api_key", "").strip()
        if not api_key:
            return []
        params = {
            "limit": min(MAX_PRODUCTS, 100),
            "properties": ",".join(PRODUCT_PROPERTIES),
            "archived": "false",
        }
        try:
            async with httpx.AsyncClient(
                base_url=HUBSPOT_BASE_URL,
                timeout=HTTP_TIMEOUT_SECONDS,
                headers=_auth_headers(api_key),
            ) as client:
                resp = await client.get("/crm/v3/objects/products", params=params)
                if resp.status_code == 404:
                    # Products are a Commerce-Hub object — many portals don't
                    # have it. Empty catalog is the right answer for those.
                    return []
                resp.raise_for_status()
                body = resp.json() or {}
                out: list[NormalizedProduct] = []
                for item in body.get("results") or []:
                    norm = _product_to_normalized(item)
                    if norm is not None:
                        out.append(norm)
                return out
        except httpx.HTTPError as e:
            log.warning("hubspot.list_products failed: %s", e)
            return []
