# Personalized Email Campaigns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing audience system with multi-touch attribution, shop-event automation, competitor-aware product comparisons, and HTML email rendering — turning the scaffolded "personalize per customer" pipeline into the full hero demo (1:1 emails that know the customer's acquisition source, fire automatically on shop events, pitch against competitor offerings, and render as branded HTML).

**Architecture:** Pure event-first additions to the existing `services/audience/`, `services/crm/`, and `services/pii/` stack. No new architectural pattern — only new fields on `NormalizedCustomer`/`Customer`, new event kinds, new endpoint(s), one extractor service in `services/enrichment/`, and one renderer module. Spec: `docs/superpowers/specs/2026-04-26-personalized-email-campaigns-design.md`.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pyee (event bus), Gemini (existing `services/llm/client.chat_json`), Playwright (existing `services/enrichment/browser`). Frontend: React + TypeScript, Zustand, mitt event bus, Tailwind.

**Critical context — what already exists (do NOT rebuild):**
- `backend/app/db/models.py` — `Customer`, `CustomerEvent`, `Segment`, `Product`, `EmailSend`, `Brand`, `Competitor` all present.
- `backend/app/api/audience.py` — full router: `/connect_crm`, `/import`, `/customers`, `/products`, `/segments/propose`, `/segments`, `/personalize`, `/dispatch`.
- `backend/app/services/audience/personalization.py` — `personalize_for_customer` and `personalize_for_segment`, both with PII-redact-then-rehydrate flow and event emission.
- `backend/app/services/audience/segmentation.py` — `propose_segments` with PII-free per-customer summaries → Gemini → 3-6 segments.
- `backend/app/services/pii/` — `Redactor` Protocol + `GoogleDLPRedactor` (Cloud DLP / Gemini fallback) + `RegexRedactor`. Selected via `AUDIENCE_PII_PROVIDER=google` env var.
- `backend/app/services/crm/providers/mock.py` — 30 deterministic customers across 6 archetypes + 12-product catalog. Seeded by `brand_id`.
- `backend/app/events/types.py` — 10 `audience.*` event types declared.
- `frontend/src/stores/audienceStore.ts` — Zustand store with full personalize/dispatch/import/segment flows, event-bus wired.
- `frontend/src/lib/audience.ts` — `Customer`, `Segment`, `Product`, `PersonalizedEmail` types + helpers.
- `frontend/src/components/audience/` — 13 components: `AudiencePane`, `CustomerList`, `SegmentList`, `ProductGrid`, `PersonalizeBlock`, `ConnectCRMModal`, `ProposedSegmentsModal`, `SegmentDrawer`, `CustomerDrawer`, `AudienceActivityFeed`, `PIIShield`, `CustomerRow`.

**Spec ↔ reality name map** (the spec used generic names; this plan uses the real ones):

| Spec name | Real name | Where |
|---|---|---|
| `Contact` | `Customer` | `db/models.py` |
| `ContactEvent` | `CustomerEvent` | `db/models.py` |
| `EmailMessage` | `EmailSend` | `db/models.py` |
| `crm.contact_selected` | `audience.personalizing` | `events/types.py` |
| `personalize.draft_generated` | `audience.personalized` | `events/types.py` |
| `email.sent` | `audience.email_dispatched` | `events/types.py` |

**Verification model:** No pytest yet in this repo. Each task ends in a smoke test (`curl` + observed response, observed event, or observed UI behavior) and a commit. A separate "set up pytest" task is **out of scope** for this plan.

**Coordination:** A peer agent (`backend-videogen`) is also editing `backend/app/events/types.py` and `backend/app/main.py`. Append-only: never modify lines you didn't write. Pull latest before each commit. Post a W2W heads-up before editing those two files (`post_message(topic="touching events/types.py + main.py for audience extensions", priority="heads_up", files=[...])`).

---

## Phase 1 — Multi-touch attribution

The current `Customer.attributes` JSON only carries `archetype` and `archetype_label`. The user wants emails to weigh "where the customer came from" (Google Ads campaign, Meta ad, organic blog post, referral). Add structured `acquisition` + `touchpoints[]` fields, seed them from the mock provider per archetype, surface them in the personalization brief, and render badges/timeline in the UI.

### Task 1.1 — Extend `NormalizedCustomer` with attribution fields

**Files:**
- Modify: `backend/app/services/crm/types.py`

- [ ] **Step 1: Add `acquisition` and `touchpoints` to `NormalizedCustomer`**

```python
# backend/app/services/crm/types.py — replace NormalizedCustomer

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
    acquisition: dict = field(default_factory=dict)
    # acquisition: { source, campaign, utm_source, utm_medium,
    #                utm_campaign, utm_content, utm_term,
    #                first_touch_url, referrer }
    touchpoints: list[dict] = field(default_factory=list)
    # touchpoints: [ { source, campaign, at, action } ]
```

- [ ] **Step 2: Verify Python imports still resolve**

Run: `python -c "from app.services.crm.types import NormalizedCustomer; c = NormalizedCustomer(provider='x', external_id='y', email='z'); print(c.acquisition, c.touchpoints)"` from `backend/`.
Expected: `{} []`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/crm/types.py
git commit -m "feat(audience): add acquisition + touchpoints to NormalizedCustomer"
```

### Task 1.2 — Seed attribution data in the mock provider

**Files:**
- Modify: `backend/app/services/crm/providers/mock.py`

- [ ] **Step 1: Add an `ACQUISITION_SOURCES` table near `ARCHETYPES`**

```python
# After ARCHETYPES, before CUSTOMERS_PER_ARCHETYPE
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
```

- [ ] **Step 2: Inject `acquisition` and a 1–3-touchpoint `touchpoints[]` into each customer in `_build_customers`**

Modify `_build_customers` — replace the `customers.append(NormalizedCustomer(...))` block with:

```python
            acq = _pick_acquisition(rng)
            # First touch always equals acquisition source. Add 1–2 more
            # touchpoints over time (organic re-visits, newsletter opens).
            tp: list[dict] = [
                {
                    "source": acq["source"],
                    "campaign": acq["campaign"],
                    "at": signup_at.isoformat(),
                    "action": "first_visit",
                }
            ]
            extra_touches = rng.randint(0, 2)
            for _ in range(extra_touches):
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
```

- [ ] **Step 3: Smoke-verify deterministic seeding**

From `backend/`:
```bash
python -c "
import asyncio
from app.services.crm.providers.mock import MockCRMProvider
from app.services.crm.types import CRMConnection
async def main():
    p = MockCRMProvider()
    c = await p.list_customers(CRMConnection(provider='mock', credentials={'brand_id': 'demo-brand'}))
    print('count', len(c))
    print('first', c[0].acquisition, c[0].touchpoints[:2])
asyncio.run(main())
"
```
Expected: `count 30` and a populated acquisition dict + 1-3-element touchpoints list. Re-running yields the SAME first customer's acquisition (deterministic).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/crm/providers/mock.py
git commit -m "feat(crm-mock): seed acquisition + touchpoints per customer"
```

