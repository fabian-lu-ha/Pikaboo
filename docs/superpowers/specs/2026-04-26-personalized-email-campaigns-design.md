# Personalized Email Campaigns — Design

**Status:** Approved 2026-04-26
**Project:** Brand Autopilot (Big Berlin Hack 2026)
**Decision:** Approach 1 — event-pipeline of stages, mirroring `services/onboarding/orchestrator.py` and `services/agent/loop.py`.

## 1. Summary

Turn Brand Autopilot from a broadcast-marketing copilot into a 1:1 customer-aware marketer. Connect to a (mocked) CRM that holds rich per-contact data — emails, clicks, purchases, acquisition attribution — auto-cluster contacts into named segments, redact third-party PII before any LLM call, generate hyper-personalized emails for individual contacts (or per-segment variants), and pick the right product from a synced shop catalog with optional competitive context scraped from competitor sites at onboarding.

The hero demo is **clicking one contact and watching a 6-stage pipeline produce a polished, branded HTML email tailored from that person's actual history, with the right product chosen and a competitor-aware comparison line.** Shop events fire the same pipeline automatically.

## 2. User-Facing Flows

### 2.1 Hero — 1:1 personalized email
1. User opens **Contacts** tab — sees CRM contacts with segment chips and acquisition source badges (`Google Ads · summer_sale`, `Organic · founder blog`, `Referral · partner_x`).
2. Clicks a contact — sees full history (last emails sent/received, clicked products, purchases, attribution journey timeline).
3. Clicks **Personalize Email** — pipeline animates step-by-step: *loading context → redacting PII → picking product → drafting → rendering*.
4. Final view: rendered HTML email (branded), product picked with rationale, optional competitor comparison line, **Send** button.

### 2.2 Segments — auto-clustering
1. User opens **Segments** tab.
2. AI auto-clusters into 4–6 named segments (e.g., *"Dormant high-LTV (12)"*, *"New + bought-once (28)"*, *"EU SMB freelancers (15)"*, *"Black-Friday-acquired (9)"*).
3. User clicks a segment → either browses member contacts (drill into 2.1) or generates a **per-segment campaign** — one email variant per segment, all in one click.

### 2.3 Shop-triggered automation
1. Mock shop emits events: `cart_abandoned`, `purchase_completed`, `subscription_lapsed`.
2. Each event routes the corresponding contact through the personalization pipeline with the trigger event as additional signal.
3. Generated emails land in a **Pending** queue (v0 preview-only) — user reviews then clicks Send. (v1 toggle: auto-send.)

### 2.4 Attribution-aware everything
- Every personalized email weighs the contact's acquisition source. A Black Friday Google Ads visitor gets a different greeting and CTA than someone from an organic founder-blog post.
- The contact detail view shows a multi-touch journey timeline.

## 3. Architecture

Pure event-first. **No new architectural pattern — only new pipeline stages.** Each stage is one Python module + one event listener registered against the existing pyee bus (`backend/app/events/bus.py`). Frontend SSE renders each stage as a lit-up timeline node. Same shape as onboarding orchestration.

### 3.1 Personalization pipeline (one contact, one trigger)

```
trigger (manual click | shop event | scheduled batch)
  ↓ crm.contact_selected
  → context_builder
  ↓ attribution.context_built
  → pii_redactor
  ↓ pii.redacted
  → product_matcher
  ↓ personalize.product_picked
  → drafter (LLM)
  ↓ personalize.draft_generated
  → renderer
  ↓ personalize.ready_to_send
  (v0: pipeline halts here until user clicks Send;
   v1+: optional auto-send toggle per-segment / per-trigger)
  ↓ email.sent  (v0: stub log; v1: Resend)
```

Failure at any stage emits a `*.failed` variant; the orchestrator marks the `EmailMessage.state = "failed"` with a reason and the frontend renders the failed node red.

### 3.2 Onboarding extension

```
existing: competitors_suggesting → competitors_suggested → competitor_enriched
adds:                                                    → competitor.products_extracting
                                                         → competitor.products_extracted
```

