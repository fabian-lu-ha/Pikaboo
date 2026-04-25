# Pioneer AI × Gemma Fine-Tuning for Brand Autopilot

> Research-only doc. Compiled 2026-04-25 (Saturday of Big Berlin Hack).
> Goal: turn the data we already collect on Brand Autopilot into a per-tenant
> Gemma model that drafts in the customer's exact voice, deployed via Pioneer AI.

---

## TL;DR (read this if you read nothing else)

- **Pioneer AI** is an *agentic* fine-tuning + adaptive inference platform from
  Fastino Labs, **launched April 21, 2026** (four days before the hackathon).
  It supports Gemma, Llama, Qwen, Nemotron, and GLiNER. You drive it with a
  prompt — it generates synthetic data, picks hyperparams, trains, evaluates,
  and deploys.
- **Hackathon prize**: €700 (Mac Mini cash value) for the *best use of
  Pioneer*. Finalists also get 1 month of Pioneer Pro (worth $40/mo).
- **Recommended Gemma size for us: Gemma 3 4B-it (instruction-tuned)** —
  big enough to hold our ~3 K-token brand context and emit clean
  JSON, small enough to LoRA-tune cheaply (~$35, ~6 h end-to-end on Pioneer
  Research mode).
- **Training data shape: JSONL with a `messages` array** (system / user /
  assistant chat format). This is what TRL, Unsloth, Hugging Face, and every
  current Gemma trainer expect. Pioneer hasn't published an official format
  spec, but its underlying stack is HF/TRL — the conversational-JSONL format
  is the safe bet.
- **Cold-start moat**: LoRA adapters + RAG *now*, full fine-tune *later* (after
  N≥30 approved drafts).
- **Hackathon scope cut**: ship the dataset builder + a "training kicked off
  on Pioneer" UI moment. Real adapter inference is post-hackathon — but
  *the dataset is the demo*.

---

## 1. What Pioneer AI is

Pioneer AI is the public-facing product of **Fastino Labs** (Palo Alto,
founded 2024, backed by Khosla / Insight / NEA / M12). It launched on
**21 April 2026** as "the first agent for fine-tuning and inference of
LLMs" — i.e. it is itself an LLM agent that drives the whole train-eval-deploy
loop, not just a hosted GPU rental.

### Two operating modes

| Mode | What it does | Best for |
| --- | --- | --- |
| **Agent Mode** | Chat-driven. You describe the task, the agent generates synthetic data, picks hyperparams, trains, evaluates, deploys. No code. | "Fine-tune a brand-voice writer for tenant X." (us) |
| **Deep Research Mode** | Fully autonomous. Web-browses to discover training data, runs multiple experiments in parallel, recovers from failed runs, iterates until convergence. | Open-ended optimization (Pro/Research tier only). |

### Adaptive Inference (the headline feature)

Once a model is deployed, Pioneer **continuously retrains it on its own live
inference data**. Failure patterns are detected, improved checkpoints are
trained and validated, and promotions happen automatically. This is unique
in the market — no other hosted fine-tune provider does this loop in production.

### Supported open-source models

Per Fastino's launch press release: **Qwen, Gemma, Llama, Nemotron, GLiNER**.
The pioneer.ai marketing site only shows Qwen / DeepSeek / Llama / GLiNER
above the fold — Gemma is confirmed in the press release but not the homepage.
We'll verify exact Gemma SKUs the moment we get a Pioneer account.

### Pricing (current, as of 2026-04-25)

| Tier | Price | Includes |
| --- | --- | --- |
| **Free** | $0/mo | $75 of usage credit, inference API, agent mode |
| **Pro** | $40/mo | Unlimited inference (rate-limited), downloadable weights, team |
| **Research** | $200/mo | Deep Research mode, multi-hour experiments, adaptive inference |

- **No overage charges until August 1, 2026** (promotional period).
- A single autonomous Deep Research run averages **6 h, ~$35** end-to-end.
- 2× cheaper inference vs GPT-4o (their claim, unverified).

### Hackathon-specific note