### Task 1.3 — Persist attribution through `sync.py` into `Customer.attributes`

The `Customer` table has no dedicated columns, but its `attributes` JSON is the right home. Stash `acquisition` and `touchpoints` under known keys.

**Files:**
- Modify: `backend/app/services/crm/sync.py:40-75` (the `_persist_customer` function)

- [ ] **Step 1: Update `_persist_customer` to write attribution into `attributes`**

```python
def _persist_customer(
    db: Session, brand_id: str, c: NormalizedCustomer
) -> models.Customer:
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
```

- [ ] **Step 2: Smoke test — re-import a brand, query a customer, observe acquisition in attributes**

Backend running. Pick or create a brand_id `demo` then:
```bash
curl -X POST http://localhost:8000/api/audience/connect_crm \
  -H "content-type: application/json" \
  -d '{"brand_id":"demo","provider":"mock","credentials":{}}'
curl -X POST http://localhost:8000/api/audience/import \
  -H "content-type: application/json" \
  -d '{"brand_id":"demo","provider":"mock"}'
curl "http://localhost:8000/api/audience/customers?brand_id=demo&limit=1" | python -m json.tool
```
Expected: `attributes.acquisition.source` is non-empty (`"google_ads"`, `"organic_search"`, etc.) and `attributes.touchpoints` is a non-empty list.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/crm/sync.py
git commit -m "feat(crm-sync): persist acquisition + touchpoints into customer attributes"
```

### Task 1.4 — Inject attribution into the personalization brief

The LLM should *say things* like *"Sarah came in via the Black Friday Google ad on Feb 14, then bounced between newsletter clicks before today's session."* Append a short acquisition narrative to the brief in `personalize_for_customer`.

**Files:**
- Modify: `backend/app/services/audience/personalization.py:128-136` (the `brief = …` block)

- [ ] **Step 1: Add a helper that turns acquisition + touchpoints into a one-paragraph narrative**

Insert near the top of `personalization.py`, after `_entity_summary`:

```python
def _attribution_narrative(customer: models.Customer) -> str:
    attrs = customer.attributes or {}
    acq = attrs.get("acquisition") or {}
    tps = attrs.get("touchpoints") or []
    if not acq and not tps:
        return "Acquisition: (unknown)"
    parts: list[str] = []
    src = acq.get("source") or "unknown"
    camp = acq.get("campaign") or ""
    first_url = acq.get("first_touch_url") or ""
    if src and camp:
        parts.append(f"first-touch: {src} — {camp}")
    elif src:
        parts.append(f"first-touch: {src}")
    if first_url:
        parts.append(f"landed on {first_url}")
    if tps:
        later = [
            f"{t.get('source','?')} ({t.get('action','?')})"
            for t in tps[1:4]
        ]
        if later:
            parts.append("then: " + ", ".join(later))
    return "Acquisition: " + " | ".join(parts)
