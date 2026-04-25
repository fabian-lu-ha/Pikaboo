# Peec MCP Integration — Research + Plan

> **Why this doc exists.** Brand Autopilot is being submitted to two contests on the same weekend: the Big Berlin Hack 2026 "0 → 1 AI Marketer" track (€2,500) **and** Peec AI's parallel **MCP Challenge** (US$5,000 grand + 3 × US$1,500 category prizes, total US$10K+, deadline **2026-04-26**). The agent loop currently uses a mock target‑prompts function and a deterministic GEO‑heuristic lift estimator. To win the Peec prize we need real Peec data driving the loop end‑to‑end. This file is the research‑and‑plan that the implementation work follows.

---

## 1. What Peec AI is, in 2026 reality

**Peec AI** is a Berlin‑based **Generative Engine Optimization (GEO)** analytics platform — "the SEO dashboard for AI search." It tracks how a brand shows up across answer engines (ChatGPT, Perplexity, Gemini, Google AI Overviews, Claude, Copilot, Grok) on the prompts that matter to that brand's category, and it scores three dimensions:

- **Visibility** — how often the brand is mentioned in answers to a tracked prompt
- **Position** — where the brand ranks among other brands cited in those answers
- **Sentiment** — whether the description is positive, neutral, or negative
- **Share of Voice** — competitor‑relative visibility on the same prompts
- **Source / Citation analysis** — *which domains* the LLMs cite when answering a prompt (the GEO equivalent of backlinks)

