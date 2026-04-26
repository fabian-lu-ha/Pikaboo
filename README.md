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

- Python 3.11+
- Node 20+ and Bun (recommended) or npm
- A Gemini API key (Vertex AI Express Mode)
- Optional: Peec API key, HubSpot Private App token, Pioneer key — all degrade to deterministic fallbacks if missing

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp ../.env.example .env   # then fill in keys
uvicorn app.main:app --reload --port 8000
```

The `lifespan` hook applies migrations, starts the Playwright browser pool, recovers any orphaned fine-tune jobs, and registers the pipeline scheduler.

### Frontend

```bash
cd frontend
bun install        # or: npm install
bun run dev        # vite on http://localhost:5173
```

### Remotion (only if rendering video)

```bash
cd frontend/remotion
bun install
# the backend invokes:
# bunx remotion render src/index.ts MarketingVideo out.mp4 --props=props.json
```

---

## Configuration

All config lives in `.env` (see [`.env.example`](./.env.example)). Notable switches:

- `DEPLOY_MODE=local|supabase` — swaps SQLite ↔ Supabase Postgres + Storage. No code branching beyond `app/db/session.py` and the storage mount in `app/main.py`.
- `STORAGE_DIR` — local FS path for generated assets when `DEPLOY_MODE=local`.
- `GEMINI_API_KEY` — required for the agent loop, voice extraction, and image generation.
- `PEEC_API_KEY` — required for live Peec snapshots; otherwise the GEO panel falls back to fixture data.
- `HUBSPOT_*` — set per-brand in the "Connect CRM" modal, not in env. Without it, audience falls back to the deterministic sample-data provider.
- `PIONEER_API_KEY` — without it, voice fine-tunes run a 90-second simulator that emits the same events.

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
