# Copy Marketing — Learning From Competitors

> *Status*: strategy doc. Drives the "Copy Marketing from others" lane on the whiteboard alongside *Content erstellen* and *Data Analyze*.
> *Author*: research agent, 2026-04-25.
> *Audience*: hackathon team — what to build, in what order, and what not to ship.

The user's directive in plain language: *"copy marketing from others, or learn from them in some way — spin one up based on what we have/get and write it into a md file."* This document is the answer to that.

---

## 1. The frame — *learning from* vs *copying*

Brand Autopilot does not plagiarize. It studies competitors the way a chess engine studies opening books: to know the *shape of the field* — which formats they invest in, which hooks land, which cadences they hold, which prompts they win on LLM answer engines — and then surfaces *openings* the user can move into in their *own voice*. The vision doc is explicit on this: *"Not to copy. To know the shape of the field and where the real openings are."* The output is patterns and gaps, not paragraphs lifted off a competitor's blog. This is the ethical line every credible competitive intelligence tool draws — Pragmatic Institute frames it as "if it feels wrong, it probably is" — and it doubles as defensible product positioning: a generic content tool that just rewords competitor posts is a lawsuit risk and a brand-voice contaminant; a *pattern-and-gap* engine that always renders through the user's own voice profile is neither. The product principle is one sentence: **competitor data is a map, not a script.**

---

## 2. What signals we extract from a competitor's marketing

For every competitor we track, we extract these signals from their public posts, site, and citation surface. The list is long on purpose — we cherry-pick the cheapest subset for the hackathon (see §8) and keep the rest as a v2 backlog.

| # | Signal | Definition | Source |
|---|---|---|---|
| 1 | **Format mix** | % share across formats: long-form blog, short-form social, video, comparison page, listicle, technical post, case study, thread | Their site + social fetchers |
| 2 | **Cadence** | Posts per week, per channel; consistency variance | Repeated time-series fetches |
| 3 | **Hooks** | First 1–2 sentences of their highest-engagement posts (proxy for "what stopped the scroll") | Social fetchers + likes/engagement |
| 4 | **CTAs** | What they ask for: sign-up, book demo, read more, install, contact sales, share, free trial | Last sentence/button extraction |
| 5 | **Voice patterns** | Recurring phrases, lexicon, sentence length distribution, point-of-view (we vs you vs they), emoji usage, em-dash habit | Same `voice_profile` extractor we run on the user's brand |
| 6 | **Visual idiom** | Palette, photographic vs illustrated, recurring layouts, brand ornament use, motion language | Same `style.analyze_style` we already run |
| 7 | **Content pillars** | Recurring themes/topics — clustered topic labels with frequencies | Topic clustering on captions/titles |
| 8 | **Hashtag families** | Which hashtag clusters they use; entry/exit cadence into trending tags | Social posts |
| 9 | **Citation surface** | Which third-party sources cite them; which prompts they win on LLM answer engines | Peec MCP |
| 10 | **GEO openings** | Prompts where they're absent (or weak) and we have an asset/angle that could win | Peec MCP diff |
| 11 | **What flopped** | Posts with engagement well below their median — cheap *don't-do-that* signal | Engagement distribution per competitor |
| 12 | **Timing** | Day-of-week and hour-of-day distribution of their posts | Posted-at timestamps |

The point of this list is breadth — we do not have to ship all twelve. We ship the cheapest *credible* set first (see §8) and let the schema accommodate the rest.

---

## 3. What we already have vs what's missing

Mapped against the existing backend at `/Users/squidbq/Documents/Hackathon_2026_Big_Hack/backend/app/`. **Done** = collection *and* analysis exist. **Partial** = collected but not analyzed for competitors. **Missing** = needs new code.