**Funding & momentum (verified).** On **2025-11-17** Peec announced a **$21M Series A** led by Singular (with Antler, Combination VC, identity.vc, S20), bringing total funding to $29M and (per CEO Marius Meiners) tripling valuation to >$100M. ARR >$4M in 10 months, ~1,300 customers, ~300 new customers/month, NYC office planned for Q2 2026. ([TechCrunch — 2025-11-17](https://techcrunch.com/2025/11/17/as-consumers-ditch-google-for-chatgpt-peec-ai-raises-21m-to-help-brands-adapt/), [Peec blog](https://peec.ai/blog/we-raised-21m-series-a-to-help-brands-win-in-ai-search))

**API + MCP shipped.** Peec shipped a public REST API (currently positioned as Enterprise/paid‑plan; beta) and on top of it a hosted **MCP server** at `https://api.peec.ai/mcp`, available on **all paid plans** (no Enterprise gate). Streamable HTTP transport. Read‑only at launch with select write ops behind opt‑in flags. ([Peec MCP launch post](https://peec.ai/blog/peec-ai-mcp), [docs index](https://docs.peec.ai/llms.txt))

---

## 2. What the Peec MCP Challenge is asking for

Source: [https://peec.ai/mcp-challenge](https://peec.ai/mcp-challenge)

**Window:** 2026-04-20 → 2026-04-26 (10‑day sprint, submissions close 2026-04-26 — i.e. *this Sunday*).

**Prize structure (verified):**
- **Grand Prize:** US$5,000 cash + 1 year Peec Pro
- **3 × Category Winners:** US$1,500 + 6 months Peec Pro (categories: Content Optimization, Competitive Analysis, Reporting Automation — Peec assigns the category for you)

**Judging weights (verbatim from the challenge page):**
| Criterion | Weight |
|---|---|
| Usefulness | **40%** |
| Creativity | **30%** |
| Execution Quality | **20%** |
| Community Impact | **10%** |

**What counts as a valid entry:** "a *repeatable workflow* powered by Peec MCP that solves a real problem." One‑off prompts or screenshots alone do **not** qualify. Examples: automated reports, competitive monitoring, content audits.

**Submission mechanics:** Tally form. No requirement to make the work public, but `#BuiltWithPeec` posts boost the Community Impact score.

**Judges:** Lily Ray, Ethan Smith, Malte Landwehr.

**Eligibility:** Open globally, prizes paid USD. Must have a Peec account; the challenge gives a 30‑day free trial (extended from the standard 14‑day) but a credit card is required at signup (no charge during trial).

**What "best integration" means here** (paraphrased from the rules — see §7 for our concrete take): a workflow that uses Peec MCP as the *spine* of an end‑to‑end loop a marketer would actually re‑run weekly — not a UI that calls one tool once.

---

## 3. What Peec's MCP server exposes

Two surfaces exist, and we should call them out clearly because they are not the same thing:

### 3a. Official Peec MCP server (hosted, recommended)

- **Endpoint:** `https://api.peec.ai/mcp`
- **Transport:** Streamable HTTP
- **Auth:** OAuth 2.0 browser consent flow when used from a desktop client (Claude Desktop / Cursor). Sessions persist; account‑switching supported. For our **server‑to‑server** use case (a FastAPI backend), OAuth is awkward — we will use the **Peec REST API directly with the `x-api-key` header** as our primary path, and treat MCP‑over‑HTTP as a fallback (see §5 + §9). The MCP server is a *thin wrapper over the same REST API*, so this is not a feature regression; it just sidesteps the OAuth dance.
- **Status:** Read tools live; write tools (create/update brands, prompts, topics, tags) gated by org‑owner project access and `readOnlyHint:false` confirmations. Delete ops carry `destructiveHint: true`.
- **Built‑in slash commands / prompts:** Peec ships three guided prompt templates exposed via MCP — *brand visibility*, *competitive analysis*, *citation analysis*. These are usable from Claude Desktop directly, and they're a hint at the workflows the judges expect to see.

Sources: [Peec MCP launch blog](https://peec.ai/blog/peec-ai-mcp), [mcpservers.org listing](https://mcpservers.org/servers/docs-peec-ai-mcp-introduction).

### 3b. Community MCP wrapper — `mcp-server-peecai` (npm, by `thein-art`)

A community‑built node MCP server that wraps the Peec REST API with **31 tools**. It is **not** the official Peec server, but it's an excellent reference for the exact REST surface we'll be calling. ([repo](https://github.com/thein-art/mcp-server-peecai), [LobeHub mirror](https://lobehub.com/mcp/thein-art-mcp-server-peecai))

Auth is API key via env: `PEECAI_API_KEY`, optional `PEECAI_PROJECT_ID`, opt‑in writes via `PEECAI_ALLOW_WRITES=true`.

**Tool catalog (verified from the community wrapper — these mirror real REST endpoints):**

| # | Tool | Key parameters | Returns |
|---|---|---|---|
| **Reads — discovery** | | | |
| 1 | `list_projects` | `limit`, `offset` | project IDs, names, statuses |
| 2 | `list_brands` | `project_id`, `limit`, `offset` | brand names + domains tracked in the project |
| 3 | `list_prompts` | `project_id`, `topic_id?`, `tag_id?`, `limit`, `offset` | prompt messages, tags, topics, est. search volume |
| 4 | `list_tags` | `project_id`, `limit`, `offset` | category tag names |
| 5 | `list_topics` | `project_id`, `limit`, `offset` | topic groupings |
| 6 | `list_models` | `project_id`, `limit`, `offset` | AI model IDs + active flag |
| 7 | `list_model_channels` | `project_id`, `limit`, `offset` | channel IDs + active models behind each |
| 8 | `list_chats` | `project_id`, `start_date`, `end_date`, `brand_id?`, `prompt_id?`, `model_id?`, `model_channel_id?`, `limit`, `offset` | chat IDs with prompt / model refs |
| 9 | `get_chat_content` | `chat_id`, `project_id` | full message thread + sources (URLs, domains, citation counts), brands mentioned |
| 10 | `list_prompt_suggestions` | `project_id`, `topic_id?`, `limit`, `offset` | AI‑generated prompt suggestions |
| 11 | `list_topic_suggestions` | `project_id`, `limit`, `offset` | AI‑generated topic suggestions |
| **Reads — analytics (the load‑bearing ones for us)** | | | |
| 12 | `get_brands_report` | `project_id`, `dimensions[]`, `start_date`, `end_date`, `filters?` | per‑brand: `visibility`, `sentiment`, `position`, `share_of_voice`, `mention_count` |
| 13 | `get_domains_report` | `project_id`, `dimensions[]`, `start_date`, `end_date`, `filters?` | per‑domain: `retrieval_rate`, `citation_rate`, `classification` |
| 14 | `get_urls_report` | `project_id`, `dimensions[]`, `start_date`, `end_date`, `filters?` | per‑URL: `retrievals`, `citation_count`, `citation_rate`, `classification` |
| 15 | `get_url_content` | `url`, `project_id` | scraped markdown, title, classification, content_length |
| **Reads — query analysis** | | | |
| 16 | `search_queries` | `project_id`, `start_date`, `end_date`, `filters?`, `limit`, `offset` | the actual search queries LLMs ran behind tracked prompts |
| 17 | `shopping_queries` | `project_id`, `start_date`, `end_date`, `filters?`, `limit`, `offset` | shopping‑intent variant |
| **Writes (opt‑in via `PEECAI_ALLOW_WRITES=true`)** | | | |
| 18–20 | `create_brand`, `update_brand`, `delete_brand` | | brand CRUD |
| 21–23 | `create_prompt`, `update_prompt`, `delete_prompt` | | prompt CRUD (this is how we'd add a new prompt to track) |
| 24–26 | `create_tag`, `update_tag`, `delete_tag` | | tag CRUD |
| 27–29 | `create_topic`, `update_topic`, `delete_topic` | | topic CRUD |
| 30–31 | `accept_prompt_suggestion`, `reject_prompt_suggestion`, `accept_topic_suggestion`, `reject_topic_suggestion` | | suggestion workflow |

> **What I'm confident of vs. inferring.** Tool *names and parameter names* above come straight from the community server's README / Glama listing and from Peec's docs index. The exact return‑shape JSON keys are inferred from those sources — they may differ slightly when we hit the real API; treat them as pseudocode‑grade until first response is logged. Endpoints surfaced in [docs.peec.ai/llms.txt](https://docs.peec.ai/llms.txt) confirm the shape of `brands`, `prompts`, `topics`, `tags`, `chats`, `model channels`, `brand/domain/url reports`, `fanout search/shopping queries`, and `URL content scraping`.

### 3c. Underlying REST API (what we actually call)

- **Base:** `https://api.peec.ai`
- **Versioned path:** `/customer/v1/...`
- **Auth header:** `x-api-key: <key>`
- **Format:** JSON
- **Status:** beta (per docs — endpoints/payloads may shift)
- **Example (verified from docs):**

```bash
curl -X GET "https://api.peec.ai/customer/v1/prompts" \
  -H "x-api-key: $PEEC_API_KEY"
```

---

## 4. Auth + setup

**Decision: dual‑path, REST‑first.**

1. **Primary path — REST with `x-api-key`.** Simple, server‑friendly, no OAuth dance, identical data surface. Get a key at **[https://app.peec.ai/api-keys](https://app.peec.ai/api-keys)** after signup. Project‑scoped keys recommended for safety.
2. **Fallback / showcase path — MCP over Streamable HTTP.** We *also* wire a thin MCP client against `https://api.peec.ai/mcp` for the demo so we can honestly claim "Peec MCP integration" (the contest asks for MCP, not just Peec). The MCP client uses the same `x-api-key` header (the Peec MCP supports API‑key auth alongside the Claude‑Desktop OAuth flow per the community server's example; if it strictly requires OAuth in production, the REST path keeps us alive — see §9).

**Concrete steps for the user (to do now, before coding):**

1. Sign up at [peec.ai](https://peec.ai/pricing) using the **MCP Challenge link** to get the 30‑day trial (vs. the standard 14). Credit card required, no charge during trial.
2. Create one project and add the demo brand (we will use the same brand we're onboarding live in the demo — see §8).
3. Generate an API key at [app.peec.ai/api-keys](https://app.peec.ai/api-keys). **Project‑scoped** key.
4. Add to `backend/.env`:
   ```
   PEEC_API_KEY=...
   PEEC_PROJECT_ID=...      # default project for tool calls
   PEEC_BASE_URL=https://api.peec.ai
   PEEC_MCP_URL=https://api.peec.ai/mcp
   ```
5. Extend `app/config.py`:
   ```python
   peec_api_key: str | None = None
   peec_project_id: str | None = None
   peec_base_url: str = "https://api.peec.ai"
   peec_mcp_url: str = "https://api.peec.ai/mcp"
   ```

---

## 5. MCP client library in Python

Canonical 2026 SDK: **`mcp`** on PyPI ([`pypi.org/project/mcp`](https://pypi.org/project/mcp/)) — maintained by Anthropic, Python ≥3.10, async, supports stdio + SSE + Streamable HTTP. Install: `pip install "mcp[cli]"`.

**Streamable HTTP client with auth (the relevant call site for us):**

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(
    "https://api.peec.ai/mcp",
    headers={"x-api-key": settings.peec_api_key},
    timeout=30,
) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool(
            "get_brands_report",
            arguments={
                "project_id": settings.peec_project_id,
                "start_date": "2026-04-01",
                "end_date":   "2026-04-25",
                "dimensions": ["brand", "prompt"],
            },
        )
```

Source confirmation for the import path + headers kwarg: [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk), Python‑SDK [issue #998](https://github.com/modelcontextprotocol/python-sdk/issues/998), `streamablehttp_client(mcp_url, headers, timeout=120, terminate_on_close=False)` signature.

**For the demo we'll keep both paths thinly wrapped behind one service** (`app/services/peec/client.py`) with a method per tool we call — internally it can route to MCP or REST. This protects us from any auth surprise on Sunday morning.

---

## 6. Replacement plan — file‑by‑file

### NEW: `backend/app/services/peec/client.py`

Single module that wraps the Peec REST API (primary) and exposes a tiny sync‑async surface. Each method maps 1:1 onto a Peec tool, with the same name as the MCP tool for grep parity.

```python
class PeecClient:
    async def list_brands(self, project_id: str | None = None) -> list[dict]: ...
    async def list_prompts(self, project_id: str | None = None,
                           topic_id: str | None = None) -> list[dict]: ...
    async def get_brands_report(self, project_id: str | None = None,
                                start_date: str | None = None,
                                end_date: str | None = None,
                                dimensions: list[str] | None = None,
                                filters: dict | None = None) -> dict: ...
    async def get_domains_report(self, **kwargs) -> dict: ...
    async def get_urls_report(self, **kwargs) -> dict: ...
    async def list_chats(self, **kwargs) -> list[dict]: ...
    async def get_chat_content(self, chat_id: str,
                               project_id: str | None = None) -> dict: ...

def get_peec() -> PeecClient | None:
    """Returns None if PEEC_API_KEY isn't set — caller must degrade gracefully."""
```

Internals: `httpx.AsyncClient` with `x-api-key` header. Cached for the process lifetime. Each method returns plain dicts so the agent loop stays decoupled from Peec response shapes.

### NEW: `backend/app/services/peec/snapshot.py`

Domain logic that turns raw Peec calls into the two artifacts the agent needs:

```python
@dataclass
class PeecSnapshot:
    brand_id: str
    project_id: str
    fetched_at: datetime
    visibility: float                 # current overall visibility 0–100
    share_of_voice: float
    sentiment: float                  # -1..+1
    visible_on: list[VisiblePrompt]   # brand currently appears
    absent_from: list[AbsentPrompt]   # brand absent, competitor wins
    cited_domains: list[CitedDomain]  # which domains LLMs cite for our prompts

async def fetch_snapshot(brand: dict) -> PeecSnapshot | None: ...

def select_target_prompts(snap: PeecSnapshot, k: int = 3) -> list[TargetPrompt]:
    """Top-k prompts where the brand could realistically win + has highest absence."""
```

Selection heuristic for `select_target_prompts` (the *strategic* bit):
- score = `competitor_top_visibility * citation_overlap_with_owned_domains * (1 - own_visibility)`
- where `citation_overlap_with_owned_domains` = fraction of domains Peec lists as citations for this prompt that are *already cited for our brand on neighbouring prompts* (the "you have a credible shot" signal that's literally called out as the demo‑winning beat in the project vision doc).
- pick `k=3` highest‑scoring `absent_from` prompts.

### `app/services/agent/loop.py` — replace `_placeholder_target_prompts`

```python
# BEFORE
target_prompts = _placeholder_target_prompts(brand_data)

# AFTER
peec = get_peec()
peec_snapshot = None
if peec is not None:
    try:
        peec_snapshot = await fetch_snapshot(brand_data)
    except Exception as e:
        log.warning("peec snapshot failed, falling back to mock: %s", e)

if peec_snapshot:
    target_prompts = select_target_prompts(peec_snapshot, k=3)
    bus.emit(Events.AGENT_PEEC_DATA_FETCHED, {
        "campaign_id": campaign_id,
        "brand_id": brand_data["id"],
        "snapshot": peec_snapshot.to_event_payload(),  # see §6 events
        "target_prompts": [tp.to_dict() for tp in target_prompts],
    })
else:
    target_prompts = _placeholder_target_prompts(brand_data)  # graceful degrade
    bus.emit(Events.AGENT_PEEC_UNAVAILABLE, {
        "campaign_id": campaign_id,
        "reason": "no api key" if peec is None else "fetch failed",
    })
```

`target_prompts` becomes `list[TargetPrompt]` with shape `{prompt, current_rank, competitor_winning, top_cited_domains}` — the downstream draft prompts get richer context and the lift estimator gets a real baseline.

### `app/services/agent/lift.py` — augment, don't replace

Keep the deterministic GEO heuristic (it scores the *content* of the draft and is honest signal). Add an optional `peec_snapshot: PeecSnapshot | None` argument that:

1. Replaces the synthetic baseline ("`+8% baseline for new on-voice content`") with a real **per‑prompt baseline visibility** drawn from `snap.absent_from[i].current_visibility` (typically 0–10%).
2. Adds a new factor **"+X% from source‑overlap with prompt's top citations"** — for each draft, count how many of `snap.cited_domains` for the target prompts appear in the draft's hyperlinks/mentions. This is the GEO equivalent of "you cite the domains the LLMs already trust on this prompt", and it's the *credibility* line the demo script leans on.
3. Returns `factors[]` with `source: "peec"` tags so the UI can mark them as "from real data" vs. "from heuristic."

Function signature:

```python
def predict_lift(
    user_request: str,
    target_prompts: list[TargetPrompt],
    draft_bodies: list[str],
    peec_snapshot: PeecSnapshot | None = None,  # NEW
) -> dict: ...
```

### `app/services/onboarding/orchestrator.py` — fetch initial snapshot

After `ONBOARDING_COMPETITORS_SUGGESTED` (so we have brand + competitors persisted), kick off:

```python
peec = get_peec()
if peec is not None:
    bus.emit(Events.ONBOARDING_PEEC_FETCHING, {"brand_id": brand_id})
    try:
        snap = await fetch_snapshot(brand_data_dict)
        if snap is not None:
            with SessionLocal() as bdb:
                row = bdb.get(models.Brand, brand_id)
                row.profile = {**(row.profile or {}), "peec": snap.to_storage_dict()}
                bdb.add(row); bdb.commit()
            bus.emit(Events.ONBOARDING_PEEC_FETCHED, {
                "brand_id": brand_id,
                "snapshot": snap.to_event_payload(),
            })
    except Exception as e:
        log.warning("peec onboarding fetch failed: %s", e)
        bus.emit(Events.ONBOARDING_PEEC_FAILED, {"brand_id": brand_id, "error": str(e)[:240]})
```

Stored on `Brand.profile["peec"]` (the existing `profile = Column(JSON, default=dict)` already handles this — no migration needed).

### `app/events/types.py` — new events

```python
ONBOARDING_PEEC_FETCHING = "onboarding.peec_fetching"
ONBOARDING_PEEC_FETCHED  = "onboarding.peec_fetched"
ONBOARDING_PEEC_FAILED   = "onboarding.peec_failed"
AGENT_PEEC_DATA_FETCHED  = "agent.peec_data_fetched"
AGENT_PEEC_UNAVAILABLE   = "agent.peec_unavailable"
```

These flow through the existing pyee → SSE → mitt bridge unmodified — frontend just registers handlers.

### Frontend — new `PeecVisibilityCard` in AgentSession

**Location:** wherever `agent.step` events render today; this card should appear *before* the drafts, right after `agent.peec_data_fetched`.

**Content:**
- "Peec visibility snapshot — pulled live"
- Three rows of `visible_on` prompts with rank pills (e.g., "Rank 4 of 9 on *best CRM for B2B SaaS*").
- Three rows of `absent_from` with the *competitor who wins*, e.g., "**HubSpot** owns *best alternatives to Salesforce* — and 3 of its top 5 cited domains are already citing you on adjacent prompts."
- A small "(Peec live)" badge so judges can see at a glance that the number isn't a guess.

**Degradation:** if `agent.peec_unavailable` arrives instead, render the same card with mock data + a yellow "(Peec unavailable — degraded)" badge. We never crash the demo.

### Optional: `LiftCard` upgrade

Show the lift factors with "Peec source‑overlap" rows visually distinct (different chip color) from the heuristic rows. Tiny change but makes the lift estimate look earned.

---

## 7. What "best integration" looks like — the demo moment

The judging weights (Usefulness 40, Creativity 30, Execution 20, Community 10) tell us exactly what to maximize. **Usefulness** wins the prize, and usefulness here = "a marketer would re‑run this every Monday." So the demo arc must show that loop, with Peec at every load‑bearing step, not as side‑info:

1. **Onboarding** scrapes the brand → automatic Peec snapshot fetched and shown.
2. **Agent loop** asks Peec "where is this brand absent and a competitor wins?" → picks 3 *real* target prompts. (`select_target_prompts`)
3. **Drafts** are written *for those exact prompts*, with the prompt brief feeding the LLM messages — so the post is targeted, not generic.
4. **Lift estimator** grounds its baseline in the brand's *current* visibility on those prompts and quantifies source‑overlap with the top‑cited domains for the prompt — "3 of 5 domains the LLMs already trust for *best CRM* already cite you on adjacent prompts. You have a credible shot — projected lift 22%, confidence medium." (Vision doc literally calls this out as the demo‑winning beat.)
5. **Counter‑move (stretch):** when Peec's `get_brands_report` shows a competitor surging on a prompt week‑over‑week (delta visibility), the agent emits `competitor.surged` (event already in the codebase!) and *automatically drafts a counter‑piece* targeting that exact prompt. Surge → response in <10s on stage.

The honest line we own: **"Brand Autopilot is the only marketing agent whose every step — from prompt selection to draft brief to lift forecast — is grounded in real LLM‑answer‑engine data."** That's the Usefulness × Creativity sweet spot.

---

## 8. Hackathon‑acceptable scope cut (smallest shippable Sunday demo)

We have ~36 hours. Build only this:

**P0 (must ship — 4–6 hours of work):**
1. `app/services/peec/client.py` with **two** methods only: `get_brands_report` and `list_prompts`.
2. `app/services/peec/snapshot.py` with `fetch_snapshot` + `select_target_prompts`.
3. Wire into `agent/loop.py` to replace `_placeholder_target_prompts`. Emit `agent.peec_data_fetched`.
4. Frontend: render a single Peec snapshot card in AgentSession before drafts.

**P1 (if there's time — 2–3 hours):**
5. Wire snapshot fetch into onboarding, persist on `Brand.profile["peec"]`.
6. Augment `predict_lift` with the real baseline (drop the synthetic +8%).

**P2 (stretch, only if P0+P1 are green):**
7. Source‑overlap factor in `predict_lift` (uses `get_domains_report`).
8. Surge‑driven counter‑move using `competitor.surged` event.

**Skip for the hackathon:**
- Write tools (`create_prompt` etc.) — judges aren't grading two‑way sync.
- Looker connector talk track.
- Multi‑project / agency mode.

---

## 9. Risks + fallback

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Peec MCP endpoint requires OAuth and our API‑key header is rejected at `/mcp`** | medium | REST‑first design (§4) sidesteps this entirely. We still *call* the MCP server in a side‑process for the demo screenshot, but the loop's data source is REST. |
| **API key not provisioned in time** (signup/CC delays) | low | User has the form already. Sign up *first*, then code. If still blocked, we keep the deterministic mock with a **"(Peec unavailable)" badge** — UX intact, badge honest, no crash. |
| **Endpoints differ from what the community wrapper documents** (Peec API is in beta) | medium | All field access in `snapshot.py` does `.get(...)` with sensible fallbacks. Log raw responses to a debug file the first time we hit each endpoint so we can adjust fast on Sunday. |
| **Rate limits / latency at demo time** | medium | Cache the snapshot for the demo brand at a 60s TTL; pre‑fetch right before going on stage by triggering onboarding once. Worst case: serve last good snapshot from `Brand.profile["peec"]`. |
| **Project has no tracked prompts at demo time** | medium | Pre‑seed: in the Peec dashboard for the demo brand, manually add 8–10 high‑signal prompts the day before. (Peec also has prompt suggestions — `list_prompt_suggestions` — we can show that as a fallback.) |
| **Demo network failure** | low | Same `(Peec unavailable)` degraded badge — UX continues with the deterministic estimator. |

**Hard rule:** every Peec call site is `try/except` with a logged warning and a graceful fallback that emits `*_unavailable` rather than raising. The pipeline must never crash because Peec is slow/down.

---

## 10. Demo script (the lines the user reads on stage)

> "Brand Autopilot doesn't just write content — it knows *where you're losing*. This number" — *points at the Peec card* — **"isn't a guess. It's pulled live from Peec, the AI‑search visibility layer that just raised $21M to be the SEO dashboard for ChatGPT and Perplexity. Right now your brand is invisible on three prompts where HubSpot is winning — and three of HubSpot's top‑cited domains are already citing you on adjacent prompts. So the post our agent just drafted? It's not random. It's targeted at exactly those prompts, citing exactly those domains. Predicted lift, 22% — grounded in Peec's own source‑overlap data."**

Three sentences a judge will repeat back; one explicit "live from Peec" callout; one number tied directly to a Peec data point.

---

## Sources

- [TechCrunch — *As consumers ditch Google for ChatGPT, Peec AI raises $21M to help brands adapt* (2025-11-17)](https://techcrunch.com/2025/11/17/as-consumers-ditch-google-for-chatgpt-peec-ai-raises-21m-to-help-brands-adapt/)
- [Peec — *We raised $21M Series A to help brands win in AI search*](https://peec.ai/blog/we-raised-21m-series-a-to-help-brands-win-in-ai-search)
- [Peec — *Peec AI MCP* (launch blog)](https://peec.ai/blog/peec-ai-mcp)
- [Peec — *The Peec MCP Challenge* (contest page)](https://peec.ai/mcp-challenge)
- [Peec Docs — index `llms.txt`](https://docs.peec.ai/llms.txt)
- [Peec Docs — Authentication](https://docs.peec.ai/api/authentication)
- [Peec Docs — Welcome / metrics overview](https://docs.peec.ai/intro-to-peec-ai)
- [`thein-art/mcp-server-peecai` — community MCP server (GitHub)](https://github.com/thein-art/mcp-server-peecai)
- [LobeHub — Peec.ai MCP Server](https://lobehub.com/mcp/thein-art-mcp-server-peecai)
- [`mcp` Python SDK on PyPI](https://pypi.org/project/mcp/)
- [MCP Python SDK on GitHub (Streamable HTTP client API)](https://github.com/modelcontextprotocol/python-sdk)
- [MCP spec — Transports (Streamable HTTP)](https://modelcontextprotocol.io/docs/concepts/transports)
- [Python‑SDK issue #998 — passing Bearer token to MCP server](https://github.com/modelcontextprotocol/python-sdk/issues/998)