Scrape competitor product catalogs at onboarding time. Cache on `Competitor.product_catalog`. Live personalization never blocks on a scrape; it falls back to no-comparison-line if competitor catalog is empty.

### 3.3 Segmentation flow

```
POST /api/email/segments/cluster
  ↓ segments.clustering
  → cluster service: build redacted contact-summary list, ask Gemini for 4–6 named clusters with member_ids
  ↓ segments.clustered  (persists Segment rows, denormalizes Contact.segment_ids)
```

## 4. Data Model

New SQLAlchemy models in `backend/app/db/models.py`. All FK to existing `Brand` for tenant isolation.

```python
class Contact(Base):
    id: int
    brand_id: int          # FK Brand
    email: str             # unique per brand
    first_name: str
    last_name: str | None
    country: str | None
    signup_at: datetime
    acquisition: JSON       # { source, campaign, utm_source, utm_medium, utm_campaign,
                            #   utm_content, utm_term, first_touch_url, referrer }
    touchpoints: JSON       # [ { source, campaign, at, action }, ... ] multi-touch journey
    segment_ids: JSON       # [int]  — denormalized for filter speed
    metadata: JSON          # plan tier, ltv_cents, etc.

class ContactEvent(Base):
    id: int
    contact_id: int        # FK Contact
    kind: str              # email_sent | email_received | page_view |
                           # product_clicked | purchase | cart_abandoned | subscription_lapsed
    at: datetime
    payload: JSON          # subject+body for emails; product_id for clicks/purchases; etc.

class Segment(Base):
    id: int
    brand_id: int          # FK Brand
    name: str              # "Dormant high-LTV"
    description: str       # one-sentence cluster description
    member_count: int
    member_ids: JSON       # [contact_id]
    created_at: datetime

class Product(Base):
    id: int
    brand_id: int          # FK Brand
    name: str
    price_cents: int
    currency: str
    image_url: str | None
    description: str
    target_attributes: JSON # ["small_team", "developers", "design-conscious"]

class CompetitorProduct(Base):
    id: int
    competitor_id: int     # FK Competitor (existing model)
    name: str
    price_cents: int | None
    currency: str | None
    image_url: str | None
    description: str | None
    source_url: str

class EmailMessage(Base):
    id: int
    contact_id: int                 # FK Contact
    segment_id: int | None          # FK Segment (set if generated as part of segment campaign)
    trigger: str                    # manual | shop.cart_abandoned | shop.purchase_completed | ...
    subject: str
    html_body: str
    plain_body: str
    product_id: int | None          # FK Product
    competitor_product_id: int | None  # FK CompetitorProduct
    rationale: str                  # why this product, why this angle (LLM output)
    state: str                      # draft | preview_ready | sent | failed
    failure_reason: str | None
    created_at: datetime
    sent_at: datetime | None
```

## 5. Event Types

Added to `backend/app/events/types.py`. **Append-only** — coordinate with peer agents that may be editing the same file.

```python
# CRM
CrmSynced(brand_id, contact_count)
CrmContactSelected(contact_id, trigger)            # trigger: "manual" or "shop.<kind>"

# Attribution
AttributionContextBuilt(contact_id, summary)

# PII
PiiRedacting(contact_id)
PiiRedacted(contact_id, replacements_count)
PiiRedactionFailed(contact_id, reason)

# Personalize
PersonalizeContextAssembled(contact_id)
PersonalizeProductPicked(contact_id, product_id, rationale)
PersonalizeDraftGenerated(contact_id, subject_preview)
PersonalizeReadyToSend(contact_id, email_id)
PersonalizeFailed(contact_id, stage, reason)

# Email send
EmailSendRequested(email_id)
EmailSent(email_id)                                 # stub in v0
EmailSendFailed(email_id, reason)

# Segments
SegmentsClustering(brand_id)
SegmentsClustered(brand_id, segment_count)
SegmentsClusteringFailed(brand_id, reason)

# Shop triggers
ShopCartAbandoned(contact_id, cart_value_cents, product_ids)
ShopPurchaseCompleted(contact_id, order_value_cents, product_ids)
ShopSubscriptionLapsed(contact_id, product_id, lapsed_days)

# Competitor products (onboarding extension)
CompetitorProductsExtracting(competitor_id)
CompetitorProductsExtracted(competitor_id, product_count)
CompetitorProductsExtractionFailed(competitor_id, reason)
```