Track: "Best use of Pioneer" by Fastino. Prize **€700** (Mac Mini cash
value). Bonus points for using GLiNER2 creatively. Judging looks for:
1. Fine-tune a model that *outperforms or replaces* a general-purpose LLM
   API call (for us: replace Gemini per-tenant draft generation).
2. Thoughtful use of Pioneer features (synthetic data gen, eval against
   frontier models, adaptive inference).

Finalist Stage prizes for top 3 each include "Pioneer Pro plan (1 month)" —
which we'd want anyway to keep training post-hackathon.

Pioneer Big Berlin Hack onboarding is at <https://wholesale-mackerel-22f.notion.site/Big-Berlin-Hack-Onboarding-3498413d474480319020ddb593d700c0>
(login-walled when we tried — grab the API key from the on-site Fastino booth
on Saturday).

---

## 2. Gemma model lineup on Pioneer (2026)

Gemma is at version 3 in production (Gemma 4 was just announced for the
parallel Kaggle "Gemma 4 Good" hackathon). Pioneer's launch announcement
names "Gemma" generically — it is not yet documented which specific Gemma
sizes are pre-wired in their agent. **Assume Gemma 3 lineup until we see
the in-app picker.**

### Gemma 3 sizes (Google, 2025)

| Size | Params | RAM/VRAM (4-bit LoRA) | Sweet spot |
| --- | --- | --- | --- |
| 270M | 0.27 B | <2 GB, runs on CPU | Toy demos, classification |
| 1B | 1 B | ~3 GB | Cheap classifiers, mobile |
| **4B** | **4 B** | **~10 GB** | **Strong creative writing, ~128 K context, sweet spot for hackathons** |
| 12B | 12 B | ~22 GB (single A100) | Production reasoning |
| 27B | 27 B | ~22 GB w/ Unsloth 4-bit, or H100 | Peak quality, expensive |

### Recommendation for Brand Autopilot: **Gemma 3 4B-it**

Justification:

1. **Context budget.** Our system prompt + brand context is ~3 K tokens.
   Gemma 3 4B has a 128 K context window — comfortable headroom for
   reference brand transcripts and recent campaign history.
2. **Latency target.** Spec is "1-second voice generation." 4B at int4 on a
   single mid-tier GPU produces ~80 tok/s; a typical Instagram caption is
   60 tokens → fits inside our latency SLA.
3. **JSON-structured output.** 4B-it is large enough to reliably emit valid
   JSON when constrained (community reports for the 270M / 1B sizes show
   schema-following collapsing without heavy prompting; 4B is the practical
   minimum for clean structured output).
4. **Cold-start fine-tunability.** With LoRA r=16 on Pioneer, 4B trains in
   roughly 1-2 hours on a small dataset (50-200 examples) for an order-of-
   magnitude cost under $20/run. 12B+ would balloon both.
5. **Aligned with hackathon judging.** Pioneer's stated value prop is
   *small models that beat general-purpose API calls*. Gemma 3 4B is exactly
   in their sweet spot — picking 27B would muddy the story.

If 4B disappoints on voice fidelity, fallback up to **12B** (same recipe,
~3-4× cost). Avoid 27B in the hackathon timeline.

---

## 3. Training data shape

### What Pioneer expects (inferred)

Pioneer has not published an official dataset format spec on the public
docs we could reach. **However**: Pioneer is built on the Hugging Face / TRL
fine-tuning stack (every Fastino public artifact and their GLiNER2 repo
points there). Therefore the format is **conversational JSONL** — the
TRL-standard `messages` array.

### Concrete format

One JSON object per line, each with a `messages` field listing role-tagged
turns. Pioneer's agent will likely also accept plain `{"prompt": ..., "completion": ...}`
pairs (the older OpenAI fine-tune format) and convert internally — but
chat-format is universally safe.

```jsonl
{"messages": [{"role": "system", "content": "You write in the voice of Acme Coffee — playful, slightly sardonic, never corporate."}, {"role": "user", "content": "Draft an Instagram caption for our new oat-milk cortado launch."}, {"role": "assistant", "content": "Ok we tried. We really did. We tried not to obsess. The oat-milk cortado is here and yes, we're insufferable about it. ☕"}]}
{"messages": [{"role": "system", "content": "You write in the voice of Acme Coffee — playful, slightly sardonic, never corporate."}, {"role": "user", "content": "Draft a LinkedIn post announcing our seed round."}, {"role": "assistant", "content": "We raised $4M. We will spend it on espresso machines and slightly better espresso machines. Thanks to everyone who said yes — and to the 47 who said no, see you at the next round."}]}
```

