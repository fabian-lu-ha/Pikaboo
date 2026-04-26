"""Mock CRM provider — deterministic seed data per brand_id.

Generates 30 customers across 6 archetypes plus a 12-product catalog.
Same brand_id always yields the same seed (via ``random.Random(brand_id)``)
so demos are reproducible.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from app.services.crm.providers.base import CRMProvider
from app.services.crm.types import (
    CRMConnection,
    NormalizedCustomer,
    NormalizedEvent,
    NormalizedProduct,
)


# A fixed catalog so personalization can recommend across categories.
PRODUCT_CATALOG: list[dict] = [
    {
        "external_id": "p_apparel_tee",
        "sku": "APP-TEE-001",
        "name": "Studio Logo Tee",
        "description": "Heavyweight cotton crew, embroidered logo at chest.",
        "price_cents": 4800,
        "image_url": "https://picsum.photos/seed/tee/600/600",
        "category": "apparel",
        "tags": ["bestseller", "unisex"],
    },
    {
        "external_id": "p_apparel_hoodie",
        "sku": "APP-HOOD-002",
        "name": "Heritage Hoodie",
        "description": "Brushed-back fleece pullover with kangaroo pocket.",
        "price_cents": 9800,
        "image_url": "https://picsum.photos/seed/hoodie/600/600",
        "category": "apparel",
        "tags": ["winter"],
    },
    {
        "external_id": "p_apparel_cap",
        "sku": "APP-CAP-003",
        "name": "Six-Panel Cap",
        "description": "Unstructured low-profile cap, adjustable strap.",
        "price_cents": 3200,
        "image_url": "https://picsum.photos/seed/cap/600/600",
        "category": "apparel",
        "tags": [],
    },
    {
        "external_id": "p_acc_tote",
        "sku": "ACC-TOTE-101",
        "name": "Canvas Field Tote",
        "description": "12oz canvas tote with reinforced bottom seam.",
        "price_cents": 2800,
        "image_url": "https://picsum.photos/seed/tote/600/600",
        "category": "accessories",
        "tags": ["everyday"],
    },
    {
        "external_id": "p_acc_bottle",
        "sku": "ACC-BOTL-102",
        "name": "Insulated Bottle 750ml",
        "description": "Double-wall stainless steel, 24h cold / 12h hot.",
        "price_cents": 3600,
        "image_url": "https://picsum.photos/seed/bottle/600/600",
        "category": "accessories",
        "tags": [],
    },
    {
        "external_id": "p_acc_pin_set",
        "sku": "ACC-PIN-103",
        "name": "Enamel Pin Trio",
        "description": "Set of three hard-enamel pins.",
        "price_cents": 1800,
        "image_url": "https://picsum.photos/seed/pins/600/600",
        "category": "accessories",
        "tags": ["gift"],
    },
    {
        "external_id": "p_digital_preset_pack",
        "sku": "DIG-PRE-201",
        "name": "Lightroom Preset Pack",
        "description": "12 cinematic Lightroom presets, mobile + desktop.",
        "price_cents": 2900,
        "image_url": "https://picsum.photos/seed/presets/600/600",
        "category": "digital",
        "tags": ["instant"],
    },
    {
        "external_id": "p_digital_workshop",
        "sku": "DIG-WORK-202",
        "name": "Voice & Brand Workshop",
        "description": "90-minute self-paced workshop + worksheets.",
        "price_cents": 7900,
        "image_url": "https://picsum.photos/seed/workshop/600/600",
        "category": "digital",
        "tags": [],
    },
    {
        "external_id": "p_digital_template",
        "sku": "DIG-TPL-203",
        "name": "Notion Brand OS",
        "description": "Notion template with brand voice + content calendar.",
        "price_cents": 4900,
        "image_url": "https://picsum.photos/seed/template/600/600",
        "category": "digital",
        "tags": ["notion"],
    },
    {
        "external_id": "p_print_zine",
        "sku": "PRT-ZINE-301",
        "name": "Issue 01 Zine",
        "description": "32-page riso-printed quarterly zine.",
        "price_cents": 1500,
        "image_url": "https://picsum.photos/seed/zine/600/600",
        "category": "print",
        "tags": ["limited"],
    },
    {
        "external_id": "p_print_poster",
        "sku": "PRT-POST-302",
        "name": "Studio Poster A2",
        "description": "Heavyweight matte poster, signed and numbered.",
        "price_cents": 2400,
        "image_url": "https://picsum.photos/seed/poster/600/600",
        "category": "print",
        "tags": ["limited"],
    },
    {
        "external_id": "p_print_book",
        "sku": "PRT-BOOK-303",
        "name": "Field Notes Hardcover",
        "description": "208 pages, smyth-sewn, dot-grid notebook.",
        "price_cents": 3400,
        "image_url": "https://picsum.photos/seed/book/600/600",
        "category": "print",
        "tags": [],
    },
]


# Per-archetype demographics, tags, and event mix.
ARCHETYPES: list[dict] = [
    {
        "name": "high_value_repeat",
        "label": "high-spend repeat buyer",
        "tags": ["repeat", "high-value", "vip"],
        "purchase_count": (4, 8),
        "open_rate": (0.55, 0.85),
        "events_per_customer": (10, 15),
        "purchase_share": 0.35,
        "click_share": 0.25,
        "open_share": 0.30,
        "view_share": 0.10,
        "support_share": 0.0,
        "signup_days_ago": (180, 540),
        "last_active_days_ago": (1, 14),
    },
    {
        "name": "lapsed_90d",
        "label": "lapsed 90+ days",
        "tags": ["lapsed", "win-back"],
        "purchase_count": (1, 3),
        "open_rate": (0.10, 0.30),
        "events_per_customer": (5, 9),
        "purchase_share": 0.15,
        "click_share": 0.10,
        "open_share": 0.45,
        "view_share": 0.30,
        "support_share": 0.0,
        "signup_days_ago": (240, 720),
        "last_active_days_ago": (95, 200),
    },
    {
        "name": "new_this_month",
        "label": "new this month",
        "tags": ["new", "onboarding"],
        "purchase_count": (0, 2),
        "open_rate": (0.40, 0.70),
        "events_per_customer": (4, 8),
        "purchase_share": 0.20,
        "click_share": 0.20,
        "open_share": 0.30,
        "view_share": 0.30,
        "support_share": 0.0,
        "signup_days_ago": (1, 28),
        "last_active_days_ago": (0, 7),
    },
    {
        "name": "browser_only",
        "label": "browser, no purchase",
        "tags": ["browser", "no-purchase"],
        "purchase_count": (0, 0),
        "open_rate": (0.20, 0.50),
        "events_per_customer": (5, 10),
        "purchase_share": 0.0,
        "click_share": 0.20,
        "open_share": 0.30,
        "view_share": 0.50,
        "support_share": 0.0,
        "signup_days_ago": (30, 200),
        "last_active_days_ago": (2, 30),
    },
    {
        "name": "support_heavy",
        "label": "support-heavy",
        "tags": ["support", "needs-attention"],
        "purchase_count": (1, 4),
        "open_rate": (0.30, 0.55),
        "events_per_customer": (8, 14),
        "purchase_share": 0.15,
        "click_share": 0.10,
        "open_share": 0.20,
        "view_share": 0.20,
        "support_share": 0.35,
        "signup_days_ago": (60, 365),
        "last_active_days_ago": (1, 21),
    },
    {
        "name": "average",
        "label": "average customer",
        "tags": [],
        "purchase_count": (1, 3),
        "open_rate": (0.25, 0.50),
        "events_per_customer": (6, 10),
        "purchase_share": 0.20,
        "click_share": 0.20,
        "open_share": 0.35,
        "view_share": 0.25,
        "support_share": 0.0,
        "signup_days_ago": (60, 420),
        "last_active_days_ago": (3, 45),
    },
]

# Acquisition sources for multi-touch attribution. Weights sum to 1.0.
# Each customer's first-touch is sampled from this distribution; their
# touchpoints[] adds 0-2 later visits with looser source choices.
ACQUISITION_SOURCES: list[dict] = [
    {
        "source": "google_ads",
        "campaign": "ga_summer_sale_2026",
        "utm_source": "google", "utm_medium": "cpc",
        "utm_campaign": "summer-sale",
        "utm_content": "tee-promo", "utm_term": "studio merch",
        "first_touch_url": "/products/studio-tee",
        "referrer": "google.com",
        "weight": 0.30,
    },
    {
        "source": "meta_ads",
        "campaign": "meta_brand_q1_2026",
        "utm_source": "facebook", "utm_medium": "paid_social",
        "utm_campaign": "brand-launch-q1",
        "utm_content": "carousel-1", "utm_term": "",
        "first_touch_url": "/", "referrer": "facebook.com",
        "weight": 0.20,
    },
    {
        "source": "organic_search",
        "campaign": None, "utm_source": "google", "utm_medium": "organic",
        "utm_campaign": "", "utm_content": "", "utm_term": "",
        "first_touch_url": "/blog/voice-and-brand",
        "referrer": "google.com", "weight": 0.20,
    },
    {
        "source": "referral_partner",
        "campaign": "partner_acme_2026",
        "utm_source": "acme", "utm_medium": "referral",
        "utm_campaign": "acme-bundle", "utm_content": "", "utm_term": "",
        "first_touch_url": "/p/acme",
        "referrer": "acme.example.com", "weight": 0.10,
    },
    {
        "source": "newsletter",
        "campaign": "ns_drop03_2026",
        "utm_source": "newsletter", "utm_medium": "email",
        "utm_campaign": "drop-03", "utm_content": "",
        "utm_term": "", "first_touch_url": "/shop",
        "referrer": "", "weight": 0.10,
    },
    {
        "source": "direct",
        "campaign": None, "utm_source": "", "utm_medium": "",
        "utm_campaign": "", "utm_content": "", "utm_term": "",
        "first_touch_url": "/", "referrer": "",
        "weight": 0.10,
    },
]


def _pick_acquisition(rng: random.Random) -> dict:
    pop = [s["source"] for s in ACQUISITION_SOURCES]
    weights = [s["weight"] for s in ACQUISITION_SOURCES]
    pick = rng.choices(pop, weights=weights, k=1)[0]
    return next(s for s in ACQUISITION_SOURCES if s["source"] == pick)


CUSTOMERS_PER_ARCHETYPE = 5

# Realistic name pool — German + US mix.
FIRST_NAMES_DE = [
    "Lena",
    "Jonas",
    "Mia",
    "Leon",
    "Hannah",
    "Felix",
    "Anna",
    "Paul",
    "Emilia",
    "Maximilian",
    "Sophie",
    "Lukas",
]
LAST_NAMES_DE = [
    "Müller",
    "Schmidt",
    "Schneider",
    "Fischer",
    "Weber",
    "Becker",
    "Hoffmann",
    "Wagner",
    "Schulz",
    "Krüger",
]
FIRST_NAMES_US = [
    "Ava",
    "Liam",
    "Olivia",
    "Noah",
    "Emma",
    "Ethan",
    "Sophia",
    "Mason",
    "Isabella",
    "Logan",
    "Mia",
    "Caleb",
]
LAST_NAMES_US = [
    "Garcia",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Miller",
    "Davis",
    "Rodriguez",
    "Wilson",
    "Anderson",
]
CITIES_DE = [
    ("Berlin", "DE"),
    ("Hamburg", "DE"),
    ("Munich", "DE"),
    ("Cologne", "DE"),
    ("Frankfurt", "DE"),
    ("Leipzig", "DE"),
]
CITIES_US = [
    ("New York", "US"),
    ("Brooklyn", "US"),
    ("Los Angeles", "US"),
    ("Austin", "US"),
    ("Portland", "US"),
    ("Chicago", "US"),
]


def _seed_int(brand_id: str) -> int:
    return int(hashlib.sha256(brand_id.encode("utf-8")).hexdigest()[:12], 16)


def _email_for(rng: random.Random, first: str, last: str) -> str:
    domains = ["gmail.com", "hey.com", "outlook.com", "proton.me"]
    suffix = rng.randint(1, 99)
    handle = f"{first.lower()}.{last.lower()}{suffix}"
    return f"{handle}@{rng.choice(domains)}"


def _phone_for(rng: random.Random, country: str) -> str:
    if country == "DE":
        return f"+49 {rng.randint(150, 179)} {rng.randint(1000000, 9999999)}"
    return (
        f"+1 ({rng.randint(200, 989)}) "
        f"{rng.randint(200, 989)}-{rng.randint(1000, 9999)}"
    )


def _pick_event_kind(rng: random.Random, archetype: dict) -> str:
    """Pick an event kind weighted by archetype shares."""
    weights = [
        ("purchase", archetype["purchase_share"]),
        ("email_click", archetype["click_share"]),
        ("email_open", archetype["open_share"]),
        ("page_view", archetype["view_share"]),
        ("support_msg", archetype["support_share"]),
    ]
    population = [k for k, _ in weights]
    cum = [w for _, w in weights]
    return rng.choices(population, weights=cum, k=1)[0]


def _build_customers(brand_id: str) -> list[NormalizedCustomer]:
    rng = random.Random(_seed_int(brand_id))
    customers: list[NormalizedCustomer] = []
    counter = 0

    for archetype in ARCHETYPES:
        for _ in range(CUSTOMERS_PER_ARCHETYPE):
            counter += 1
            use_de = rng.random() < 0.5
            first = rng.choice(FIRST_NAMES_DE if use_de else FIRST_NAMES_US)
            last = rng.choice(LAST_NAMES_DE if use_de else LAST_NAMES_US)
            city, country = rng.choice(CITIES_DE if use_de else CITIES_US)
            signup_days = rng.randint(*archetype["signup_days_ago"])
            signup_at = datetime.now(timezone.utc) - timedelta(
                days=signup_days
            )
            acq = _pick_acquisition(rng)
            # First touch always equals acquisition source. Add 0-2 more
            # touchpoints over time (return visits, newsletter opens) so
            # the journey timeline has more than one dot for most customers.
            tp: list[dict] = [
                {
                    "source": acq["source"],
                    "campaign": acq["campaign"],
                    "at": signup_at.isoformat(),
                    "action": "first_visit",
                }
            ]
            for _ in range(rng.randint(0, 2)):
                later_days = rng.randint(1, max(2, signup_days - 1))
                tp.append(
                    {
                        "source": rng.choice(
                            ["direct", "newsletter", "organic_search"]
                        ),
                        "campaign": None,
                        "at": (
                            datetime.now(timezone.utc)
                            - timedelta(days=later_days)
                        ).isoformat(),
                        "action": "return_visit",
                    }
                )
            customers.append(
                NormalizedCustomer(
                    provider="mock",
                    external_id=f"mock_cust_{counter:03d}",
                    email=_email_for(rng, first, last),
                    name=f"{first} {last}",
                    phone=_phone_for(rng, country),
                    city=city,
                    country=country,
                    attributes={
                        "archetype": archetype["name"],
                        "archetype_label": archetype["label"],
                    },
                    tags=list(archetype["tags"]),
                    signup_at=signup_at,
                    acquisition={
                        "source": acq["source"],
                        "campaign": acq["campaign"],
                        "utm_source": acq["utm_source"],
                        "utm_medium": acq["utm_medium"],
                        "utm_campaign": acq["utm_campaign"],
                        "utm_content": acq["utm_content"],
                        "utm_term": acq["utm_term"],
                        "first_touch_url": acq["first_touch_url"],
                        "referrer": acq["referrer"],
                    },
                    touchpoints=tp,
                )
            )
    return customers


def _build_events_for(
    brand_id: str, customer: NormalizedCustomer
) -> list[NormalizedEvent]:
    archetype_name = (customer.attributes or {}).get("archetype", "average")
    archetype = next(
        (a for a in ARCHETYPES if a["name"] == archetype_name), ARCHETYPES[-1]
    )
    # Per-customer RNG so each customer's history is also deterministic.
    rng = random.Random(
        _seed_int(brand_id + ":" + customer.external_id)
    )
    n = rng.randint(*archetype["events_per_customer"])
    last_active_days = rng.randint(*archetype["last_active_days_ago"])
    span_days = max(7, last_active_days + 30)

    events: list[NormalizedEvent] = []
    for _ in range(n):
        offset = rng.randint(last_active_days, span_days)
        occurred = datetime.now(timezone.utc) - timedelta(
            days=offset,
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        kind = _pick_event_kind(rng, archetype)
        payload: dict = {}
        if kind == "purchase":
            product = rng.choice(PRODUCT_CATALOG)
            payload = {
                "product_id": product["external_id"],
                "product_name": product["name"],
                "amount_cents": product["price_cents"],
                "category": product["category"],
            }
        elif kind in ("email_open", "email_click"):
            subjects = [
                "Drop 03 is live",
                "Behind the scenes — studio reset",
                "A small thank-you, on us",
                "New zine, limited print",
                "Your wishlist is waiting",
            ]
            payload = {"subject": rng.choice(subjects)}
            if kind == "email_click":
                payload["link"] = "/shop/" + rng.choice(
                    [p["external_id"] for p in PRODUCT_CATALOG]
                )
        elif kind == "page_view":
            product = rng.choice(PRODUCT_CATALOG)
            payload = {
                "path": f"/shop/{product['external_id']}",
                "product_id": product["external_id"],
            }
        elif kind == "support_msg":
            payload = {
                "channel": rng.choice(["email", "chat"]),
                "topic": rng.choice(
                    ["sizing", "shipping", "return", "exchange"]
                ),
            }

        events.append(
            NormalizedEvent(
                external_customer_id=customer.external_id,
                kind=kind,
                occurred_at=occurred,
                payload=payload,
            )
        )

    events.sort(key=lambda e: e.occurred_at)
    return events


class MockCRMProvider(CRMProvider):
    """In-memory deterministic CRM. Same brand_id → same data."""

    name = "mock"

    async def test_connection(self, credentials: dict) -> bool:  # noqa: ARG002
        return True

    async def list_customers(
        self, conn: CRMConnection
    ) -> list[NormalizedCustomer]:
        brand_id = (conn.credentials or {}).get("brand_id", "default-brand")
        return _build_customers(brand_id)

    async def list_events(
        self,
        conn: CRMConnection,
        customer_external_id: str,
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        brand_id = (conn.credentials or {}).get("brand_id", "default-brand")
        # Find this customer in the deterministic set, then build events.
        match = next(
            (
                c
                for c in _build_customers(brand_id)
                if c.external_id == customer_external_id
            ),
            None,
        )
        if match is None:
            return []
        events = _build_events_for(brand_id, match)
        if since is not None:
            events = [e for e in events if e.occurred_at >= since]
        return events

    async def list_products(
        self, conn: CRMConnection  # noqa: ARG002
    ) -> list[NormalizedProduct]:
        return [
            NormalizedProduct(
                provider="mock",
                external_id=p["external_id"],
                name=p["name"],
                sku=p.get("sku"),
                description=p.get("description"),
                price_cents=int(p.get("price_cents") or 0),
                image_url=p.get("image_url"),
                category=p.get("category"),
                tags=list(p.get("tags") or []),
            )
            for p in PRODUCT_CATALOG
        ]
