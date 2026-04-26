# 1:1 Personalized Campaigns & Custom Offers — vision plan

_Date: 2026-04-26_
_Branch: feat/audience-extensions_
_Successor to:_ `docs/superpowers/plans/2026-04-26-personalized-email-campaigns.md` (mostly shipped — attribution, shop triggers, competitor products, HTML email render are all in main).

---

## What we already have

Phase 1 of the audience extension already shipped on this branch. Concretely:

- **Data legs:** `Customer`, `CustomerEvent` (open / click / purchase / page_view / support / cart_abandoned / subscription_lapsed), `Product`, `Segment`, `EmailSend`, multi-touch attribution under `customer.attributes.acquisition` + `touchpoints`.
- **Mock CRM ingestion:** `services/crm/providers/mock.py` → `services/crm/sync.py::import_all` upserts customers + events + products. Pluggable provider interface — Shopify / HubSpot / Klaviyo can drop in next.
- **AI segmentation:** `services/audience/segmentation.py::propose_segments` builds PII-free per-customer summaries and asks Gemini for 3–6 named segments with rationales. Frontend has a `ProposedSegmentsModal` for accept/reject.
- **PII shield:** `services/pii/{regex_redactor,google_dlp,redactor}.py`. Cloud DLP when `GCP_PROJECT_ID` is set; Gemini-3-flash classifier when only `GEMINI_API_KEY` is set; regex fallback otherwise. Tokenizes to `[NAME_1] [EMAIL_1]` style placeholders, LLM only sees tokens, rehydrate is local. **Fail-closed:** detection errors abort rather than leak.
- **Personalization:** `services/audience/personalization.py` has both `personalize_for_customer` (full PII redacted in, rehydrated out, HTML email with product CTA) and `personalize_for_segment` (aggregate brief, `{customer_name}` merge tag).
- **UI:** `components/audience/{AudiencePane,CustomerList,CustomerDrawer,SegmentDrawer,PIIShield,PersonalizeBlock,ConnectCRMModal,ProductGrid,ShopFeed}`.

That is: **a single email per customer or per segment is solved.** What's not solved is the next two steps the user asked for: **full multi-touch campaigns generated for one person**, and **custom product offers bundled per person** — both attachable to a user group.

---

## The PII model — fact correction

User asked us to use "Google's just-released new PII model." That release doesn't exist. Reality, as of April 2026:

- The April 2026 PII headline is **OpenAI Privacy Filter** (Apache-2.0, 1.5B params / 50M active, 8 categories: names, addresses, emails, phones, URLs, dates, account numbers, secrets; 96–97% F1 on PII-Masking-300k; designed to run locally).
- Google's PII story is unchanged: **Cloud DLP** (server, mature, infoTypes API). The codebase already uses it as the primary path, with a Gemini-3-flash classifier as the cheaper fallback.
- ShieldGemma 2 is image safety, not PII.

So "use Google" is already the architecture. What we should *steal from OpenAI's approach without taking their library*:

1. **Local-first, on-device path.** Keep Google DLP as default but make sure the regex fallback covers OpenAI's 8 categories (we currently cover 6) so a fully offline demo works.
2. **Span-based output, not row-based.** Already what we do.
3. **Honest "fail-closed" semantics.** Already what we do.

→ **Action:** harden `regex_redactor.py` to add `URL`, `DATE`, `ACCOUNT_NUMBER`, `SECRET` (API key / password) categories, mirroring the Privacy Filter taxonomy. Cite the inspiration in the docstring. No new dependency.

---

## Inspiration: hera.video