For Brand Autopilot specifically, our `system` should also encode the
**structured-output contract** the agent loop needs (e.g. JSON envelope with
`caption`, `hashtags`, `cta`, `lift_estimate`). That keeps the fine-tune
serving the same JSON shape our existing `chat_json` client expects.

### Not what we'd use

- **Plain-text continuation** ({"text": "..."} on each line). Worse for
  instruction-following.
- **DPO/preference pairs** (chosen / rejected). Useful for *later*
  reinforcement on approve/reject draft feedback, but cold-start needs
  supervised pairs first.

### Format gotcha

Pioneer's docs are thin on this — **plan to email Fastino on Saturday** with
a dataset sample to confirm. Their GitHub `fastino-ai/GLiNER2` repo and the
`fastino.com/run` API both lean toward JSONL with named fields, so we are
on safe ground starting there.

---

## 4. Our training corpus — turning Brand Autopilot data into JSONL

This is the *moat*. Every other AI marketer ships one model for all tenants;
we ship one *per tenant*. The data we already collect is the input.

### What we have, per tenant (as of 2026-04-25)

| Source | Field | Volume per tenant |
| --- | --- | --- |
| Onboarding | voice profile (`tone`, `do_dont`, `voice_excerpt`, recurring phrases) | 1 object, ~200-500 tokens |
| Onboarding | competitor list + handles | ~3-5 entries |
| User pasted | Past social posts (text) | 0-30 |
| Social fetchers (`services/social/`: instagram, linkedin, tiktok, x, youtube) | captions / post text | 5-50 per platform when handle present |
| Video analyzer (`services/video/`) | transcripts + style observations | 0-10 |
| Style analyzer (`services/style/analyzer.py`) | structured `StyleProfile` (visual, ~500-1000 tokens) | 1 object |
| Reference brands | external posts user *aspires* to | 0-20 |

### Mapping to instruction-response pairs

The trick is **not** to dump posts and hope the model copies them — that
trains a copycat, not a voice. Instead, *back-construct* an instruction for
each post. For every captured post, we synthesize: "What brief would have
produced this post?" → that brief becomes the `user` turn, the post becomes
the `assistant` turn.

Brief synthesis can itself be a Gemini call (cheap; one-off per onboarding):

```python
# Pseudocode
for post in tenant.captured_posts:
    brief = gemini.generate(
        prompt=f"Reverse-engineer the marketing brief that produced this post:\n{post.text}\nReturn JSON: {{platform, audience, goal, length}}"
    )
    pair = {
        "messages": [
            {"role": "system", "content": render_brand_system_prompt(tenant.voice_profile)},
            {"role": "user", "content": render_user_brief(brief, post.platform)},
            {"role": "assistant", "content": json.dumps({"caption": post.text, "hashtags": extract_tags(post), ...})},
        ]
    }
    dataset.append(pair)
```

### Target volume per tenant

| Source | Pairs after expansion |
| --- | --- |
| Pasted posts | 0-30 (1:1) |
| Scraped social posts | 30-150 (top 30 per platform if handle found) |
| Video transcripts → captions | 0-30 (chunk transcripts into 1-2 caption-sized briefs) |
| Voice profile → synthetic | 20-50 (ask Gemini to generate variations grounded in `voice_excerpt` + `do_dont`) |
| **Total per tenant** | **~50-200** |

That hits the empirically-observed sweet spot (LIMA-style: 1k curated > 50k
noisy; <500 examples requires aggressive early stopping but works for LoRA
on a small model).

### Reference brands — handle with care

Mixing competitor / reference-brand text into the training set is **dangerous**:
the model will dilute the user's voice toward the references. Three options:

1. **Don't train on them.** Use them only as in-context retrieval examples
   at inference time.