| Signal | Status | Where it lives / What's needed |
|---|---|---|
| Voice patterns | **Partial** | Voice extractor exists at `app/services/llm/prompts.py::voice_profile_messages` and runs on the user's brand in the orchestrator. Reuse the same prompt against competitor body text. New work: a competitor scrape that produces enough body markdown to feed it. |
| Visual idiom | **Partial** | Style analyzer exists at `app/services/style/analyzer.py`. Currently runs on the user's screenshots only. Needs to run on competitor screenshots (we already collect a logo via `_enrich_competitor_lite`, but no screenshots yet). |
| Format mix | **Missing** | Needs a classifier prompt over fetched posts (LLM JSON: blog/short/video/listicle/comparison/case-study/technical/thread). Cheap. |
| Cadence | **Missing** | Requires N≥2 snapshots over time. For the hackathon we *fake* it from the timestamp of the most-recent K posts (N=1 fetch, infer rate from the time-window those K posts span). Honest about the caveat (see §9 pitfall #4). |
| Hooks | **Partial** | Social fetchers (`app/services/social/{instagram,linkedin,x,tiktok,youtube}.py`) already return `caption` and `likes`. Sort by likes, take top K, slice first 1–2 sentences. New work: the slicer + the rank. |
| CTAs | **Missing** | Tail-of-caption extraction + LLM classifier. Trivial. |
| Content pillars | **Missing** | Cluster captions with embeddings, label clusters with an LLM. ~30 lines. |
| Hashtag families | **Partial** | Captions contain them; need a regex extract + frequency. ~10 lines. |
| Citation surface | **Missing** | Peec MCP lookup per competitor handle. Wired through MCP tool calls. |
| GEO openings | **Missing** | Peec MCP diff: prompts they don't win where we have an asset/angle. |
| What flopped | **Missing** | Engagement-distribution outlier on the same data we already have. ~5 lines. |
| Timing | **Missing** | Histogram on posted-at. ~5 lines. |

Net: **two heavy lifters already exist** (voice + style analyzers). We don't need new ML infrastructure — we need to point what we have at competitor data and add a thin pattern-extraction service on top.

The data model is also already partway there. `app/db/models.py::Competitor` has `id, brand_id, name, url, reason, logo_url`. The minimum schema change is one column: `pattern_library: JSON` (see §6).

---

## 4. The pattern library

A single JSON object per competitor, stored on `Competitor.pattern_library`. The agent re-reads this whenever it needs to suggest a counter-move, draft a piece, or surface a gap. Versioned on `last_updated` so we can tell stale data from fresh.

### Schema

```json
{
  "competitor_id": "uuid",
  "format_mix": {
    "blog_long": 0.30,
    "social_short": 0.40,
    "video": 0.15,
    "comparison_page": 0.05,
    "listicle": 0.05,
    "technical": 0.05
  },
  "cadence": {
    "linkedin_per_week": 5.5,
    "x_per_week": 12.0,
    "blog_per_week": 1.2,
    "consistency_variance": "low"
  },
  "hook_archetypes": [
    {
      "pattern": "contrarian-claim",
      "examples": [
        "Most CRMs are built for sales managers, not salespeople.",
        "We deleted half our roadmap. Here's why."
      ],
      "frequency": 0.25
    },
    {
      "pattern": "specific-number-flex",
      "examples": ["We shipped 47 features in Q1.", "1.3M devs use this."],
      "frequency": 0.18
    }
  ],
  "cta_patterns": ["start-free", "book-demo", "read-the-docs"],
  "voice_lexicon": {
    "signature_phrases": ["ship it", "as a team", "the right tool"],
    "avg_sentence_len": 14,
    "pov": "we",
    "tone": "confident, technical, dry-witty"
  },
  "visual_idiom": {
    "palette_character": "monochrome dark with electric purple accent",
    "photographic_vs_illustrated": "screenshot-led, with line illustrations",
    "distinctive_marks": ["oversized rounded corner cards", "code in product shots"]
  },
  "content_pillars": [
    {"label": "engineering culture", "frequency": 0.30},
    {"label": "product launches", "frequency": 0.25},
    {"label": "customer stories", "frequency": 0.20},
    {"label": "industry takes", "frequency": 0.15},
    {"label": "career posts", "frequency": 0.10}
  ],
  "hashtag_clusters": [["#buildinpublic", "#startup"], ["#design", "#ux"]],
  "citation_sources": [
    {"domain": "techcrunch.com", "count": 14},
    {"domain": "hackernews", "count": 32}
  ],
  "geo_wins": [
    {"prompt": "best project management for startups", "rank": 2},
    {"prompt": "linear vs jira", "rank": 1}
  ],
  "geo_gaps": [
    {"prompt": "cheapest pm tool for solo founders", "their_rank": null}
  ],
  "what_flopped": [
    {"hook": "5 ways to schedule meetings", "engagement_z": -1.8}
  ],
  "timing": {"peak_day": "Tue", "peak_hour_utc": 14},
  "last_updated": "2026-04-25T12:00:00Z",
  "snapshot_count": 1
}
```

### Concrete example — Linear

```json
{
  "competitor_id": "linear-uuid",
  "format_mix": {
    "blog_long": 0.20,
    "social_short": 0.50,
    "video": 0.20,
    "comparison_page": 0.05,
    "technical": 0.05
  },
  "cadence": {
    "linkedin_per_week": 3.0,
    "x_per_week": 8.0,
    "blog_per_week": 0.5
  },
  "hook_archetypes": [
    {
      "pattern": "craft-pride",
      "examples": [
        "We obsess over every pixel, because the tools you use shape what you build.",
        "Speed isn't a feature. It's a discipline."
      ],
      "frequency": 0.40
    },
    {
      "pattern": "contrarian-claim",
      "examples": ["Issue trackers are the wrong abstraction."],
      "frequency": 0.20
    }
  ],
  "cta_patterns": ["read-changelog", "try-linear", "watch-demo"],
  "voice_lexicon": {
    "signature_phrases": ["built for software teams", "speed", "craft"],
    "avg_sentence_len": 12,
    "pov": "we",
    "tone": "minimal, opinionated, design-led"
  },
  "visual_idiom": {
    "palette_character": "near-black background with subtle purple/blue gradient accents",
    "photographic_vs_illustrated": "UI screenshots dominant, almost no photography",
    "distinctive_marks": ["soft glow on UI mocks", "monospaced labels", "thin keyline borders"]
  },
  "content_pillars": [
    {"label": "product changelog", "frequency": 0.40},
    {"label": "engineering culture", "frequency": 0.25},
    {"label": "design system", "frequency": 0.20},
    {"label": "customer stories", "frequency": 0.15}
  ],
  "hashtag_clusters": [["#product", "#design"], ["#engineering"]],
  "citation_sources": [
    {"domain": "ycombinator.com", "count": 28},
    {"domain": "designsystem.fm", "count": 6}
  ],
  "geo_wins": [
    {"prompt": "best issue tracker for startups", "rank": 1},
    {"prompt": "linear vs jira", "rank": 1},
    {"prompt": "fastest project management software", "rank": 2}
  ],
  "geo_gaps": [
    {"prompt": "cheapest project tool for solo founders", "their_rank": null},
    {"prompt": "best PM tool with AI assistant", "their_rank": null}
  ],
  "timing": {"peak_day": "Wed", "peak_hour_utc": 15},
  "last_updated": "2026-04-25T12:00:00Z",
  "snapshot_count": 1
}
```

The gap-finder (§6) reads two of these — the user's pattern_library and the competitor's — and produces a diff.

---

## 5. How the agent uses it (the actual product surface)

The pattern library is invisible if it's not surfaced. Six user-visible features turn it into a product:

1. **"Counter-move" cards on home.** A scrollable feed on the home screen. Each card is a single sentence + a CTA: *"Linear shipped a vertical-video changelog post on Tuesday. You've never tried that format. Want to draft a video changelog for your last release?"* One tap drafts it in the user's voice. This is the headline feature — every demo opens here.
2. **Hook bank.** A small library of voice-adapted hook archetypes pulled from competitor top-engagement posts. The user picks one ("contrarian-claim," "specific-number-flex," "second-person-question"), the agent applies their voice profile and topic, out comes a draft. Foreplay's *Spyder* product is the closest credible analog — they explicitly extract "top-performing hooks" and ship them as a discoverable asset (foreplay.co/spyder-ad-spy).
3. **Format gap report.** A short, scannable card: *"Your 3 main competitors invest 20% of their content in comparison pages. You have zero. Three prompts ('linear vs jira'-style) are wide open."* One tap drafts the comparison page outline.
4. **Cadence gap indicator.** A tiny sparkline-style chart on the dashboard: *competitor average posts/week vs yours*. No big spend on charting — a dot, a line, a number. The point is a glance, not a deep-dive.
5. **GEO opening suggestions.** Peec-driven. *"You're not cited on 'best CRM for Series A' (12K monthly LLM queries). Two competitors are weakly cited. Here's a draft answer."* This is the wedge — see §10.
6. **Style mix-and-match.** *"Use Vercel's polish on a Notion-clarity post structure for your next launch post."* The vision doc names taste-blending as a goal; the visual_idiom block in the pattern library is what makes it feasible. v2.

Counter-move cards (#1) are the demo-day moment. Everything else is supporting cast.

---

## 6. Concrete implementation plan — file-by-file

```
backend/app/services/learning/
  __init__.py
  competitor_analyzer.py      # produces pattern_library JSON for one competitor
  gap_finder.py               # diffs user pattern vs competitor patterns; returns top N gaps
  suggestor.py                # turns gaps into home-screen cards
backend/app/db/models.py      # +1 column on Competitor: pattern_library: JSON
backend/app/events/types.py   # +3 events
backend/app/api/learning.py   # GET /api/competitors/{id}/pattern, GET /api/suggestions
```

### `competitor_analyzer.py`

Single entry point: `async def analyze(competitor_id: str) -> dict`. Pulls the competitor's URL, runs the existing `scrape_lite` against it, fetches social posts via the existing fetchers (one per handle the user supplied for that competitor), runs the existing `voice_profile` LLM prompt against the body markdown, runs the existing `analyze_style` against the screenshots, then fills in the cheap signals (hashtag regex, hook slicing, CTA classifier, format-mix LLM call). Persists into `Competitor.pattern_library`. Emits `competitor.pattern_extracted`. **Best-effort by contract** — every step degrades to `None` rather than raises, mirroring the convention already established in `app/services/style/analyzer.py` and the social fetchers. The function is intentionally a pipeline of small, individually-failable steps.

### `gap_finder.py`

`async def find_gaps(brand_id: str) -> list[Gap]`. Loads `Brand.voice_profile` + an inferred "user pattern_library" (computed from the user's own posts the same way) and every `Competitor.pattern_library` for the brand. Returns a ranked list of `Gap` objects: `{kind, competitor_id, evidence, suggested_action, score}`. Kinds: `format_gap`, `cadence_gap`, `geo_gap`, `hook_gap`, `pillar_gap`. Score is a 0–1 *opportunity index* — combines competitor strength on that signal × user weakness × estimated payoff. Emits `gap.identified` for the top N.

### `suggestor.py`

`async def suggest_cards(brand_id: str, max_cards: int = 5) -> list[Card]`. Reads gaps, applies a small LLM prompt that turns each into a single-sentence counter-move written in the user's voice. Each card carries a `draft_intent` payload that the existing draft-generation pipeline already understands. Emits `suggestion.generated` per card. The home screen reads these via a new GET endpoint. Suggestions cache for 24h per `(brand_id, gap_signature)` so a refresh doesn't re-spend LLM tokens.

### Data model change

```python
# backend/app/db/models.py — add to Competitor
pattern_library = Column(JSON, default=dict)   # see §4 for shape
pattern_updated_at = Column(DateTime, nullable=True)
```

A single nullable JSON column. No migration tooling needed (we already use SQLAlchemy on a SQLite file `brand_autopilot.db`).

### Events

```python
# backend/app/events/types.py — add to Events class
COMPETITOR_PATTERN_EXTRACTED = "competitor.pattern_extracted"
GAP_IDENTIFIED = "gap.identified"
SUGGESTION_GENERATED = "suggestion.generated"
```

`COMPETITOR_SURGED` already exists at `events/types.py:23` — reuse it as the trigger that kicks off `gap_finder` for a given competitor.

### Reusing what's already there

- `voice_profile` extractor → call against competitor body markdown
- `analyze_style` → call against competitor screenshots once we collect them (hookable in `_enrich_competitor_lite`)
- Social fetchers → already return `caption + likes + posted_at`, exactly what we need for hooks/cadence/timing
- Event bus → already wired into the SSE stream (`api/events_stream.py`); the new events flow through it for free

---

## 7. Integration with Peec MCP

The citation/visibility data is the multiplier. Without Peec the agent can suggest format gaps and hook patterns, which is useful but generic. With Peec, the agent suggests *the prompt the user should win on this week, the competitor whose surge opened it, and the draft that fills the gap*. That is the demo.

### End-to-end flow

```
1. Peec MCP polls citation share-of-voice on tracked prompts
   └─ Detects competitor_X jumped from rank 4 → rank 1 on prompt P
2. Emit competitor.surged { competitor_id, prompt, rank_delta, sources }
3. gap_finder receives competitor.surged
   ├─ Loads user.pattern_library for brand_id
   ├─ Loads competitor_X.pattern_library
   └─ Computes one geo_gap: { prompt: P, their_rank: 1, our_rank: null,
                              their_format: "comparison-page", our_pillars_overlap: 0.3 }
4. suggestor turns the gap into a card:
   "Acme jumped to #1 on 'best CRM for Series A' with a comparison page.
    You haven't published one. Draft a comparison piece in your voice?"
5. User taps "Draft" → existing draft pipeline runs with draft_intent =
   { type: "comparison_page", target_prompt: P, reference_format_only: competitor_X.id }
6. Draft is generated using user's voice_profile, NOT competitor's voice
   (provenance hook: voice fingerprint check before publish — see §9)
7. After publish, Peec MCP tracks our citation rank on P;
   suggestion lifecycle closes when our_rank ≤ N (configurable; default 3)
```

### Pseudocode

```python
# Triggered by competitor.surged from Peec MCP
async def on_competitor_surged(event: dict) -> None:
    brand_id = event["brand_id"]
    competitor_id = event["competitor_id"]
    prompt = event["prompt"]

    competitor = load_competitor(competitor_id)
    if not competitor.pattern_library:
        await competitor_analyzer.analyze(competitor_id)
        competitor = load_competitor(competitor_id)

    gap = gap_finder.geo_gap_for(
        brand_id=brand_id,
        competitor=competitor,
        surged_prompt=prompt,
    )
    if not gap or gap.score < 0.4:
        return

    card = await suggestor.from_gap(gap, brand_id=brand_id)
    bus.emit(Events.SUGGESTION_GENERATED, {"brand_id": brand_id, "card": card})
```

The two MCP read paths we need from Peec: *(a)* "current rank for {brand, prompt}" and *(b)* "rank delta over the last 7 days for {competitor, prompts they appear on}." Both are already documented as Peec capabilities (Share of Voice + competitive citation data per docs.peec.ai).

---

## 8. Hackathon-acceptable scope cut

Build the smallest version that demos. Everything else is post-hackathon.

**In:**
- One scrape-and-analyze pass per competitor at onboarding time (no time-series, no scheduled re-scans). One `competitor_analyzer.analyze()` per competitor in the existing `enrich_and_persist` loop in `orchestrator.py`.
- Pattern library limited to: `voice_lexicon` (existing prompt), `visual_idiom` (existing analyzer), `format_mix` (one new LLM call), `hook_archetypes` (top 3 by likes from social fetcher), `geo_wins/geo_gaps` (Peec MCP).
- One home-screen feed of suggestion cards. Five cards max. Cached.
- One Peec-driven card minimum on demo day — the "Acme surged on prompt X, draft a counter-piece" flow, end to end. This is the wow moment.
- Counter-move cards are read-only first; "Draft" button hits the existing draft pipeline.

**Out (post-hackathon):**
- Cadence (needs N≥2 snapshots — fake it from a single fetch with an honest "estimated" badge if we want the metric on the dashboard, otherwise skip).
- What-flopped detection (needs distribution).
- Style mix-and-match (the v2 magic moment).
- Re-running pattern extraction on a schedule.
- A separate "user pattern_library" computed from the user's own posts — for the demo we use `Brand.voice_profile` directly and infer format-mix from the user's onboarding scrape only.

**Demo storyline:** onboarding finishes → home screen shows 4 generic cards (format-gap, hook, content-pillar, voice-style) drawn from the static pattern libraries → judges watch a *live* Peec ping change one card from "draft a comparison page" to "Acme just surged on 'best CRM for Series A' — here's your counter-piece." Tap, draft renders, in user's voice. Sub-90 seconds end-to-end.

---

## 9. Pitfalls

Five concrete failure modes to design against. Each is a real trap, each has a known mitigation.

1. **Biggest-competitor playbook bias.** If the user's three competitors are Linear, Notion, and Figma, the agent will recommend post cadences and production budgets the user can't sustain. Their resources are not yours. **Mitigation:** weight competitor patterns by relative size/stage (a small "company stage" tag on each Competitor row, set during onboarding). Down-weight giants for early-stage users.
2. **Survivorship bias.** We see what they shipped, not what they tried and dropped. The "winning" formats are a sample of one — their successes — not their experiments. **Mitigation:** make this explicit in the UI ("based on what they publicly ship"), and lean on `what_flopped` (their below-median posts) when we have enough data — that's the closest we can get to seeing their losers.
3. **Voice contamination.** Anything that fine-tunes on competitor posts dilutes the brand voice we just spent the onboarding flow learning. **Mitigation hard rule:** competitor posts never enter the voice training/few-shot pool. The voice profile is computed *only* from the user's own scraped/uploaded content. Competitor data flows through separate prompts (pattern extraction, gap finding, hook archetype labeling) — never through the voice prompt.
4. **Hallucinated cadence from a single fetch.** If we fetch 5 posts spanning 3 days, "1.7 posts/day" is misleading — they may have batched and gone silent for a week. **Mitigation:** require N≥2 snapshots taken ≥3 days apart before any cadence number leaves the backend with high-confidence flag set. For the hackathon, mark cadence numbers as "estimated, single snapshot" or omit them.
5. **Plagiarism risk if "learning" becomes "rewording."** Drafting a comparison page that reads as a paraphrase of a competitor's comparison page is a legal and brand risk. **Mitigation:** content provenance hooks. Two checks before publish: (a) max-overlap n-gram check between draft and any competitor post we've ingested (>15% overlap blocks publish, surfaces a warning); (b) voice-fingerprint check — the draft's stylometric profile must be within an L2 distance threshold of the user's `voice_profile`. Both are cheap, both are credible to a judge, both are necessary in production.

---

## 10. Why this is a wedge

Generic content-generation tools have one ingredient: an LLM that writes copy. Brand Autopilot has three, and the *combination* is what no incumbent has shipped end-to-end:

- **Per-tenant voice fine-tuning** — the agent writes in *your* voice, not a generic "professional but friendly" register. Competitors at the SaaS-content layer (Jasper, Copy.ai) treat this as a setting, not the spine.
- **Competitor pattern intelligence** — what they ship, when, in which format, with which hooks, with which visual idiom. Competitors at the competitive-intel layer (Foreplay, BuiltWith, Sprout Social) have great data but no execution engine attached. They show you the gap; they don't fill it.
- **Peec visibility ground truth** — the *outcome* that matters in the LLM-answer-engine era. GEO platforms (Profound, Peec, Writesonic) report citation share-of-voice as the metric, but they're mostly read-only dashboards; they don't drive content production.

Each leg alone is a feature. Voice fine-tuning alone is a "writes in your style" toy. Competitor pattern intelligence alone is a dashboard. Peec data alone is a measurement layer. **Stitched together, they form the loop**: we measure where you're absent (Peec), see what's working in your space (competitor patterns), and produce a counter-piece in your own voice (per-tenant voice). The home-screen feed of counter-move cards *is* that loop made visible. Each card is an instance of "Peec saw a gap → competitor analysis explains the shape → voice profile ships the move." That's the demo, that's the moat, and that's what makes "copy marketing from others" the right top-level capability on the whiteboard — because we read it as *outcompete by learning, not by copying*.

---

## Sources

- [Foreplay — Spyder Ad Spy / Hook extraction](https://www.foreplay.co/spyder-ad-spy)
- [Foreplay — Discovery and competitor tracking](https://www.foreplay.co/discovery)
- [Pragmatic Institute — Legal and Ethical Guardrails for Sound Competitive Intelligence](https://www.pragmaticinstitute.com/resources/articles/product/the-legal-and-ethical-guardrails-for-sound-competitive-intelligence/)
- [Peec.ai — Share of Voice docs](https://docs.peec.ai/metrics/brand-metrics/share-of-voice)
- [Peec AI Review — visibility tracking and competitive citation](https://discoveredlabs.com/blog/peec-ai-review-best-for-ai-visibility-monitoring-use-cases-limits-alternatives)
- [Backlinko — Generative Engine Optimization (GEO)](https://backlinko.com/generative-engine-optimization-geo)
- [Profound — 10-step framework for GEO 2025](https://www.tryprofound.com/resources/articles/generative-engine-optimization-geo-guide-2025)
- [BuiltWith — Sales Intelligence (tech signals)](https://builtwith.com/sales-intelligence)
- [Sprout Social — Strengthen competitive analysis with social listening (2026)](https://sproutsocial.com/insights/strengthen-competitive-analysis-strategy-social-listening/)
- [StoryChief — Competitive Content Analysis: Ultimate 2025 Guide](https://storychief.io/blog/competitive-content-analysis)
- [BestEver — 10 Ad Hook Styles Marketers Swear By In 2025](https://www.bestever.ai/post/marketing-hooks)
- [Social Insider — How to Run a Content Competitor Analysis](https://www.socialinsider.io/blog/content-competitor-analysis/)