Hera (the user's reference) is "AI Motion Designer" — drop in a customer record, get a 1:1 personalized video at brand quality. The pattern that matters for us:

- **One drag-and-drop ingest** of a CRM/customer file is the entire onboarding moment.
- **The unit of output is one asset per person**, not a campaign template + merge tags. The asset is composed from brand templates filled with that person's signals.
- **Scale is the magic.** The demo lands when you watch a feed render 100 personalized assets in front of you.

We already have video gen (`services/video_gen/`, `api/video.py`). So a hera-grade demo is in reach: **personalized video clip + personalized email + personalized landing copy, per customer, in a feed.**

---

## The new feature, in one sentence

> **Pick a person or a group → get a complete multi-touch campaign and a custom product offering, with PII never reaching the LLM.**

### What "campaign" means here (vs. a single email)

A campaign is a 3–5 step orchestrated sequence. Two flavors:

**Individual target (1:1, the wow):**
1. **Hook email** — references the trigger signal (cart-abandoned, lapsed sub, new launch in their top category).
2. **Reminder email** — +2/+4 days if no open/click; references one earlier touchpoint from their history.
3. **Offer email** — bundles the *custom offer* (below). Hard CTA.
4. **Personalized video clip with voice overlay** — same redacted brief produces a 15–30s voiceover script that the brand's fine-tuned voice reads over a base video template. Rendered **on demand** (when the user clicks preview, or when the campaign actually dispatches). Cached by `(customer_id, campaign_id, touch_id)` so re-clicks are free.
5. _(Optional)_ **Landing snippet** — one-page copy block keyed to the same brief, served from `/o/{offer_id}`.

**Group target (segment, the workhorse):**
- One templated campaign for the segment, `{customer_name}` merge tag style. What `personalize_for_segment` already does — promoted from a one-shot email to a real multi-touch sequence backed by `Campaign` + `CampaignTouch` rows. No 1:1 fanout.

### One LLM call, three coupled outputs

For an individual target, a single redacted-brief LLM call returns `{email_body, voiceover_script, offer_payload}` together. Reasons:
- Tone stays coherent across channels (the email and the voice say the same thing in their own register).
- One PII shield pass instead of three.
- Cheaper than three independent calls.

The voiceover script is short, conversational, has no CTAs/headers/footer, and references 1–2 personal signals. It's the same brief, different writing constraints — captured in the JSON schema as separate fields.

### What "custom offer" means

A composed object per customer or per group, **bounded by the brand's offer policy** (see below). Persisted as `Offer`:
- 1–3 products from *our catalog* (id-checked against `models.Product`).
- A discount or bundle rule chosen by the LLM **within the policy envelope** (percent / fixed amount / free shipping / BOGO / bundle).
- A short reasoning sentence ("you bought X in March, Y is the natural follow-up").
- A short "why ours" line if a competitor offers something similar (we already extract competitor catalogs).
- Expiration timestamp clamped to the policy's `expiration_max_days`.

Durable, addressable, reusable across the campaign emails, voiceover, and landing snippet without re-running the model.

### Freedom-to-Operate: the offer policy envelope

Brands give the AI a budget envelope. Inside it, the LLM has full taste. Outside, the output gets clamped and the over-attempt is logged. This is the difference between a curated 5-rule library (too rigid) and free-form LLM output (could hallucinate 90% off coupons).

**Envelope shape (lives on `Brand`, optional override on `Segment`):**

```
max_discount_pct: int                # e.g. 25
allowed_discount_types: list[str]    # ["percent", "fixed_amount", "free_shipping", "bogo"]
allow_bundles: bool
max_bundle_size: int                 # e.g. 3
allowed_addons: list[str]            # ["free_returns", "gift_wrap", "expedited_shipping"]
expiration_max_days: int             # offers must expire within N days
max_total_redemptions: int           # campaign-level cap
forbid_urgency_language: bool        # for brands that hate "act now / limited time"
```

**Two-stage enforcement:**
1. **Pre:** envelope rendered into the system prompt as a hard constraint.
2. **Post:** validator clamps output. If the LLM returned 30% in a 25% brand → clamp to 25%. If 4 products in a 3-cap → drop the lowest-margin extra. If a forbidden discount type → fall back to free shipping. Every clamp event emits `OFFER_POLICY_CLAMPED` to the bus and renders in the trust dashboard.

**No per-customer overrides.** Segment-or-brand only. Per-customer is a slippery slope to manual ops and breaks the "AI within authority" narrative.

---

## Data-model deltas

Additive only. No migrations of existing tables.

- **`Brand`** gains `offer_policy: dict` (the envelope shape above). Default-fill on brand creation; editable via Settings.
- **`Segment`** gains `offer_policy_override: dict | None`. Effective policy = `brand.offer_policy` shallow-merged with `segment.offer_policy_override`.
- **`Campaign`** (already exists) gains:
  - `target_kind: "customer" | "segment"`
  - `target_id: str`
  - `trigger: str` (`cart_abandoned` | `subscription_lapsed` | `new_arrival_in_category` | `manual`)
  - `status: "draft" | "scheduled" | "sending" | "done"`
- **`CampaignTouch`** (new): one row per planned step. `campaign_id, step_index, kind ("email"|"video"|"landing"), scheduled_at, content_json, send_id (FK to EmailSend when sent), render_cache_key`.
- **`Offer`** (new): `id, brand_id, customer_id?, segment_id?, product_ids (json), rule_json, copy_json, expires_at, policy_clamps (json — list of fields the validator clamped, for telemetry)`. Either `customer_id` or `segment_id` must be set, never both.
- **`VideoRender`** (new): `id, brand_id, customer_id, campaign_id, touch_id, voice_model_id, script_text, audio_url, video_url, status, cache_key UNIQUE`. Cache lookup by `(customer_id, campaign_id, touch_id)`.

Events (`backend/app/events/types.py`):
`CAMPAIGN_PLANNING, CAMPAIGN_PLANNED, CAMPAIGN_TOUCH_SCHEDULED, CAMPAIGN_TOUCH_SENT, OFFER_GENERATED, OFFER_POLICY_CLAMPED, VIDEO_RENDER_REQUESTED, VIDEO_RENDER_DONE`.

---

## Services

- **`services/audience/campaign_planner.py`** — `plan_campaign(brand, target_kind, target_id, trigger) -> CampaignPlan`. PII-redact the brief once. For individual targets, makes ONE LLM call returning `{touches: [{kind, email_body?, voiceover_script?, ...}], offer}`. For segment targets, returns the existing template-style output. Rehydrate per field. Persist `Campaign` + `CampaignTouch` + `Offer` rows.
- **`services/audience/offer_builder.py`** — `build_offer(brand, target) -> Offer`. Computes effective policy (brand merged with segment override), passes envelope into the LLM as a hard constraint, runs the validator post-hoc, emits `OFFER_POLICY_CLAMPED` for any clamps. Exposed standalone as "generate offer" button on a customer/segment row.
- **`services/audience/policy_validator.py`** — pure function `clamp(offer_dict, policy_dict) -> (clamped_offer, clamp_log)`. Stateless, easy to unit-test. Drop-lowest-margin for bundle overflow, fall back to free shipping for forbidden types.
- **`services/audience/triggers.py`** — light dispatcher that watches `CustomerEvent` inserts on the existing event bus for `cart_abandoned` / `subscription_lapsed` / new product launches in someone's top category, and creates a draft `Campaign`. Per-rule toggle. Not a real cron.
- **`services/video_gen/voiceover.py`** (new, lives in existing `video_gen/`) — `render_voiceover(script, voice_model_id) -> audio_url` then `mux_audio_onto_template(audio_url, template_id, customer_id) -> video_url`. Idempotent on `cache_key`. **Falls back to a default TTS voice** if `voice_model_id` is null or the fine-tune isn't ready yet — never blocks the demo on the voice-finetune workstream.
- **`services/pii/regex_redactor.py`** — extend to OpenAI Privacy Filter's 8 categories (adds `URL`, `DATE`, `ACCOUNT_NUMBER`, `SECRET`). Cite Privacy Filter in the docstring as inspiration. No new dependency.

All routed through the existing event bus. No env-mode branching. (Per `feedback_event_first_architecture.md`.) Voiceover script and email body share the **same redactor pass** — never a separate "quick" path that bypasses the shield.

---

## API additions

- `POST /api/audience/campaigns/plan` `{target_kind, target_id, trigger?}` → returns the planned campaign with all touches + bundled offer.
- `POST /api/audience/campaigns/{id}/launch` → flips status to `scheduled`, dispatches first touch (and triggers any `kind=video` renders for that touch).
- `POST /api/audience/touches/{touch_id}/render-video` → on-demand voice+video render for preview. Idempotent via `VideoRender.cache_key`.
- `POST /api/audience/offers` `{customer_id|segment_id}` → standalone offer generation, runs the same envelope clamp.
- `GET /api/audience/campaigns?target_id=…` → list.
- `GET /api/brands/{id}/offer-policy` / `PUT /api/brands/{id}/offer-policy` → the envelope sliders.
- `GET /api/segments/{id}/offer-policy-override` / `PUT /api/segments/{id}/offer-policy-override`.
- `GET /api/audience/policy-clamps?brand_id=…` → trust dashboard feed (every time the validator clamped the LLM's output).

---

## UX — the demo spine

Four panels, all under the existing **Audience** tab. No new top-level nav.

**1. Customer feed → "Generate 1:1 campaign"**
Click a row → drawer opens with:
- **PII shield bar** at top: "12 spans redacted before model call: 3 NAME, 2 EMAIL, 1 PHONE, …" Clickable to open the "what the LLM saw" inspector.
- **Campaign storyboard:** 3–5 touch cards in a horizontal strip. Each card is a real preview — emails render the HTML, the video card has a Play button that triggers the on-demand render with a 2–3s shimmer.
- **Voiceover panel:** the spoken script in a text box, the brand-voice indicator (or "Default TTS — voice fine-tune still training"), a Play button.
- **Offer card** on the right: products, discount rule, expiration, reasoning. A small badge if any field was clamped by the policy validator.
- **Send all** button. SMTP/Klaviyo dispatcher stubbed with a logger.

**2. Segment view → "Generate group campaign"**
- One templated multi-touch campaign for the whole segment. `{customer_name}` merge tag style.
- The "Override offer policy for this segment" toggle is here. When on, the segment-specific envelope sliders appear inline.
- No 1:1 fanout — that's what the individual-customer flow is for.

**3. Triggers panel**
A simple list of "rules": "When a customer abandons cart > €50, plan a 3-touch campaign within 2 hours." Toggle on/off. Recent fires below.

**4. Brand Settings → "Offer Policy" (new section)**
The envelope sliders. `max_discount_pct`, allowed types, bundle cap, expiration window, urgency-language toggle. **Trust dashboard** below: a feed of every recent policy clamp ("AI proposed 30%, clamped to 25% on Lapsed VIPs · 14 minutes ago"). This is the "AI within authority" pitch made visible.

---

## Demo script (90 seconds)

1. Open Audience → click "Sync mock CRM" (existing). Feed populates with customers + events + product catalog.
2. Click a customer with a cart-abandoned event. Drawer opens. Point at the PII shield bar — "12 spans redacted before any model call." Click it briefly to show the inspector: redacted brief on the left, rehydrated output on the right.
3. Walk the storyboard left to right: hook email, reminder email, offer email. Click the **video touch** — 2-second shimmer, then the personalized clip plays with the brand's voice reading the recipient's name and a recent purchase. **This is the wow.**
4. Cut to Brand Settings → Offer Policy. Drag `max_discount_pct` from 25 down to 10. Cut back to a customer and re-generate the campaign. The offer card now shows 10% with a "policy clamped from 18% → 10%" badge. Trust-dashboard ticker logs the clamp.
5. Open Triggers panel → flip "Cart-abandoned auto-plan" on. Inject a fake cart-abandoned event from dev tools. A new draft campaign appears in the feed within seconds, all PII redacted, all voice-personalized.
6. Closing line: "Google DLP shields the data. The LLM has freedom inside the brand's policy envelope. Every personalization is one redacted brief — coherent across email, voice, and offer."

---

## What we are NOT doing

- Real ESP integration. EmailSend logging is enough for the demo.
- Real cron / queue. Triggers fire off the in-process event bus.
- Re-doing PII detection. Existing redactor stays; only the regex fallback is widened.
- A new "Campaigns" tab. Lives inside Audience.
- Editing `services/finetune/`, `services/peec/`, `services/kanban/` — out of scope.

---

## Decisions locked (2026-04-26)

1. **Triggers:** `cart_abandoned`, `subscription_lapsed`, `new_arrival_in_category`, `manual`.
2. **Video:** on-demand render, voiceover-driven personalization. The script that the brand voice speaks is per-customer. Cached by `(customer_id, campaign_id, touch_id)`. Falls back to default TTS if the brand-voice fine-tune isn't ready.
3. **Group flow:** group target = one segment-level multi-touch campaign with `{customer_name}` merge tags. No 1:1 fanout. The 1:1 wow lives in the individual-customer flow.
4. **Offer rules:** "Freedom-to-Operate" envelope on `Brand`, override on `Segment`. LLM has taste inside the envelope; validator clamps anything outside and logs it. No curated library, no free-form output.

## Cross-team dependency

The voiceover work depends on the **Agent Voice Fine-tuning** workstream (`services/finetune/`, `stores/voiceModelStore.ts`). Plan posture: **never block on it.** `services/video_gen/voiceover.py` accepts `voice_model_id = None` and falls back to a default TTS voice with a UI label ("Default voice — brand fine-tune in progress"). The fine-tune team can light up real brand voices independently; the campaign feature ships either way.

---

## Effort sketch (not a commitment)

Roughly four parallel workstreams that can run in background agents:

- A: `Campaign` / `CampaignTouch` / `Offer` models + migrations + events (1 agent).
- B: `campaign_planner.py` + `offer_builder.py` services + the redactor extension (1 agent).
- C: API routes + `triggers.py` (1 agent).
- D: Drawer storyboard UI + group fanout feed (1 agent).

Per `feedback_no_time_boxing.md` — no hour estimates here.

---

## Next move

Confirm the four open questions, and I'll launch the four background agents in parallel.