## 6. Backend File Layout (new code)

```
backend/app/services/
├── crm/
│   ├── __init__.py            # registers listeners
│   ├── loader.py              # load fixture, normalize to Contact + ContactEvent rows, emit crm.synced
│   └── fixture_path.py        # resolves backend/app/fixtures/mock_crm.json
├── shop/
│   ├── __init__.py
│   └── triggers.py            # cart_abandoned/purchase_completed/lapsed simulators + listeners that
│                              #   route the trigger into the personalization pipeline
├── pii/
│   ├── __init__.py
│   ├── interface.py           # PIIRedactor Protocol + RedactionResult TypedDict
│   └── gemini_redactor.py     # Gemini-prompt impl using existing services.llm.chat_json
├── segmentation/
│   ├── __init__.py
│   └── cluster.py             # LLM clustering of contacts into named segments
├── attribution/
│   ├── __init__.py
│   └── synthesize.py          # builds "this user came from..." narrative for LLM context
├── product_catalog/
│   ├── __init__.py
│   ├── loader.py              # synced products from fixture (frame as "from your store")
│   └── matcher.py             # picks best product (LLM scored against contact profile)
├── personalize/
│   ├── __init__.py            # registers all listeners; orchestrates the pipeline
│   ├── orchestrator.py        # listens for triggers, dispatches to stages
│   ├── context_builder.py     # assembles full LLM input (history + attribution + product catalog)
│   ├── drafter.py             # LLM draft generation; outputs JSON {subject, html_body, plain_body, rationale}
│   └── renderer.py            # HTML email render with Brand styling (palette, logo, CTA button)
├── enrichment/
│   └── competitor_products.py # NEW extractor for competitor catalogs (called by onboarding orchestrator)
└── email_send/
    ├── __init__.py
    └── stub.py                # logs to console + persists EmailMessage.state="sent" + emits email.sent

backend/app/api/
└── email.py                   # endpoints (see §7); registered in main.py

backend/app/fixtures/
└── mock_crm.json              # rich fixture: brand_seed, products, ad_campaigns, contacts (+ events)
```

## 7. API Endpoints

```
POST /api/crm/sync                          # load fixture → DB; emit crm.synced
GET  /api/crm/contacts                      # list with segment + acquisition badges (paginated)
GET  /api/crm/contacts/{id}                 # full detail incl. events + attribution timeline

POST /api/email/personalize/{contact_id}    # trigger 1:1 pipeline; returns email_id; stages stream over SSE
POST /api/email/segments/cluster            # trigger segmentation; emit segments.clustered
GET  /api/email/segments                    # list segments
POST /api/email/segments/{id}/campaign      # generate per-segment variants (calls personalize for each member;
                                            #   bounded fan-out, max 5 in parallel)
POST /api/email/{email_id}/send             # stub-send; emits email.sent

POST /api/shop/trigger/{kind}               # manually fire a shop event (cart_abandoned | purchase_completed |
                                            #   subscription_lapsed); body: {contact_id, ...payload}
                                            #   used for live demo and tests
```

All endpoints emit progress over the existing `/api/events/stream` SSE — no new transport.

## 8. PII Redactor Interface

```python
# services/pii/interface.py
class RedactionResult(TypedDict):
    redacted_text: str
    replacements: dict[str, str]   # placeholder ("[PERSON_1]") -> original ("Sarah's husband Mike")

class PIIRedactor(Protocol):
    async def redact(self, text: str, *, keep: list[str] = []) -> RedactionResult: ...
```

`keep=[contact.first_name]` preserves the recipient's own name (they are the data subject). Mappings are kept server-side and never sent to an LLM in subsequent calls; if we need to reference the original (we shouldn't), we always re-fetch from `Contact` rather than from `replacements`.

