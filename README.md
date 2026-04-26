# Brand Autopilot

An AI marketing co-founder for early-stage brands. Built for the **Big Berlin Hack 2026** + the parallel **Peec MCP Challenge**.

You onboard once. The agent learns your brand — voice, products, competitors, audience — and then runs your weekly marketing: GEO-optimized content, brand-consistent images, short-form video storyboards, 1:1 email campaigns, and predicted lift on AI-search visibility, all grounded in real Peec data.

> **Vision in one line:** the marketing function for early-stage brands, run by an agent that knows them.

The full vision narrative lives in [`docs/VISION.md`](./docs/VISION.md). What follows describes what's actually in this repo today.

---

## What's built (current state)

The hackathon scope is being threaded as a working demo spine — onboarding → home → first campaign → audience-aware follow-ups. The repo is monolithic by design (one FastAPI backend, one Vite frontend, one Remotion subproject) so the demo can swap between brands mid-run.

### Backend (`backend/`)

FastAPI app with an event-bus core. Every feature listens on or emits events — no duplicated paths, no env-mode branches in feature code.

| Area | Module | What it does |
| :--- | :----- | :----------- |
| Event bus | `app/events/` | `pyee`-backed pub/sub. Single source of truth for cross-feature wiring. |
| Onboarding | `app/api/onboarding.py`, `app/services/onboarding/` | Site scrape (Playwright + Trafilatura) → brand extraction → palette + logo + voice profile. |
| Agent loop | `app/services/agent/` | Chat-driven planner. Pulls Peec snapshots, drafts content in brand voice, predicts lift, streams progress over SSE. |
| Audience | `app/services/audience/` | CRM connect (HubSpot Private App), segmentation, offer/policy validation, shop-event triggers, 1:1 personalization, HTML email rendering. |
| Peec integration | `app/services/peec/` | Both the REST client and the MCP client (HTTP + auth) used for the Peec MCP Challenge. |
| GEO | `app/services/geo/` | Gap detection on visibility data, channel playbook scoring. |
| Video gen | `app/services/video_gen/`, `frontend/remotion/` | Storyboard → cast/scene/frame generation → critic + improver loop → Remotion render via subprocess. |
| Pioneer fine-tune | `app/services/finetune/` | Per-brand Gemma voice training on Pioneer / Fastino Labs (with 90s simulator fallback when no key). |
| Asset library | `app/services/assets/`, `app/services/asset_describe/`, `app/services/image_edit/` | Generated + uploaded assets, captions, edits via Nano Banana Pro. |
| Pipelines | `app/services/pipeline/` | Trigger → executor for autonomous mode (cron + event-driven). |
| Research / Brand book | `app/services/research/`, `app/services/brand_book/` | Competitor intel + the persistent brand-knowledge doc the agent reads from. |
| Persistence | `app/db/`, SQLite (local) or Supabase Postgres (`DEPLOY_MODE=supabase`) | Same models both modes; storage either local FS or Supabase Storage. |
| LLMs | `app/services/llm/client.py` | Gemini (Vertex AI Express Mode) for text + Nano Banana Pro for images. |

### Frontend (`frontend/`)

Vite + React 19 + TypeScript + Tailwind v4 + Zustand. SSE-driven; the UI mirrors the backend event bus through `src/events/bus.ts`.

| Surface | Where |
| :------ | :---- |
| Onboarding flow | `src/onboarding/` |
| Home / agent session | `src/components/AgentSession.tsx`, `src/components/Dashboard/` |
| Storyboard + video | `src/components/Storyboard.tsx`, `src/stores/storyboardStore.ts` |
| Audience pane (CRM, segments, customers, triggers, offers) | `src/components/audience/` |
| Asset / research / GEO panels | `src/components/Dashboard/` + matching stores in `src/stores/` |

### Remotion subproject (`frontend/remotion/`)

Standalone Remotion project rendered via subprocess from the FastAPI backend. Independent `package.json` / `tsconfig.json` — do not share deps with the Vite app.

---

## Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2, `pyee`, MCP SDK, Playwright, Pillow, `google-genai` (Gemini), `yt-dlp`
- **Frontend:** React 19, TypeScript, Vite 8, Tailwind v4, Zustand, `motion`, `mitt`
- **Video:** Remotion (Bun or Node)
- **Data:** SQLite locally, Supabase (Postgres + Storage) when `DEPLOY_MODE=supabase`
- **Models:** Gemini 3 Flash (text), Nano Banana Pro (images), Gemma via Pioneer / Fastino Labs (per-brand voice fine-tune)
- **Partners wired:** Peec (REST + MCP), HubSpot (CRM), Pioneer / Fastino Labs (fine-tune)

---

## Run it locally

### Prerequisites

- **Python 3.11+**
- **Node 20+** and **Bun** (recommended) or npm
- **ffmpeg** on `$PATH` (used by the voiceover/transitions step in video gen)
- One required API key: **Gemini** (Vertex AI Express Mode). Everything else has a fallback.

### Quick start (3 terminals)

```bash
# 1) Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp ../.env.example .env       # then fill in at minimum GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000

# 2) Frontend
cd frontend
bun install                    # or: npm install
bun run dev                    # http://localhost:5173

# 3) Remotion (only if rendering video)
cd frontend/remotion
bun install
# Backend invokes this on /api/video/render:
# bunx remotion render src/index.ts MarketingVideo out.mp4 --props=props.json
```

The backend `lifespan` hook applies migrations, starts the Playwright browser pool, recovers orphaned fine-tune jobs, and registers the pipeline scheduler. First boot creates `brand_autopilot.db` (SQLite) and the `./storage` directory automatically.

### Sanity check the install

```bash
curl http://localhost:8000/api/health        # → {"status":"ok"}
curl http://localhost:8000/openapi.json | jq '.paths | keys' | head
```

Open `http://localhost:5173` and run through onboarding once — that exercises Playwright (site scrape), Gemini (extraction), and the event bus end-to-end.

---

## API keys & where to get them

Set in `backend/.env` (see [`.env.example`](./.env.example)) unless noted.

### Required

| Key | Purpose | Where to get |
| :-- | :------ | :----------- |
| `GEMINI_API_KEY` | Single key powers Gemini text (3 Flash / 3 Pro), image (Nano Banana Pro), video (Veo 3.1 lite/fast), and TTS (3.1 Flash TTS). Vertex AI Express Mode — no project/location setup. | <https://aistudio.google.com/apikey> |

### Optional (graceful degradation)

| Key | What it unlocks | Without it |
| :-- | :-------------- | :--------- |
| `PEEC_API_KEY` | Live AI-search visibility snapshots, competitor radar, GEO gap detection grounded in real data. | GEO panel + competitor radar fall back to deterministic fixture data so the demo flow still runs. |
| `PEEC_PROJECT_ID` | Pin Peec calls to one project (otherwise the first project on the key is used). | Auto-selects first project. |
| `TAVILY_API_KEY` | Web search + extraction for the research leg (onboarding research, agent loop grounding). | `gather_brand_context` is a no-op; agent drafts skip web grounding. |
| `PIONEER_API_KEY` | Real per-brand Gemma/Qwen voice fine-tune via Pioneer / Fastino Labs. | 90-second in-process simulator emits identical events so the demo flow still works. |
| `HUBSPOT_*` (per-brand, not env) | Real CRM contacts, products, deals for audience segmentation + 1:1 campaigns. Token entered in the **Connect CRM** modal on the audience page. | Deterministic sample-data CRM provider (~50 fake contacts across 4 segments). |
| `SUPABASE_URL` + `SUPABASE_KEY` | Hosted Postgres + Storage when `DEPLOY_MODE=supabase`. | Local SQLite at `./brand_autopilot.db` and FS storage under `STORAGE_DIR`. |

**Where to sign up:**