```

- [ ] **Step 2: Splice the narrative into the brief**

In `personalize_for_customer`, change the `brief = (` block to include the narrative line right after Tags:

```python
    brief = (
        f"Customer name: {customer.name or '(unknown)'}\n"
        f"Email: {customer.email}\n"
        f"Phone: {customer.phone or '(none)'}\n"
        f"City: {customer.city or '(unknown)'}, {customer.country or ''}\n"
        f"Tags: {', '.join(customer.tags or []) or '(none)'}\n"
        f"{_attribution_narrative(customer)}\n"
        f"Total spend: ${(customer.total_spend_cents or 0) / 100:.2f}\n"
        "Recent activity:\n" + ("\n".join(activity_lines) or "(no activity)")
    )
```

- [ ] **Step 3: Smoke test — personalize for one customer, observe acquisition reference in body**

```bash
# pick any customer_id from the demo brand
CID=$(curl -s "http://localhost:8000/api/audience/customers?brand_id=demo&limit=1" \
  | python -c "import sys,json;print(json.load(sys.stdin)['customers'][0]['id'])")
curl -X POST http://localhost:8000/api/audience/personalize \
  -H "content-type: application/json" \
  -d "{\"brand_id\":\"demo\",\"target_kind\":\"customer\",\"target_id\":\"$CID\"}" \
  | python -m json.tool
```
Expected: `body` contains a phrase referencing the acquisition source/campaign in at least 2 of 3 runs (LLM is non-deterministic; if 0/3 runs reference it, tighten the system prompt by adding an explicit instruction to weave acquisition into the email).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/audience/personalization.py
git commit -m "feat(personalize): include acquisition narrative in customer brief"
```

### Task 1.5 — Surface acquisition in the customer serializer

The `/api/audience/customers*` responses don't yet expose attribution explicitly — it's hidden inside `attributes`. Frontend will want a typed shape.

**Files:**
- Modify: `backend/app/api/audience.py:117-135` (the `_serialize_customer` function)

- [ ] **Step 1: Add `acquisition` and `touchpoints` to the serialized output**

```python
def _serialize_customer(c: models.Customer, recent_events: list[dict]) -> dict:
    attrs = c.attributes or {}
    return {
        "id": c.id,
        "provider": c.provider,
        "external_id": c.external_id,
        "email": c.email,
        "name": c.name,
        "phone": c.phone,
        "city": c.city,
        "country": c.country,
        "tags": list(c.tags or []),
        "attributes": attrs,
        "acquisition": dict(attrs.get("acquisition") or {}),
        "touchpoints": list(attrs.get("touchpoints") or []),
        "signup_at": c.signup_at.isoformat() if c.signup_at else None,
        "last_active_at": (
            c.last_active_at.isoformat() if c.last_active_at else None
        ),
        "total_spend_cents": int(c.total_spend_cents or 0),
        "recent_events": recent_events,
    }
```

- [ ] **Step 2: Smoke test**

```bash
curl -s "http://localhost:8000/api/audience/customers?brand_id=demo&limit=1" \
  | python -c "import sys,json;c=json.load(sys.stdin)['customers'][0];print('acq',c['acquisition']);print('tps',len(c['touchpoints']))"
```
Expected: non-empty acquisition dict + touchpoints length ≥ 1.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/audience.py
git commit -m "feat(audience-api): expose acquisition + touchpoints on customer responses"
```

### Task 1.6 — Frontend: extend Customer type + acquisition badge

**Files:**
- Modify: `frontend/src/lib/audience.ts`
- Modify: `frontend/src/components/audience/CustomerRow.tsx`

- [ ] **Step 1: Extend `Customer` type with `acquisition` + `touchpoints`**

In `frontend/src/lib/audience.ts`, replace the `Customer` type and add two new types:

```typescript
export type Acquisition = {
  source: string
  campaign: string | null
  utm_source: string
  utm_medium: string
  utm_campaign: string
  utm_content: string
  utm_term: string
  first_touch_url: string
  referrer: string
}

export type Touchpoint = {
  source: string
  campaign: string | null
  at: string
  action: string
}

export type Customer = {
  id: string
  brand_id: string
  provider: string
  external_id: string
  email: string
  name: string | null
  phone: string | null
  city: string | null
  country: string | null
  attributes: Record<string, unknown>
  acquisition: Partial<Acquisition>
  touchpoints: Touchpoint[]
  tags: string[]
  signup_at: string | null
  last_active_at: string | null
  total_spend_cents: number
  recent_events?: CustomerEvent[]
}

export const SOURCE_LABELS: Record<string, string> = {
  google_ads: 'Google Ads',
  meta_ads: 'Meta Ads',
  organic_search: 'Organic',
  referral_partner: 'Referral',
  newsletter: 'Newsletter',
  direct: 'Direct',
}

export function acquisitionBadge(acq: Partial<Acquisition>): string {
  const src = SOURCE_LABELS[acq.source ?? ''] ?? acq.source ?? 'Direct'
  if (acq.campaign) return `${src} · ${acq.campaign}`
  return src
}
```

- [ ] **Step 2: Render the badge in `CustomerRow.tsx`**

Open `frontend/src/components/audience/CustomerRow.tsx`. After the existing tag row (or in a clearly visible meta line), render:

```tsx
import { acquisitionBadge } from '../../lib/audience'

// inside the row JSX, near tags:
{customer.acquisition?.source && (
  <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
    {acquisitionBadge(customer.acquisition)}
  </span>
)}
```

If `CustomerRow.tsx` doesn't take `customer` directly, adapt to its prop shape — render the badge on the same line as tags, same styling.

- [ ] **Step 3: Smoke test in browser**

`pnpm dev` (or `npm run dev`) in `frontend/`. Open the audience pane. Each customer row shows a badge like `Google Ads · ga_summer_sale_2026` or `Organic` or `Direct`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/audience.ts frontend/src/components/audience/CustomerRow.tsx
git commit -m "feat(audience-ui): show acquisition badge on customer rows"
```

### Task 1.7 — Frontend: attribution timeline in `CustomerDrawer`

**Files:**
- Modify: `frontend/src/components/audience/CustomerDrawer.tsx`

- [ ] **Step 1: Add a touchpoints section to the drawer body**

Find the section where existing customer detail (events list, spend, etc.) is rendered. Insert a new block:

```tsx
import { SOURCE_LABELS, type Touchpoint } from '../../lib/audience'

function TouchpointTimeline({ tps }: { tps: Touchpoint[] }) {
  if (!tps?.length) return null
  return (
    <section className="mt-4 border-t border-zinc-800 pt-4">
      <h4 className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
        Acquisition journey
      </h4>
      <ol className="space-y-2">
        {tps.map((t, i) => (
          <li key={`${t.at}-${i}`} className="flex items-start gap-3 text-sm">
            <span className="w-2 h-2 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
            <div>
              <div className="text-zinc-200">
                {SOURCE_LABELS[t.source] ?? t.source}
                {t.campaign ? ` · ${t.campaign}` : ''}
              </div>
              <div className="text-xs text-zinc-500">
                {t.action} — {new Date(t.at).toLocaleDateString()}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
```

Render `<TouchpointTimeline tps={customer.touchpoints ?? []} />` inside the drawer's content panel, ideally above or beside the events list.

- [ ] **Step 2: Smoke test**

Open the audience pane → click a customer → drawer opens → shows journey with at least the first-touch dot + the source label.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/audience/CustomerDrawer.tsx
git commit -m "feat(audience-ui): show acquisition journey timeline in customer drawer"
```

---

## Phase 2 — Shop-event automation

The user wants emails to fire automatically on shop events (`cart_abandoned`, `subscription_lapsed`) and to factor those into the personalization. The existing event kinds set is `purchase | email_open | email_click | page_view | support_msg`. Add the two new kinds, a manual trigger endpoint for the demo, and a bus listener that auto-runs `personalize_for_customer` and persists the result for preview (no auto-send).

### Task 2.1 — Add new event kinds + `audience.shop_event_triggered` event type

**Files:**
- Modify: `backend/app/services/crm/types.py:27-32` (the `NormalizedEvent` docstring/comment)
- Modify: `backend/app/events/types.py` (append-only)
- Modify: `frontend/src/lib/audience.ts` (extend `CustomerEventKind`)

- [ ] **Step 1: Update `NormalizedEvent` kind comment**

```python
@dataclass
class NormalizedEvent:
    external_customer_id: str
    kind: str
    # email_open | email_click | purchase | page_view | support_msg |
    # cart_abandoned | subscription_lapsed
    occurred_at: datetime
    payload: dict = field(default_factory=dict)
```

- [ ] **Step 2: Append `AUDIENCE_SHOP_EVENT` event type**

In `backend/app/events/types.py`, **before the `KNOWN_EVENTS` tuple**, append (after the existing `AUDIENCE_EMAIL_DISPATCHED` line):

```python
    AUDIENCE_SHOP_EVENT_TRIGGERED = "audience.shop_event_triggered"
    AUDIENCE_SHOP_AUTO_PERSONALIZED = "audience.shop_auto_personalized"
```

(Append-only — verify peer agent hasn't moved that section. If conflict, rebase first.)

- [ ] **Step 3: Extend frontend `CustomerEventKind`**

In `frontend/src/lib/audience.ts`:

```typescript
export type CustomerEventKind =
  | 'email_open'
  | 'email_click'
  | 'purchase'
  | 'page_view'
  | 'support_msg'
  | 'cart_abandoned'
  | 'subscription_lapsed'

export const EVENT_GLYPHS: Record<CustomerEventKind, string> = {
  email_open: '✉',
  email_click: '↗',
  purchase: '◆',
  page_view: '◐',
  support_msg: '◇',
  cart_abandoned: '⊗',
  subscription_lapsed: '↧',
}

export const EVENT_LABELS: Record<CustomerEventKind, string> = {
  email_open: 'opened email',
  email_click: 'clicked email',
  purchase: 'purchased',
  page_view: 'viewed page',
  support_msg: 'support message',
  cart_abandoned: 'abandoned cart',
  subscription_lapsed: 'subscription lapsed',
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/crm/types.py backend/app/events/types.py frontend/src/lib/audience.ts
git commit -m "feat(audience): add cart_abandoned + subscription_lapsed event kinds"
```

### Task 2.2 — Shop trigger endpoint

A demo-friendly POST that records a `CustomerEvent` of the given kind and emits the trigger event. The auto-personalize listener (Task 2.3) handles the rest.

**Files:**
- Create: `backend/app/services/audience/shop_triggers.py`
- Modify: `backend/app/api/audience.py` (add POST `/shop_trigger`)

- [ ] **Step 1: Write `shop_triggers.py`**

```python
"""Shop-event simulator. Records a CustomerEvent of one of the shop kinds
and emits ``audience.shop_event_triggered`` for downstream auto-personalize."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.db import models
from app.events.bus import bus
from app.events.types import Events

log = logging.getLogger(__name__)

ShopEventKind = Literal["cart_abandoned", "subscription_lapsed"]


def fire_shop_event(
    db: Session,
    brand_id: str,
    customer_id: str,
    kind: ShopEventKind,
    payload: dict,
) -> models.CustomerEvent:
    customer = db.get(models.Customer, customer_id)
    if customer is None or customer.brand_id != brand_id:
        raise ValueError(f"customer {customer_id} not found for brand")

    now = datetime.now(timezone.utc)
    row = models.CustomerEvent(
        brand_id=brand_id,
        customer_id=customer_id,
        kind=kind,
        occurred_at=now,
        payload=payload or {},
    )
    db.add(row)
    customer.last_active_at = now
    db.commit()
    db.refresh(row)

    bus.emit(
        Events.AUDIENCE_SHOP_EVENT_TRIGGERED,
        {
            "brand_id": brand_id,
            "customer_id": customer_id,
            "kind": kind,
            "event_id": row.id,
            "payload": payload or {},
        },
    )
    log.info("shop trigger %s for %s", kind, customer_id)
    return row
```

- [ ] **Step 2: Add the endpoint to `audience.py`**

Append at the bottom of `backend/app/api/audience.py`:

```python
from app.services.audience.shop_triggers import fire_shop_event


class ShopTriggerIn(BaseModel):
    brand_id: str
    customer_id: str
    kind: Literal["cart_abandoned", "subscription_lapsed"]
    payload: dict = {}


@router.post("/shop_trigger")
def shop_trigger(
    body: ShopTriggerIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    try:
        row = fire_shop_event(
            db, body.brand_id, body.customer_id, body.kind, body.payload
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "ok": True,
        "event": {
            "id": row.id,
            "kind": row.kind,
            "occurred_at": row.occurred_at.isoformat(),
            "payload": row.payload or {},
        },
    }
```

- [ ] **Step 3: Smoke test**

```bash
CID=$(curl -s "http://localhost:8000/api/audience/customers?brand_id=demo&limit=1" \
  | python -c "import sys,json;print(json.load(sys.stdin)['customers'][0]['id'])")
curl -X POST http://localhost:8000/api/audience/shop_trigger \
  -H "content-type: application/json" \
  -d "{\"brand_id\":\"demo\",\"customer_id\":\"$CID\",\"kind\":\"cart_abandoned\",\"payload\":{\"value_cents\":7900,\"product_ids\":[\"p_apparel_tee\"]}}"
# observe event in SSE stream:
curl -N http://localhost:8000/api/events/stream
```
Expected: response is `{"ok": true, "event": {...}}` and the SSE stream emits `audience.shop_event_triggered` within ~100ms.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/audience/shop_triggers.py backend/app/api/audience.py
git commit -m "feat(audience): shop_trigger endpoint for cart_abandoned + subscription_lapsed"
```

### Task 2.3 — Auto-personalize listener for shop events

When a shop event fires, automatically run `personalize_for_customer` and emit a `audience.shop_auto_personalized` event with the result so the frontend can render it in a "pending sends" feed.

**Files:**
- Modify: `backend/app/services/audience/__init__.py` (add a listener registration)
- Modify: `backend/app/services/audience/shop_triggers.py` (add the listener function)

- [ ] **Step 1: Add the listener to `shop_triggers.py`**

Append to the file:

```python
import asyncio

from app.db.session import SessionLocal
from app.services.audience.personalization import personalize_for_customer


async def _on_shop_event(payload: dict) -> None:
    brand_id = payload.get("brand_id")
    customer_id = payload.get("customer_id")
    kind = payload.get("kind")
    if not brand_id or not customer_id or not kind:
        return

    user_prompt = (
        f"Trigger: {kind}. The customer just had this shop event — write the "
        f"email AS A RESPONSE to it (e.g. for cart_abandoned: encourage the "
        f"completion with helpful framing; for subscription_lapsed: a "
        f"win-back with a small incentive)."
    )

    db = SessionLocal()
    try:
        result = await personalize_for_customer(
            db, brand_id, customer_id, user_prompt
        )
    except Exception:
        log.exception("audience: shop auto-personalize failed")
        return
    finally:
        db.close()

    bus.emit(
        Events.AUDIENCE_SHOP_AUTO_PERSONALIZED,
        {
            "brand_id": brand_id,
            "customer_id": customer_id,
            "trigger_kind": kind,
            "subject_preview": (result.get("subject") or "")[:80],
            "recommended_product_ids": result.get(
                "recommended_product_ids", []
            ),
        },
    )


def register() -> None:
    bus.on(Events.AUDIENCE_SHOP_EVENT_TRIGGERED, _on_shop_event)
```

(`SessionLocal` may be named differently. If `db/session.py` exposes a different factory, adapt the import — search `def get_db` to find it.)

- [ ] **Step 2: Register the listener at app start**

In `backend/app/services/audience/__init__.py`, ensure `register()` is called on import — equivalent to the existing pattern used for `agent.loop`. The simplest form:

```python
from app.services.audience import shop_triggers as _shop_triggers

_shop_triggers.register()
```

If the existing `__init__.py` is empty or different, follow the same pattern as `app/services/agent/__init__.py`. Make sure `app.services.audience` is imported during startup — verify `main.py` already triggers this via `audience` router import; if not, add `from app.services import audience as _audience  # noqa: F401` to `main.py` near the agent_loop import.

- [ ] **Step 3: Smoke test the auto-personalize**

```bash
# Fire trigger; expect both shop_event_triggered AND shop_auto_personalized
# events on the SSE stream within a few seconds:
curl -N http://localhost:8000/api/events/stream &
sleep 1
curl -X POST http://localhost:8000/api/audience/shop_trigger \
  -H "content-type: application/json" \
  -d "{\"brand_id\":\"demo\",\"customer_id\":\"$CID\",\"kind\":\"cart_abandoned\",\"payload\":{\"value_cents\":7900}}"
```
Expected: Within ~5–10s (Gemini latency), the stream emits `audience.shop_auto_personalized` with a `subject_preview`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/audience/shop_triggers.py backend/app/services/audience/__init__.py backend/app/main.py
git commit -m "feat(audience): auto-personalize on shop events via bus listener"
```

### Task 2.4 — Frontend: ShopFeed component

Render a feed showing recent shop events + the auto-generated email previews. Add a "Fire test trigger" control for the demo.

**Files:**
- Create: `frontend/src/components/audience/ShopFeed.tsx`
- Modify: `frontend/src/stores/audienceStore.ts` (handle the two new events)
- Modify: `frontend/src/components/audience/AudiencePane.tsx` (wire ShopFeed in)

- [ ] **Step 1: Extend `audienceStore.ts` with shop-event state**

Append to the `State` type:

```typescript
type ShopFeedEntry = {
  id: number
  at: string
  brand_id: string
  customer_id: string
  kind: 'cart_abandoned' | 'subscription_lapsed'
  payload: Record<string, unknown>
  // populated when shop_auto_personalized arrives
  subject_preview?: string
  recommended_product_ids?: string[]
}

// add to State:
  shopFeed: ShopFeedEntry[]

// in initial:
  shopFeed: [],
```

Append to actions:
```typescript
  fireShopTrigger: (
    brand_id: string,
    customer_id: string,
    kind: 'cart_abandoned' | 'subscription_lapsed',
    payload?: Record<string, unknown>,
  ) => Promise<void>
```

Implement:
```typescript
  fireShopTrigger: async (brand_id, customer_id, kind, payload = {}) => {
    try {
      await safeJson<{ ok: boolean }>(
        await fetch('/api/audience/shop_trigger', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ brand_id, customer_id, kind, payload }),
        }),
      )
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'shop_trigger failed' })
    }
  },
```

Add bus listeners at module bottom:
```typescript
let shopCounter = 0
bus.on('audience.shop_event_triggered', (p) => {
  useAudienceStore.setState((s) => ({
    shopFeed: [
      {
        id: shopCounter++,
        at: new Date().toLocaleTimeString(),
        brand_id: p.brand_id,
        customer_id: p.customer_id,
        kind: p.kind,
        payload: p.payload ?? {},
      },
      ...s.shopFeed,
    ].slice(0, 25),
  }))
})

bus.on('audience.shop_auto_personalized', (p) => {
  useAudienceStore.setState((s) => ({
    shopFeed: s.shopFeed.map((e) =>
      e.customer_id === p.customer_id && !e.subject_preview
        ? {
            ...e,
            subject_preview: p.subject_preview,
            recommended_product_ids: p.recommended_product_ids,
          }
        : e,
    ),
  }))
})
```

(Also update the bus type definitions in `frontend/src/events/bus.ts` so TypeScript accepts the two new event names — append to the `AgentEvents` map.)

- [ ] **Step 2: Create `ShopFeed.tsx`**

```tsx
import { useAudienceStore } from '../../stores/audienceStore'

export function ShopFeed({ brandId }: { brandId: string }) {
  const feed = useAudienceStore((s) => s.shopFeed)
  const customers = useAudienceStore((s) => s.customers)
  const fire = useAudienceStore((s) => s.fireShopTrigger)

  return (
    <section className="border-t border-zinc-800 pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">Shop feed</h3>
        <button
          className="text-xs px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600"
          onClick={() => {
            const c = customers[0]
            if (!c) return
            void fire(brandId, c.id, 'cart_abandoned', {
              value_cents: 7900,
              product_ids: ['p_apparel_tee'],
            })
          }}
        >
          Fire test cart_abandoned
        </button>
      </div>
      {feed.length === 0 && (
        <div className="text-xs text-zinc-500">No shop events yet.</div>
      )}
      <ul className="space-y-2">
        {feed.map((e) => (
          <li
            key={e.id}
            className="text-xs bg-zinc-900 border border-zinc-800 rounded p-2"
          >
            <div className="text-zinc-300">
              <span className="text-zinc-500">{e.at}</span>{' '}
              <span className="font-mono">{e.kind}</span> · {e.customer_id.slice(-6)}
            </div>
            {e.subject_preview ? (
              <div className="mt-1 text-emerald-300">
                ✓ Email drafted: "{e.subject_preview}"
              </div>
            ) : (
              <div className="mt-1 text-zinc-500 italic">drafting…</div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
```

- [ ] **Step 3: Mount `<ShopFeed brandId={brandId} />` in `AudiencePane.tsx`**

Open `frontend/src/components/audience/AudiencePane.tsx`, find a sensible location (sidebar or below the activity feed), import and render `<ShopFeed brandId={brandId} />`.

- [ ] **Step 4: Smoke test in browser**

Click "Fire test cart_abandoned". Within seconds the entry shows the drafted-email subject preview.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/audience/ShopFeed.tsx frontend/src/stores/audienceStore.ts frontend/src/events/bus.ts frontend/src/components/audience/AudiencePane.tsx
git commit -m "feat(audience-ui): ShopFeed with manual trigger + live auto-draft preview"
```

---

## Phase 3 — Competitor product extraction

Onboarding already enriches `Competitor` rows with logo + pattern_library. Extend this to also extract a small product catalog per competitor (name + price + url + description), cache it on `Competitor.pattern_library["products"]`, and inject the catalog into the personalization brief so the LLM can write competitive-comparison lines.

### Task 3.1 — Add `competitor_products.py` extractor

**Files:**
- Create: `backend/app/services/enrichment/competitor_products.py`

- [ ] **Step 1: Write the extractor**

```python
"""Extract a small product catalog from a competitor's marketing site.

Strategy: load the competitor's homepage with the existing Playwright
browser, then ask Gemini to extract up to 6 visible products with
name, price (best-effort), description, and url. Caches result on
``Competitor.pattern_library['products']`` via the caller — this
module is pure extraction.

Fail-soft: returns ``[]`` on any error. The caller MUST treat absent
competitor products as "no comparison line"; nothing should hard-fail
because a competitor site has anti-scraping measures or a non-standard
layout.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.enrichment import browser as pw_browser
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


PRODUCT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "minItems": 0,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "price_text": {"type": "string"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["name", "price_text", "description", "url"],
            },
        }
    },
    "required": ["products"],
}