**v0**: `gemini_redactor.py` calls `services/llm/chat_json` with a strict JSON schema and a prompt that instructs the model to redact 8 PII categories matching the OpenAI Privacy Filter taxonomy.
**v1 swap**: `openai_privacy_filter_redactor.py` using HuggingFace `transformers` + the open-weight model. Selected via `settings.pii_redactor_kind` env var.

## 9. Frontend Additions

```
frontend/src/components/
├── ContactsView.tsx        # list with segment/attribution badges; filter by segment, source, country
├── ContactDetail.tsx       # full history + attribution timeline + Personalize button
├── EmailPreview.tsx        # rendered HTML email (iframe srcdoc) + product card + rationale + Send
├── SegmentsView.tsx        # AI clusters with descriptions + member counts + "Run campaign" button
└── ShopFeed.tsx            # live shop events feed; click to trigger one manually for demo

frontend/src/stores/
├── contactsStore.ts        # contacts + segments + filters
├── personalizeStore.ts     # per-pipeline stage state, draft, product, rationale, email_id
└── shopStore.ts            # shop trigger feed + auto-trigger toggle

frontend/src/events/bus.ts  # extend AgentEvents with the new event types
frontend/src/events/useEventStream.ts  # add dispatch cases for new events
```

Routing: add `/contacts`, `/contacts/:id`, `/segments`, `/shop` to the existing app shell.

## 10. Mock Fixture Shape

`backend/app/fixtures/mock_crm.json`:

```json
{
  "brand_seed": { "name_hint": "Acme", "industry": "B2B SaaS" },
  "products": [
    {
      "name": "Widget Pro",
      "price_cents": 7900,
      "currency": "USD",
      "image_url": "/static/products/widget-pro.png",
      "description": "Self-serve plan for solo founders",
      "target_attributes": ["solo", "developer", "early-stage"]
    }
    /* 8–12 products spanning price tiers + audiences */
  ],
  "ad_campaigns": [
    {
      "id": "ga_summer_2026",
      "platform": "google_ads",
      "name": "Summer Sale 2026",
      "spend_cents": 240000,
      "clicks": 1820,
      "conversions": 47
    }
    /* 4–6 campaigns: google_ads, meta_ads, organic, referral, email */
  ],
  "contacts": [
    {
      "email": "sarah.k@example.com",
      "first_name": "Sarah",
      "last_name": "Kowalski",
      "country": "DE",
      "signup_at": "2026-02-14T09:21:00Z",
      "acquisition": {
        "source": "google_ads",
        "campaign": "ga_summer_2026",
        "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "summer-sale",
        "utm_content": "widget-pro-promo", "utm_term": "ai marketing tool",
        "first_touch_url": "/products/widget-pro",
        "referrer": "google.com"
      },
      "touchpoints": [
        { "source": "google_ads", "campaign": "ga_summer_2026", "at": "2026-02-14T09:21:00Z", "action": "first_visit" },
        { "source": "email", "campaign": "welcome_series", "at": "2026-02-15T07:00:00Z", "action": "open" },
        { "source": "direct", "campaign": null, "at": "2026-04-25T18:11:00Z", "action": "cart_abandon" }
      ],
      "metadata": { "ltv_cents": 0, "plan": null },
      "events": [
        { "kind": "email_received", "at": "2026-02-15T07:00:00Z", "payload": { "subject": "Welcome to Acme", "body": "..." } },
        { "kind": "page_view", "at": "2026-04-25T17:42:00Z", "payload": { "url": "/products/widget-pro" } },
        { "kind": "product_clicked", "at": "2026-04-25T17:48:00Z", "payload": { "product_id": 0 } },
        { "kind": "cart_abandoned", "at": "2026-04-25T18:11:00Z", "payload": { "product_ids": [0], "value_cents": 7900 } }
      ]
    }
    /* 30–50 contacts spanning: dormant high-LTV, new+bought-once, EU SMB freelancers,
       Black-Friday-acquired, organic-blog-acquired, referral-from-partner */
  ]
}
```

The fixture is the single source of truth for the demo. No live scrapes required at runtime (other than the optional competitor-product extractor at onboarding).

## 11. Out of Scope (v0)