2. **Train on them with a *negative* system prompt** ("This is a competitor's
   tone — do NOT replicate"). Risky; LLMs learn correlations not negations.
3. **Use them as DPO rejected pairs** in a later RLHF pass once we have
   approve/reject signal from the user.

Recommend (1) for hackathon; (3) for V2.

### Voice profile → synthetic seed pairs

Our richest cold-start asset is the voice profile JSON. We can multiply
it into ~20-50 synthetic instruction-response pairs by prompting Gemini:

> "Given this brand voice profile {profile}, generate 30 diverse marketing
> briefs and the corresponding posts written exactly in this voice. Output
> JSONL with `messages` arrays."

This is also where Pioneer's **Agent Mode synthetic-data feature** earns its
keep — they advertise "agent handles synthetic data generation." If their
synthetic generator is good, we hand it the voice profile + 5 real posts
and let it expand to 100. **This is the most strategically aligned use of
Pioneer for the hackathon prize.**

---

## 5. Cold-start problem — what to do with 5-20 posts

A new tenant walks in with 5 Instagram captions and a vibe. We can't fine-
tune on that *alone* and expect a voice model. The mitigation stack:

### Layer 1 — RAG fallback (ship Day 1)

Until N ≥ 30 approved drafts exist, **don't fine-tune at all**. Use the
generic Gemini model with the voice profile + a few-shot retrieval of the
3-5 most similar past posts pulled into the prompt. This is the well-known
"RAG > fine-tune for low-data brand voice" finding. Pioneer's deferred until
we have data worth training on.

### Layer 2 — Synthetic expansion (ship Day 2)

Use Gemini (or Pioneer's Agent Mode synthetic-data generator) to expand the
voice profile into 50-100 synthetic pairs. Train a **first-pass LoRA
adapter** on Pioneer.

This is parameter-efficient (PEFT/LoRA: only ~0.1% of model weights are
trainable). Survives small datasets *if* the data is clean and consistent.
Hyperparameter discipline:

- Learning rate: 5e-6 to 5e-5 (lower than usual for small data)
- Epochs: 1-2 max
- Early stopping on validation loss climbing
- Batch size: small (1-4)
- LoRA r: 16, alpha: 32, target modules: q_proj, v_proj, k_proj, o_proj

### Layer 3 — Continuous fine-tuning (Pioneer's superpower)

Pioneer's adaptive-inference loop reads live inference traces. Every
approved draft becomes a positive training signal; every rejected draft a
negative. After ~500 inferences in production, the model auto-improves.
**This is the long-tail moat.** The longer a tenant uses us, the more
distinctive their voice model becomes.

### Decision tree

```
on draft generation:
  if tenant has fine-tuned adapter:
    use Pioneer-deployed adapter
  elif tenant has ≥30 approved drafts:
    queue fine-tune job on Pioneer (background)
    use Gemini + RAG meanwhile
  else:
    use Gemini + RAG (voice profile + 5-shot retrieval)
```

---

## 6. API surface (best inferred from public Fastino docs + standard LLM-tuning APIs)

> **Caveat:** Pioneer's full API reference is not yet on the public web
> (launched 4 days ago). What follows is a reasonable inference based on
> Fastino's existing API patterns (`api.fastino.com/run` with `x-api-key`
> auth) and standard fine-tune-platform conventions. **Validate at the
> Fastino booth Saturday morning.**

### Auth

```http
POST https://api.fastino.com/...
x-api-key: pio_live_<...>
content-type: application/json
```

API key generated at <https://labs.fastino.ai>.

### Likely endpoint shape (pseudocode)

```python
import httpx, json

PIONEER = "https://api.fastino.com"
HEADERS = {"x-api-key": PIONEER_API_KEY}

# 1. Upload dataset
with open("tenant_acme.jsonl", "rb") as f:
    r = httpx.post(
        f"{PIONEER}/v1/files",
        headers=HEADERS,
        files={"file": f},
        data={"purpose": "fine-tune"},
    )
file_id = r.json()["id"]

# 2. Kick off training job (Agent Mode)
r = httpx.post(
    f"{PIONEER}/v1/agent/finetune",
    headers=HEADERS,
    json={
        "base_model": "gemma-3-4b-it",
        "training_file": file_id,
        "task_description": "Generate social-media drafts in Acme Coffee's voice. Output JSON with caption, hashtags, cta.",
        "method": "lora",
        "hyperparameters": {"r": 16, "alpha": 32, "epochs": 2, "lr": 2e-5},
    },
)
job_id = r.json()["id"]

# 3. Poll status
while True:
    job = httpx.get(f"{PIONEER}/v1/jobs/{job_id}", headers=HEADERS).json()
    if job["status"] in ("succeeded", "failed"):
        break
    time.sleep(30)

# 4. Deploy adapter (auto on success in Agent Mode, but explicit endpoint exists)
r = httpx.post(
    f"{PIONEER}/v1/deployments",
    headers=HEADERS,
    json={"model_id": job["fine_tuned_model"], "name": f"acme-voice-v1"},
)
deployment_url = r.json()["endpoint"]   # e.g. https://infer.pioneer.ai/d/acme-voice-v1

# 5. Inference
r = httpx.post(
    deployment_url,
    headers=HEADERS,
    json={
        "messages": [
            {"role": "system", "content": render_brand_system(tenant)},
            {"role": "user", "content": brief},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
    },
)
draft = r.json()
```

### Adaptive inference (Pro/Research)

Once deployed, Pioneer auto-monitors and retrains. You get a webhook when a
new checkpoint is promoted:

```json
{"event": "deployment.checkpoint_promoted", "deployment_id": "...", "metrics": {...}}
```

We'd subscribe to this webhook in `app/events/bus.py` and emit a new
`brand.voice_model_upgraded` event for our agent loop to pick up.

---

## 7. Cost / time estimates

### Per-tenant fine-tune (single LoRA training run)

| Variable | Value | Source |
| --- | --- | --- |
| Time | 1-2 h (Agent Mode), 6 h avg (Deep Research) | Fastino press release: "in a matter of hours"; "average of 6 hours" |
| Cost | **~$5-15** for our 50-200 example, 4B LoRA Agent-Mode run; **~$35** for an autonomous Deep Research run | Fastino claim: "average $35" for a full autonomous run; ours is much smaller scope so cheaper |
| Free tier | $75 included | Pioneer pricing page |
| Pro tier | $40/mo | Pioneer pricing page |

### Implications for our SaaS economics

- A free-tier Pioneer account ($75 credit) covers ~5 tenant fine-tunes.
- At Pro ($40/mo unlimited inference, paid training), assume training
  spend amortizes to ~$10/tenant/month if we retrain monthly.
- If we charge €49/tenant/month, fine-tune cost is ~20% of revenue —
  acceptable but not luxurious. At scale we'd want to negotiate a
  Fastino enterprise deal.

### Inference cost

Pioneer claims "2× cheaper than GPT-4o." GPT-4o is roughly $2.50/M input,
$10/M output tokens. So Pioneer ≈ $1.25/M in, $5/M out. A typical draft
(3 K in + 200 out) ≈ $0.005. Per tenant per day with 10 drafts ≈ $0.05/day,
$1.50/month. Trivial.

### Caveat

Inference *cost* is not the bottleneck — *latency* is. Pioneer hasn't
published p50 latency numbers. We'll measure on Saturday.

---

## 8. Integration plan into Brand Autopilot

### File-by-file

```
backend/app/
├── services/
│   ├── finetune/                   # NEW
│   │   ├── __init__.py
│   │   ├── corpus_builder.py       # collect tenant data → JSONL
│   │   ├── pioneer_client.py       # httpx wrapper around Pioneer API
│   │   ├── orchestrator.py         # job lifecycle: kick off, poll, deploy
│   │   └── prompts.py              # brief-synthesis + system-prompt templates
│   ├── llm/
│   │   └── client.py               # MODIFY: route to Pioneer adapter if tenant has one
│   └── ...
├── events/
│   └── types.py                    # ADD events (see below)
├── api/
│   └── finetune.py                 # NEW: webhook receiver + admin endpoints
└── db/
    └── ...                         # ADD: tenant.voice_model_id, tenant.adapter_url
```

### New events

```python
class Events:
    ...
    # Fine-tune lifecycle
    VOICE_CORPUS_BUILT      = "brand.voice_corpus_built"      # JSONL ready
    VOICE_TRAINING_QUEUED   = "brand.voice_training_queued"   # Pioneer job created
    VOICE_TRAINING_PROGRESS = "brand.voice_training_progress" # status updates
    VOICE_MODEL_READY       = "brand.voice_model_ready"       # adapter deployed
    VOICE_MODEL_UPGRADED    = "brand.voice_model_upgraded"    # Pioneer adaptive-inference promoted a new checkpoint
    VOICE_TRAINING_FAILED   = "brand.voice_training_failed"
```

### When does fine-tuning trigger?

Three triggers, in priority order:

1. **Manual**: tenant clicks "Train my voice model" in the dashboard once
   onboarding is complete and they have a meaningful corpus. (Hackathon-
   demoable button.)
2. **Threshold**: after ≥30 approved drafts, auto-queue a fine-tune job.
   This is the production trigger.
3. **Scheduled**: monthly retrain, picking up the latest approved/rejected
   drafts as fresh training signal. (Pioneer's adaptive-inference does
   this automatically once deployed; this is just for tenants who haven't
   opted into adaptive mode yet.)

### Routing logic in `services/llm/client.py`

```python
async def chat_json(messages, schema=None, model=None, tenant_id=None):
    # If tenant has a deployed Pioneer adapter, prefer it.
    if tenant_id and (adapter_url := await get_tenant_adapter_url(tenant_id)):
        return await pioneer_chat_json(adapter_url, messages, schema)
    # Otherwise: existing Gemini path (unchanged).
    return await gemini_chat_json(messages, schema, model)
```

### Webhook listener for adaptive inference

```python
@router.post("/webhooks/pioneer")
async def pioneer_webhook(payload: dict):
    if payload["event"] == "deployment.checkpoint_promoted":
        await event_bus.emit(Events.VOICE_MODEL_UPGRADED, {...})
```

---

## 9. Risk / fallback

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Pioneer is rate-limited / API undocumented at hackathon time | High (launched 4 days ago) | Talk to Fastino booth Saturday. Have a local Unsloth+LoRA fallback script ready. |
| Pioneer's Gemma support isn't first-class yet | Medium | Llama 3 8B is a fine alternative; same recipe, supported by Pioneer per press release. |
| Fine-tune *fails* due to too few examples | Medium | Synthetic-pair generation (Gemini, Section 4) bumps minimum corpus to ≥50. |
| Voice fidelity disappointing | Medium | Stack with RAG: `output = adapter(brief + retrieved_examples)`. Belt + braces. |
| Pioneer expensive at scale | Low (their claim is 2× cheaper than GPT-4o) | Renegotiate enterprise; or self-host Gemma 3 4B + LoRA on a single L4 GPU (~$200/mo). |
| Pioneer goes down mid-demo | Low-Medium | **Fallback path: route to Gemini with the same system prompt + retrieved examples, no model change visible to user.** |
| Webhook never arrives (adaptive inference broken) | Medium | Polling fallback every 1 h on `/v1/deployments/{id}`. |

### Cleanest fallback that still ships the per-tenant-voice story

If Pioneer is fully unavailable: **a heavy system prompt + 5 retrieved
examples in-context, packaged as a "Voice Adapter" in our UI**. The user
never sees the model name. We get the brand-voice story without the actual
fine-tune. Honest, demoable, ships in 2 hours.

---

## 10. Hackathon-acceptable scope cut

> Time check: Sunday submission at 14:00. We have ~24 working hours.
> Strict scope.

### Must-ship

1. **Corpus builder** (`services/finetune/corpus_builder.py`)
   - Reads tenant data (voice profile, scraped posts, video transcripts).
   - Calls Gemini for brief synthesis.
   - Emits a JSONL file at `storage/finetune/{tenant_id}/corpus.jsonl`.
   - Logs counts (e.g. "73 training pairs ready for Acme Coffee").
   - **This is the part that has to actually work** — it's the moat.
2. **Pioneer kickoff call** (`services/finetune/pioneer_client.py`)
   - Even if the API is hand-held: use the Agent Mode chat interface
     interactively at the booth, paste in the JSONL, take a screenshot
     of the training run.
   - Or: actually hit `/v1/agent/finetune` if the API works.
3. **UI moment**: a "Training your voice model on Pioneer..." progress
   card in the dashboard, with a real (or mocked) status feed via SSE.
4. **Demo narrative** (in the 2-min Loom):
   - Show onboarding produce voice profile.
   - Show corpus.jsonl building from real data, with line counts.
   - Show "Train on Pioneer" button → Pioneer dashboard → finished
     adapter.
   - Show *one inference call* against the deployed adapter, even if
     hand-tuned by Pioneer's staff.
   - Compare vs generic Gemini on the same brief — show voice fidelity
     diff.

### Nice-to-have (skip if behind)

- Real webhook listener.
- Routing logic in `chat_json` — can be a feature flag hardcoded for
  the demo tenant.
- Adaptive-inference loop — talk about it in the pitch, don't build it.

### Honest scope cut: "fake-it" version

If Pioneer's API resists us:

- Build the corpus.jsonl for real (this is the genuine work).
- The "training" UI shows real progress for 90 seconds, ending with a
  celebration card: "Acme's voice model is ready."
- Behind the scenes: we're still calling Gemini, but with an enriched
  system prompt assembled from the same corpus.
- Pitch frames it as "the next deploy is to Pioneer; today you're seeing
  the data layer that powers it."

This is **honest** if we say it on stage. The judges of "Best use of
Pioneer" will probably reward genuine API usage even if scrappy, but
fallback is a real demo either way.

### Stretch (post-hackathon)

- Real webhook + adaptive inference.
- DPO pass on approve/reject signals.
- Multi-modal Gemma 3 (vision) for visual-style learning from
  screenshots.
- Per-tenant model versioning + rollback.

---

## Sources (all 2025-2026)

1. Fastino launch press release (PR Newswire, 2026-04-21) —
   <https://www.prnewswire.com/news-releases/fastino-launches-pioneer-the-first-agent-for-fine-tuning-and-inference-of-llms-302748105.html>
2. Pioneer AI homepage — <https://pioneer.ai/>
3. Pioneer AI pricing — <https://pioneer.ai/pricing>
4. Fastino API quickstart docs — <https://fastino-1.gitbook.io/docs>
5. Big Berlin Hack manual (`/Users/squidbq/Documents/Hackathon_2026_Big_Hack/big_berlin_hack_manual.md`)
6. Big Berlin Hack event page — <https://luma.com/bigberlinhack>
7. Phil Schmid, "How to fine-tune Google Gemma with ChatML and Hugging Face TRL" — <https://www.philschmid.de/fine-tune-google-gemma>
8. Google AI for Developers, "Gemma model fine-tuning" — <https://ai.google.dev/gemma/docs/tune>
9. Unsloth, "Fine-tune Gemma 3 with Unsloth" — <https://unsloth.ai/blog/gemma3>
10. Novita, "Which Gemma 3 Model is Best for You?" (2026) — <https://blogs.novita.ai/which-gemma-3-model-is-best-for-you-a-complete-guide/>
11. Databricks, "Efficient Fine-Tuning with LoRA" — <https://www.databricks.com/blog/efficient-fine-tuning-lora-guide-llms>
12. AWS Prescriptive Guidance, "Comparing RAG and fine-tuning" — <https://docs.aws.amazon.com/prescriptive-guidance/latest/retrieval-augmented-generation-options/rag-vs-fine-tuning.html>
13. Hillock, "How to fine-tune an LLM for brand voice consistency" — <https://hillock.studio/blog/brand-voice>

## Open questions (verify Saturday at the Fastino booth)

- Exact list of Gemma SKUs available in Pioneer's model picker.
- Confirmed dataset format: chat-JSONL vs prompt-completion.
- Real `/v1/agent/finetune` endpoint shape (or whatever they actually call it).
- Whether downloadable adapter weights (Pro tier) are LoRA `.safetensors` or merged.
- Webhook event names for adaptive-inference promotion.
- Are hackathon participants given temporary Pro tier access? (Worth $40 — saves us our $75 credit for Sunday's actual training.)