SYSTEM = (
    "You extract a small product catalog from a competitor's marketing "
    "page. Return up to 6 products that are clearly for sale (not navigation "
    "links). For each product give the visible name, the price as it "
    "appears on the page (e.g. '$79', '€129/mo', 'Free'), a one-sentence "
    "description, and the absolute URL if visible. If no products are "
    "obvious, return an empty array. Never invent products."
)


async def extract(competitor_url: str) -> list[dict[str, Any]]:
    if not competitor_url:
        return []
    try:
        page = await pw_browser.new_page()
        await page.goto(competitor_url, timeout=15000, wait_until="domcontentloaded")
        # cap textual content the LLM sees to keep cost bounded
        body_text = await page.evaluate(
            "() => document.body.innerText.slice(0, 6000)"
        )
        await page.close()
    except Exception as e:  # noqa: BLE001
        log.warning("competitor_products: page load failed for %s: %s",
                    competitor_url, e)
        return []

    try:
        result = await chat_json(
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Competitor URL: {competitor_url}\n\nVisible page "
                        f"text (truncated):\n{body_text}"
                    ),
                },
            ],
            schema=PRODUCT_SCHEMA,
        )
    except Exception:  # noqa: BLE001
        log.warning("competitor_products: gemini extraction failed",
                    exc_info=True)
        return []

    products = result.get("products", []) or []
    out: list[dict[str, Any]] = []
    for p in products[:6]:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "price_text": (p.get("price_text") or "").strip(),
                "description": (p.get("description") or "").strip(),
                "url": (p.get("url") or "").strip(),
            }
        )
    return out