- Real CRM/Shopify/Gmail OAuth — fixture only.
- Real email send — stub logs and emits event.
- Embeddings / k-means segmentation — LLM clustering only.
- Multi-touch attribution ML — heuristic-based context synthesis from `touchpoints[]`.
- Autonomous batch sends — preview-only with user-click "Send".
- Bounce / unsubscribe / suppression handling — irrelevant to a fixture-based demo.
- Real-time analytics ingestion — events come from fixture + manual trigger endpoint.
- Per-contact send-time optimization — v2.

## 12. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Competitor product scrape fails for a brand at onboarding | Fall back gracefully — personalization works without competitor angle; renderer omits the comparison line if `competitor_product_id` is null |
| Gemini PII redaction misses an entity | Interface boundary lets us swap to OpenAI Privacy Filter without code changes outside `services/pii/`; demo prompt narrowly scopes content to fixture text where we control the inputs |
| LLM hallucinates a product not in catalog | Drafter prompt includes the catalog JSON; product_matcher returns a real `Product.id`, renderer pulls all product display data from the row, never from drafter output |
| Events fire faster than the frontend can render | Same pyee + SSE pipeline as onboarding/agent — already handles bursts in current usage |
| Conflict with peer agent (`backend-videogen`) editing `events/types.py` and `main.py` | Append-only changes to `types.py`; coordinate via W2W bulletin before edits; register router in `main.py` after pulling latest |
| Per-segment campaign fan-out hammers Gemini quota | Cap parallel personalize calls at 5 per segment campaign; queue the rest |
| Demo fixture is too sparse to feel real | Spec calls for 30–50 contacts with varied histories spanning all attribution sources and event kinds — author the fixture deliberately, not faker-random |
| User refreshes mid-pipeline | Pipeline state persisted to `EmailMessage.state`; frontend rehydrates from `GET /api/email/{id}` and resubscribes to events |

## 13. Demo Script (60-second hero)

1. **(0:00–0:05)** Open Contacts tab — show 30 contacts with attribution badges (`Google Ads · summer_sale`, `Organic · founder blog`, etc.).
2. **(0:05–0:10)** Open Segments tab — *"AI found 5 segments"* — show *"Dormant high-LTV"*, *"New + bought-once"*, *"Black-Friday-acquired"*.
3. **(0:10–0:15)** Open Shop Feed — toggle on; instantly see *"Cart abandoned: Sarah K., Widget Pro"* trigger fire.
4. **(0:15–0:25)** Click Sarah — see full history with Google Ads attribution journey timeline.
5. **(0:25–0:40)** Click "Personalize Email" — watch 6-stage pipeline animate (loading context → redacting PII → picking product → drafting → rendering).
6. **(0:40–1:00)** Final email rendered — branded, addresses Sarah by name, references that she came from the Black Friday Google ad and abandoned the Widget Pro cart, picks Widget Pro Plus as the upsell with rationale, includes competitive comparison line vs CompetitorX's $99 plan, signed in the brand's voice. **Send** button glows.

## 14. Implementation Sequencing (writing-plans hand-off)

The implementation plan should sequence the work so each step ends with something demoable:

1. Data model + migrations (Contact, ContactEvent, Segment, Product, CompetitorProduct, EmailMessage).
2. Mock fixture authoring — the demo lives or dies by this file's quality.
3. CRM loader + `/api/crm/sync` + `/api/crm/contacts*` + ContactsView + ContactDetail.
4. PII redactor interface + Gemini impl + tests.
5. Personalize pipeline (orchestrator + context_builder + product_matcher + drafter + renderer) + `/api/email/personalize/{id}` + EmailPreview component. **End of step 5 = hero demo works.**
6. Segmentation service + `/api/email/segments/*` + SegmentsView.
7. Shop triggers + ShopFeed + `/api/shop/trigger/{kind}`.
8. Attribution synthesizer integration into context_builder.
9. Competitor product extractor wired into onboarding orchestrator + competitor comparison line in renderer.
10. Email send stub + `/api/email/{id}/send`.
11. Polish, fixture authoring pass 2, demo script rehearsal.

Steps 1–5 are the critical path to the hero demo. Steps 6–11 are layered enhancements that each light up another part of the demo script.