- Peec — <https://app.peec.ai> → API Keys (also see `docs/PEEC_MCP_INTEGRATION.md` for the MCP track setup)
- Tavily — <https://app.tavily.com> (free: 1,000 credits/month)
- Pioneer / Fastino Labs — <https://labs.fastino.ai> (free: $75 credit ≈ 5 trainings)
- HubSpot Private App — Settings → Integrations → Private Apps → Create. Required scopes: `crm.objects.contacts.read`, `crm.objects.products.read`, `oauth`. Optional: `events.read` (email opens/clicks).
- Supabase — <https://supabase.com>, project URL + anon key

---

## Rate limits & quotas to know

The defaults in this repo are tuned to the **free tier** of each provider so the demo won't melt during a contest weekend. If you hit a 429, lower the relevant concurrency knob below before raising the tier.

### Gemini API (the main bottleneck)

Per-model RPM / concurrency for the preview models we use (Gemini API, paid tier):

| Model | Where used | Limit | Notes |
| :---- | :--------- | :---- | :---- |
| `gemini-3-flash-preview` | Agent loop drafts, voice extraction, segmentation, brief reverse-engineering | High RPM (tier-dependent) | Corpus builder semaphores at **24 parallel** calls (`_REVERSE_BRIEF_PARALLELISM` in `corpus_builder.py:56`) — drop to 8 if you're on the free tier. |
| `gemini-3-pro-preview` | Storyboard *plan* (narrative arc, cast bible, scene direction) | Lower RPM than Flash | Fires once per `/api/video/suggest` call. |
| `nano-banana-pro-preview` | All image generation (hero shots, social cards, brand assets) | Per-image cost; tier-dependent RPM | Brand-conditioned — passes logo + reference images. |
| `veo-3.1-lite-generate-preview` | Default per-scene video clip (4–6 s) | **10 RPM, 10 concurrent**, $0.05/s @ 720p | Fits the 6-parallel storyboard pattern. |
| `veo-3.1-fast-generate-preview` | Quality / hero scene render | Same caps, $0.10/s | Used when `quality="hero"` on the request. |
| `gemini-3.1-flash-tts-preview` | Voiceover narration | Tier-dependent | 24 kHz PCM mono → wrapped to WAV → ffmpeg-muxed onto the mp4. |

Authoritative quotas: <https://ai.google.dev/gemini-api/docs/rate-limits>

Tip for the demo: leave **`enable_veo_transitions=True`** off (set false) if you're on a tight Veo budget — each AI-decided bridge adds another Veo call (~30–60 s of latency).

### Other providers

| Provider | Limit | Source |
| :------- | :---- | :----- |
| **Peec API** | Generous for partner / contest keys; per-project. | <https://app.peec.ai/api-keys> |
| **HubSpot Private App** | **100 requests / 10 seconds** (=600 RPM) per app, plus a daily cap by account tier. | <https://developers.hubspot.com/docs/api/usage-details> |
| **Tavily** | Free: 1,000 credits/month (≈ 1 credit per basic search, 2 per `advanced`). We default to `advanced` for the agent loop, `basic` for onboarding (`tavily_default_depth` in `config.py`). | <https://docs.tavily.com> |
| **Pioneer / Fastino** | Free trial: $75 credit ≈ 5 trainings. Polling: `pioneer_client.py` waits with backoff. | <https://labs.fastino.ai> |
| **Playwright (site scrape)** | Self-imposed via the browser pool — one shared headless Chromium. No external limit, but be polite to target sites. | — |

### When you do hit a rate limit

The Veo path retries with jittered backoff (`scene_gen.py:504`). For everything else, the agent surfaces 429s as failed events on the bus — they show up in the UI as a red step you can retry. Don't paper over them with sleeps; lower concurrency or upgrade the tier.

---

## Configuration switches

All config lives in `backend/.env` (see [`.env.example`](./.env.example)) and is loaded via `app/config.py` (Pydantic settings). Notable switches:

| Var | Default | Effect |
| :-- | :------ | :----- |
| `DEPLOY_MODE` | `local` | `local` = SQLite + FS storage. `supabase` = Postgres + Supabase Storage. No code branching beyond `app/db/session.py` and the storage mount in `app/main.py`. |
| `DATABASE_URL` | `sqlite:///./brand_autopilot.db` | When `DEPLOY_MODE=supabase`, set to the Supabase Postgres URL. |
| `STORAGE_DIR` | `./storage` | Local FS path for generated images / videos. Mounted at `/api/storage/*`. |
| `SERVER_BASE_URL` | `http://localhost:8000` | Used to rewrite `/api/storage/...` into absolute URLs the Remotion subprocess can fetch over HTTP (headless Chromium can't read arbitrary `file://` paths). |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | Override the text model. |
| `GEMINI_PLANNING_MODEL` | `gemini-3-pro-preview` | Override the heavier reasoning model used once per storyboard plan. |
| `GEMINI_IMAGE_MODEL` | `nano-banana-pro-preview` | Override image model. |
| `VEO_FAST_MODEL` / `VEO_QUALITY_MODEL` | `veo-3.1-lite-generate-preview` / `veo-3.1-fast-generate-preview` | Per-scene video models. |
| `ENABLE_VEO_TRANSITIONS` | `true` | When on, the editor opts into Veo bridges between scenes (~30–60 s render, extra cost per bridge). Turn off for cheap/fast renders. |
| `TAVILY_DEFAULT_DEPTH` | `advanced` | `basic` is half-cost. Onboarding overrides to `basic` for parallel calls. |
| `TAVILY_MAX_RESULTS` | `6` | Snippets per query passed to the LLM (Tavily caps at 20). |

### What runs without any optional keys

A clean install with **only `GEMINI_API_KEY`** still gives you: full onboarding, agent chat, brand voice extraction, image generation, video storyboards + Remotion render, and the audience pane on sample-data CRM. Peec / Tavily / HubSpot / Pioneer all gate cleanly — features are visibly degraded but no surface throws.

---

## Useful endpoints + scripts

```bash
# Live event stream (SSE) — every cross-feature event passes through here
curl -N http://localhost:8000/api/events/stream

# Manually trigger a fine-tune from CLI (uses the same orchestrator path)
python -m app.scripts.run_finetune --brand-id <uuid>

# Type-check the Remotion subproject before a render
cd frontend/remotion && bunx tsc --noEmit
```

---

## Repo layout

```
.
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers (one per feature)
│   │   ├── services/       # Business logic, grouped by domain
│   │   ├── events/         # Event bus + typed event payloads
│   │   ├── db/             # SQLAlchemy models + session/migrations
│   │   ├── config.py       # Pydantic settings (env-driven)
│   │   └── main.py         # App + lifespan + router wiring
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/     # Onboarding, dashboard, audience, storyboard
│   │   ├── stores/         # Zustand stores, one per domain
│   │   ├── events/         # SSE → bus bridge
│   │   ├── effects/        # chatBridge etc.
│   │   ├── lib/            # Typed API clients
│   │   └── onboarding/     # Onboarding flow screens
│   ├── remotion/           # Standalone Remotion renderer
│   └── package.json
├── docs/                   # CHANNEL_PLAYBOOK, COPY_MARKETING, CORPORATE_IDENTITY,
│                           # DEEP_PALETTE, PEEC_MCP_INTEGRATION, PIONEER_FINETUNING, VISION
├── big_berlin_hack_manual.md
├── .env.example
└── README.md
```

---

## Architecture notes

- **Event-first.** Every cross-feature interaction goes through `app/events/`. If you find yourself adding a "mode" check inside a feature, route it through an event instead.
- **Server-authoritative + resumable.** SSE streams from `/api/events/stream`. The frontend store reconciles from server state on connect — no hybrid local/server truth.
- **Graceful degradation.** Every external partner has a deterministic fallback so the demo flow keeps running without keys (Peec → fixture, HubSpot → sample CRM, Pioneer → 90s simulator).
- **One source of truth per field.** Brand profile, audience segments, and asset library each live in exactly one place; everything else points there.

---

## Hackathon submission

Same repo qualifies for both contests:

- **Big Berlin Hack** — full agent demo
- **Peec MCP Challenge** — `app/services/peec/mcp_*` is the dedicated MCP integration

Aikido is wired as a security hygiene tool (not counted toward the 3 partner technologies); Pioneer fine-tuning layers on top.