```

- [ ] **Step 2: Smoke test**

From `backend/`:
```bash
python -c "
import asyncio
from app.services.enrichment import browser as pw
from app.services.enrichment.competitor_products import extract
async def main():
    await pw.start()
    try:
        out = await extract('https://example.com')
        print('count', len(out))
        for p in out: print(' -', p['name'], p['price_text'])
    finally:
        await pw.stop()
asyncio.run(main())
"
```
Expected: `count 0` (example.com has no products) without exception.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/enrichment/competitor_products.py
git commit -m "feat(enrichment): extract competitor product catalog from URL"
```

### Task 3.2 — Wire extractor into onboarding orchestrator

**Files:**
- Modify: `backend/app/services/onboarding/orchestrator.py` (add a call after `competitor_enriched`)
- Modify: `backend/app/events/types.py` (append two new event types)

- [ ] **Step 1: Append event types**

In `backend/app/events/types.py`, after `AUDIENCE_SHOP_AUTO_PERSONALIZED`:

```python
    ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTING = "onboarding.competitor_products_extracting"
    ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTED = "onboarding.competitor_products_extracted"
```

- [ ] **Step 2: Add the wiring in `onboarding/orchestrator.py`**

Find the place where `Events.ONBOARDING_COMPETITOR_ENRICHED` is emitted. Just after that block (typically inside the per-competitor enrichment loop), call the extractor and persist:

```python
from app.services.enrichment.competitor_products import (
    extract as extract_competitor_products,
)

# inside the per-competitor block, AFTER the existing enrichment writes
# competitor.logo_url / pattern_library:
if competitor.url:
    bus.emit(
        Events.ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTING,
        {"brand_id": brand.id, "competitor_id": competitor.id, "url": competitor.url},
    )
    products = await extract_competitor_products(competitor.url)
    pattern_library = dict(competitor.pattern_library or {})
    pattern_library["products"] = products
    competitor.pattern_library = pattern_library
    db.add(competitor)
    db.commit()
    bus.emit(
        Events.ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTED,
        {
            "brand_id": brand.id,
            "competitor_id": competitor.id,
            "product_count": len(products),
        },
    )
```

(The exact loop variable names and emission style depend on the existing orchestrator structure — match local style.)

- [ ] **Step 3: Smoke test**

Run an onboarding flow on a brand with at least one competitor URL. SSE stream emits `onboarding.competitor_products_extracting` and `onboarding.competitor_products_extracted` with a `product_count`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/onboarding/orchestrator.py backend/app/events/types.py
git commit -m "feat(onboarding): extract competitor product catalogs after enrichment"
```

### Task 3.3 — Inject competitor products into personalization brief

**Files:**
- Modify: `backend/app/services/audience/personalization.py`

- [ ] **Step 1: Add a competitor catalog summary helper**

Insert near `_attribution_narrative`:

```python
def _competitor_catalog_text(db: Session, brand_id: str) -> str:
    competitors = (
        db.query(models.Competitor)
        .filter(models.Competitor.brand_id == brand_id)
        .all()
    )
    lines: list[str] = []
    for c in competitors:
        products = ((c.pattern_library or {}).get("products") or [])[:3]
        if not products:
            continue
        for p in products:
            lines.append(
                f"- {c.name}: {p.get('name','?')} @ "
                f"{p.get('price_text','?')}: "
                f"{(p.get('description') or '')[:100]}"
            )
    if not lines:
        return "(no competitor product data)"
    return "\n".join(lines[:10])
```

- [ ] **Step 2: Splice into `personalize_for_customer`**

In the user-prompt assembly inside `personalize_for_customer`:

```python
    user = (
        f"Brand voice: {_voice_brief(brand)}\n\n"
        f"Customer brief (PII redacted):\n{redaction.redacted_text}\n\n"
        f"Product catalog:\n{_product_catalog_text(products)}\n\n"
        f"Competitor catalog (for comparison context only — do NOT recommend "
        f"competitor products):\n{_competitor_catalog_text(db, brand_id)}\n\n"
        f"User instruction: {user_prompt or '(none — use your judgment)'}\n\n"
        "Write a short personalized email: subject + body. Reference the "
        "customer by their [NAME_x] token. Reference 1-2 specific recent "
        "activity moments. Recommend 1-2 products from OUR catalog by id. "
        "If a competitor offers a similar product, ONE sentence on why ours "
        "is the better fit (no name-calling, no lies). Output JSON: "
        "{subject, body, recommended_product_ids, reasoning}."
    )
```

- [ ] **Step 3: Smoke test**

Personalize a customer for a brand whose competitors have products extracted. The body should sometimes reference a comparison line. (LLM non-deterministic — observe over 3 runs.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/audience/personalization.py
git commit -m "feat(personalize): include competitor catalog in brief for comparison lines"
```

### Task 3.4 — Frontend: surface competitor catalog presence in personalize UI

A small reassurance for the demo — show a chip in `PersonalizeBlock` saying *"3 competitor products considered"* when the brief used them.

**Files:**
- Modify: `backend/app/services/audience/personalization.py` (return a `competitor_catalog_size` in the result)
- Modify: `frontend/src/lib/audience.ts` (extend `PersonalizedEmail`)
- Modify: `frontend/src/components/audience/PersonalizeBlock.tsx` (render chip)

- [ ] **Step 1: Backend — add competitor count to the result**

In `personalize_for_customer`, replace the `return {…}` near the end with:

```python
    competitor_catalog_size = sum(
        len(((c.pattern_library or {}).get("products") or []))
        for c in db.query(models.Competitor)
        .filter(models.Competitor.brand_id == brand_id)
        .all()
    )

    return {
        "subject": subject,
        "body": body,
        "recommended_product_ids": rec_ids,
        "reasoning": str(result.get("reasoning") or ""),
        "redaction_summary": _entity_summary(redaction.entities),
        "competitor_catalog_size": competitor_catalog_size,
    }
```

- [ ] **Step 2: Frontend — type + chip**

In `frontend/src/lib/audience.ts`:
```typescript
export type PersonalizedEmail = {
  subject: string
  body: string
  recommended_product_ids: string[]
  reasoning: string
  redaction_summary: { entity_count: number; types: string[] }
  competitor_catalog_size?: number
  html_body?: string  // populated after Phase 4
}
```

In `PersonalizeBlock.tsx` near the existing redaction summary:
```tsx
{typeof email.competitor_catalog_size === 'number' && email.competitor_catalog_size > 0 && (
  <span className="ml-2 text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">
    {email.competitor_catalog_size} competitor product{email.competitor_catalog_size === 1 ? '' : 's'} considered
  </span>
)}
```

- [ ] **Step 3: Smoke test**

Run personalize for a customer of a brand with extracted competitor products. The chip appears.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/audience/personalization.py frontend/src/lib/audience.ts frontend/src/components/audience/PersonalizeBlock.tsx
git commit -m "feat(audience-ui): show competitor-catalog-considered chip on personalized emails"
```

---

## Phase 4 — HTML email rendering

Today personalize returns plain `subject`/`body`. Add an HTML render with brand styling (palette, logo, CTA button) and surface it in `PersonalizeBlock`.

### Task 4.1 — `renderer.py` service

**Files:**
- Create: `backend/app/services/audience/renderer.py`

- [ ] **Step 1: Write the renderer**

```python
"""HTML email renderer.

Builds a single-table inline-styled HTML email using the brand's palette
and logo. No template engine — just an f-string. The body text comes
from the LLM output (already plain). Linebreaks are converted to
``<p>`` tags.
"""
from __future__ import annotations

import html
from typing import Iterable

from app.db import models


_TEMPLATE = """<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f7f9;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border-radius:14px;overflow:hidden;">
      <tr><td style="padding:24px 28px;background:{header_bg};color:{header_fg};">
        {logo_html}
      </td></tr>
      <tr><td style="padding:28px;color:#111;font-size:15px;line-height:1.55;">
        {body_html}
        {cta_html}
      </td></tr>
      <tr><td style="padding:18px 28px;background:#fafafa;color:#888;font-size:11px;">
        Sent by {brand_name}. You're receiving this because you're a customer.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _paragraphs(body: str) -> str:
    paras = [p.strip() for p in (body or "").split("\n\n") if p.strip()]
    if not paras:
        paras = [(body or "").strip()] if (body or "").strip() else []
    return "".join(
        f'<p style="margin:0 0 14px 0;">{html.escape(p).replace(chr(10), "<br/>")}</p>'
        for p in paras
    )


def _logo_html(brand: models.Brand, header_fg: str) -> str:
    if brand.logo_url:
        return (
            f'<img src="{html.escape(brand.logo_url)}" alt="{html.escape(brand.name)}" '
            f'height="28" style="display:block;height:28px;"/>'
        )
    return (
        f'<div style="font-weight:700;font-size:18px;color:{header_fg};">'
        f"{html.escape(brand.name)}</div>"
    )


def _cta_html(
    brand: models.Brand, products: Iterable[models.Product]
) -> str:
    products = list(products)[:1]
    if not products:
        return ""
    p = products[0]
    accent = brand.theme_color or "#111"
    label = f"Shop {p.name}"
    href = "#"  # real shop URL wiring is out of scope for v0
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;">'
        f'<tr><td style="background:{accent};border-radius:8px;">'
        f'<a href="{href}" style="display:inline-block;padding:11px 18px;color:#fff;text-decoration:none;font-weight:600;font-size:14px;">'
        f"{html.escape(label)}</a>"
        f"</td></tr></table>"
    )


def render(
    brand: models.Brand,
    body_text: str,
    recommended_products: Iterable[models.Product],
) -> str:
    accent = brand.theme_color or "#111"
    header_fg = "#fff" if accent.lower() not in ("#fff", "#ffffff") else "#111"
    return _TEMPLATE.format(
        header_bg=accent,
        header_fg=header_fg,
        logo_html=_logo_html(brand, header_fg),
        body_html=_paragraphs(body_text),
        cta_html=_cta_html(brand, recommended_products),
        brand_name=html.escape(brand.name or "Your brand"),
    )
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from types import SimpleNamespace
from app.services.audience.renderer import render
brand = SimpleNamespace(name='Demo', logo_url=None, theme_color='#1f2937')
out = render(brand, 'Hi Sarah,\n\nWe noticed you abandoned your cart.', [SimpleNamespace(name='Studio Tee')])
print(out[:200])
print('...')
print('len', len(out))
"
```
Expected: a well-formed HTML doc starting with `<!doctype html>`, including a CTA "Shop Studio Tee" and "Hi Sarah" in a `<p>`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/audience/renderer.py
git commit -m "feat(audience): HTML email renderer with brand palette + logo + CTA"
```

### Task 4.2 — Wire `renderer.render()` into `personalize_for_customer` + `personalize_for_segment`

**Files:**
- Modify: `backend/app/services/audience/personalization.py`

- [ ] **Step 1: Render and include `html_body` in both functions' results**

Add at top of `personalization.py`:
```python
from app.services.audience import renderer
```

In `personalize_for_customer`, just before the final `return`:
```python
    rec_products = [p for p in products if p.id in valid_ids and p.id in rec_ids]
    html_body = renderer.render(brand, body, rec_products)
```

Update the return:
```python
    return {
        "subject": subject,
        "body": body,
        "html_body": html_body,
        "recommended_product_ids": rec_ids,
        "reasoning": str(result.get("reasoning") or ""),
        "redaction_summary": _entity_summary(redaction.entities),
        "competitor_catalog_size": competitor_catalog_size,
    }
```

Mirror the same change in `personalize_for_segment` (use empty list for `rec_products` if simpler — segment emails typically don't have a single hero product).

- [ ] **Step 2: Smoke test**

```bash
curl -X POST http://localhost:8000/api/audience/personalize \
  -H "content-type: application/json" \
  -d "{\"brand_id\":\"demo\",\"target_kind\":\"customer\",\"target_id\":\"$CID\"}" \
  | python -c "import sys,json;d=json.load(sys.stdin);print('html len',len(d['email']['html_body']));print(d['email']['html_body'][:120])"
```
Expected: html_body length ~800-1500 starting with `<!doctype html>`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/audience/personalization.py
git commit -m "feat(personalize): include html_body alongside plain body"
```

### Task 4.3 — Frontend: render HTML preview in `PersonalizeBlock`

**Files:**
- Modify: `frontend/src/components/audience/PersonalizeBlock.tsx`

- [ ] **Step 1: Add an iframe srcdoc preview**

Where the existing personalize result is rendered (subject + body), add a tabbed view or a side-by-side. Simplest version: a toggle showing either plain or HTML.

```tsx
import { useState } from 'react'

function EmailRenderTabs({ email }: { email: { body: string; html_body?: string } }) {
  const [view, setView] = useState<'html' | 'text'>(email.html_body ? 'html' : 'text')
  return (
    <div className="mt-3">
      <div className="flex gap-2 mb-2">
        {email.html_body && (
          <button
            className={`text-xs px-2 py-1 rounded ${view === 'html' ? 'bg-zinc-700 text-zinc-100' : 'bg-zinc-900 text-zinc-400'}`}
            onClick={() => setView('html')}
          >HTML</button>
        )}
        <button
          className={`text-xs px-2 py-1 rounded ${view === 'text' ? 'bg-zinc-700 text-zinc-100' : 'bg-zinc-900 text-zinc-400'}`}
          onClick={() => setView('text')}
        >Plain</button>
      </div>
      {view === 'html' && email.html_body ? (
        <iframe
          srcDoc={email.html_body}
          title="email preview"
          sandbox=""
          className="w-full h-[480px] bg-white rounded border border-zinc-700"
        />
      ) : (
        <pre className="whitespace-pre-wrap text-sm text-zinc-200 bg-zinc-950 p-3 rounded border border-zinc-800">
          {email.body}
        </pre>
      )}
    </div>
  )
}
```

Replace the existing body rendering with `<EmailRenderTabs email={email} />`.

- [ ] **Step 2: Smoke test in browser**

Personalize a customer. The HTML tab shows the rendered email with the brand color header and the CTA button.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/audience/PersonalizeBlock.tsx
git commit -m "feat(audience-ui): HTML email preview tabs in PersonalizeBlock"
```

### Task 4.4 — Persist `html_body` in `EmailSend` on dispatch

**Files:**
- Modify: `backend/app/db/models.py` (add `html_body` column to `EmailSend`)
- Modify: `backend/app/api/audience.py` (accept + persist `html_body`)
- Modify: `frontend/src/stores/audienceStore.ts` (pass `html_body` to dispatch)

- [ ] **Step 1: Add column**

In `db/models.py` `EmailSend`:
```python
class EmailSend(Base):
    __tablename__ = "email_sends"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    target_kind = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    html_body = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="queued")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
```

The repo uses `Base.metadata.create_all` at lifespan-start, so the column will be added automatically on a fresh DB. For an existing SQLite file, drop it: `rm backend/brand_autopilot.db` (the dev DB regenerates from imports). Document this in the commit message.

- [ ] **Step 2: Update `/dispatch` payload + persistence**

In `audience.py`:
```python
class DispatchIn(BaseModel):
    brand_id: str
    target_kind: Literal["customer", "segment"]
    target_id: str
    subject: str
    body: str
    html_body: str | None = None


@router.post("/dispatch")
def dispatch(
    body: DispatchIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    # ... existing target lookup logic ...
    send = models.EmailSend(
        brand_id=body.brand_id,
        target_kind=body.target_kind,
        target_id=body.target_id,
        subject=body.subject,
        body=body.body,
        html_body=body.html_body,
        status="sent",
        sent_at=now,
    )
    # ... rest unchanged ...
```

- [ ] **Step 3: Update store dispatch action**

In `audienceStore.ts` `dispatch` action signature + body:
```typescript
  dispatch: (
    brand_id: string,
    target_kind: 'customer' | 'segment',
    target_id: string,
    subject: string,
    body: string,
    html_body?: string,
  ) => Promise<{ ok: boolean; send_id: string | null }>

  // ... in the implementation, include html_body in the request body:
  body: JSON.stringify({
    brand_id, target_kind, target_id, subject, body, html_body,
  }),
```

In `PersonalizeBlock.tsx`, when calling dispatch, pass `email.html_body`.

- [ ] **Step 4: Smoke test**

Dispatch an email. Then `sqlite3 backend/brand_autopilot.db "SELECT length(html_body) FROM email_sends ORDER BY created_at DESC LIMIT 1;"` returns a non-null length.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/app/api/audience.py frontend/src/stores/audienceStore.ts frontend/src/components/audience/PersonalizeBlock.tsx
git commit -m "feat(audience): persist html_body on EmailSend dispatch (drop dev db on migration)"
```

---

## Phase 5 — End-to-end demo verification

Final task: walk through the spec's §13 demo script (`docs/superpowers/specs/2026-04-26-personalized-email-campaigns-design.md` §13) with the full pipeline — attribution badges → segments → shop trigger → auto-personalize → HTML preview → dispatch.

### Task 5.1 — Demo script rehearsal

- [ ] **Step 1:** Backend running, frontend running, fresh DB, fresh import.

```bash
rm -f backend/brand_autopilot.db
cd backend && uvicorn app.main:app --reload &
cd frontend && pnpm dev &
```

Open `http://localhost:5173`, complete onboarding for a brand with at least one competitor URL. Connect mock CRM, import.

- [ ] **Step 2:** Verify each act of the demo:

  - **Customer list** shows acquisition badges (Google Ads · ga_summer_sale_2026, Organic, Newsletter, etc.)
  - **Customer drawer** shows acquisition journey timeline
  - **Propose segments** returns 3-6 segments with names like "Lapsed VIPs"
  - **Shop feed** — click "Fire test cart_abandoned" — entry appears with `drafting…` then resolves to `✓ Email drafted: "..."`
  - **Personalize button** on a customer — HTML preview tab shows branded email with CTA button matching brand color
  - **Competitor-considered chip** appears when brand has competitor products extracted
  - **Dispatch** — `EmailSend.html_body` row persisted

- [ ] **Step 3:** If any step fails, file the failing step as a follow-up task; do not fix in this rehearsal task to keep commits scoped.

- [ ] **Step 4: Commit (any rehearsal-driven small fixes)**

```bash
git add -p
git commit -m "fix(audience): demo rehearsal pass - <specific fixes>"
```

---

## Out of scope for this plan

- Pytest setup + unit tests — separate plan, blocks nothing.
- Real CRM OAuth (HubSpot, Salesforce) — `mock` provider is sufficient for demo.
- Real email send (Resend / SMTP) — `dispatch` records an `EmailSend` row only.
- K-means / embeddings segmentation — LLM clustering is in production.
- Send-time optimization, bounce handling, unsubscribe — not relevant to fixture-based demo.
- Per-segment fan-out personalization — current per-segment endpoint generates one merge-tagged email; per-member fan-out is a v2 feature.
- Auto-send toggle on shop events — current behavior is preview-only via `audience.shop_auto_personalized`; user must click Send.

## Risks during execution

- **Shared file edits** (`backend/app/events/types.py`, `backend/app/main.py`) collide with peer agent (`backend-videogen`). **Mitigation:** post W2W heads-up, append-only edits, pull before commit, resolve conflicts by keeping both peers' additions.
- **Gemini latency** during shop-event auto-personalize. **Mitigation:** the listener uses `asyncio` and the bus is non-blocking; the SSE stream tells the user "drafting…" so the UX doesn't feel stuck.
- **Competitor scrape failures** are silent (returns `[]`). **Mitigation:** `_competitor_catalog_text` already handles empty case; LLM prompt instructs to skip comparison line if no data.
- **SQLite migration** for the new `EmailSend.html_body` column requires dropping the dev DB (no Alembic in repo). **Mitigation:** documented in Task 4.4 commit message.

---

## Self-review

- **Spec coverage:** Phase 1 covers spec §2.4 + §4 acquisition fields + §6 attribution synthesizer. Phase 2 covers §2.3 shop triggers + §5 shop event types. Phase 3 covers §3.2 onboarding extension + §6 competitor extractor + comparison line. Phase 4 covers §6 renderer + §9 EmailPreview HTML rendering. Hero demo (§13) verified by Phase 5. **Spec items not in plan:** PII model swap to OpenAI Privacy Filter (already deferrable per spec, interface exists), per-segment fan-out personalization (out-of-scope §11), Resend integration (out-of-scope §11), dedicated `Contact`/`EmailMessage` rename (handled by spec↔reality map at top).

- **Placeholder scan:** No "TBD"/"TODO" steps. Each step has either real code, a real shell command, or a real verification.

- **Type consistency:** `Customer`, `Acquisition`, `Touchpoint` consistent across backend serializer, frontend type, and components. Event names (`audience.shop_event_triggered`, `audience.shop_auto_personalized`, `onboarding.competitor_products_extracted`) consistent across backend emit, frontend bus listener, and types.

No issues to fix.
