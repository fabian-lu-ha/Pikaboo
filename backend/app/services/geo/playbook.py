"""Research-grounded GEO playbook — the action menu the recommender picks
from, plus the per-engine knobs that bias which actions matter most.

Sources (all consolidated in the GEO research brief):
  - Princeton/Georgia Tech GEO paper (arXiv 2311.09735): stats + quotation +
    citation injection lifts AI citations 30-40%.
  - ConvertMate 2026 GEO benchmark: 44.2% of citations from first 30% of page;
    definition-first ledes get chunked cleanly.
  - Averi B2B SaaS 2026: 32.5% of all AI citations land on comparison pages
    /listicles. FAQ + HowTo schema +78% citation odds.
  - Goodie / Profound / ZipTie domain studies: G2/Wikipedia/Reddit/YouTube
    dominate cited domains — owned content is the floor, earned mentions
    the ceiling.
  - upGrowth schema patterns 2026: Organization sameAs to Wikidata is the
    most under-used high-leverage tag, esp. for ChatGPT/Gemini.
"""

from __future__ import annotations

ACTION_TYPES: tuple[str, ...] = (
    "comparison_page",
    "definition_first",
    "faq_schema",
    "stats_quote",
    "wikidata_schema",
    "reddit_draft",
)


_LABELS: dict[str, str] = {
    "comparison_page": "Competitor Comparison Page",
    "definition_first": "Definition-First Page Rewrite",
    "faq_schema": "FAQ Block + FAQPage JSON-LD",
    "stats_quote": "Stats + Quote Injection",
    "wikidata_schema": "Wikidata + Organization JSON-LD",
    "reddit_draft": "Reddit Answer Draft (human approval)",
}


_SUMMARIES: dict[str, str] = {
    "comparison_page": (
        "Programmatic 'X vs Competitor' page with feature table, balanced "
        "voice, and citation-heavy body. Comparative listicles capture 32.5% "
        "of all AI-engine citations — the single highest-yield format."
    ),
    "definition_first": (
        "Rewrite an existing page so the first sentence is a clean definition "
        "('X is a Y that does Z'). 44.2% of LLM citations come from the first "
        "30% of a page; definition-first ledes get chunked cleanly by retrievers."
    ),
    "faq_schema": (
        "Inject an FAQ Q&A block on the target page plus FAQPage JSON-LD. "
        "Schema'd pages are cited 8.2× more often; FAQ/HowTo specifically "
        "lifts citation odds by 78%."
    ),
    "stats_quote": (
        "Inject one expert quote, one specific statistic, and one outbound "
        "citation into a target page. The Princeton/Georgia Tech GEO paper "
        "showed this combo lifts position-adjusted citation share 30-40%."
    ),
    "wikidata_schema": (
        "Generate Organization JSON-LD with sameAs to Wikidata, LinkedIn, "
        "Crunchbase, GitHub. The most under-used high-leverage tag; "
        "ChatGPT pulls ~7.8% of all citations from Wikipedia/Wikidata."
    ),
    "reddit_draft": (
        "Surface 1-3 Reddit threads where the brand is a genuine answer to "
        "the gap prompt; draft a human-voice reply. Reddit drives 5-21% of "
        "citations across engines, but auto-posting gets banned — always "
        "human-in-loop."
    ),
}


# Per-engine playbook — which action_types matter most for each engine, and
# why. Used by the recommender to bias action selection toward whichever
# engine the brand cares about most. Surfaced verbatim in the dashboard so
# users see *why* an action was picked.
ENGINE_PLAYBOOK: dict[str, dict] = {
    "chatgpt": {
        "label": "ChatGPT",
        "retrieval": "Bing-fed (~87% overlap with Bing top-10).",
        "high_leverage": [
            "wikidata_schema",
            "comparison_page",
            "faq_schema",
        ],
        "note": (
            "Wikipedia/Wikidata is its #1 source. Push to Bing Webmaster + "
            "IndexNow on every new asset."
        ),
    },
    "perplexity": {
        "label": "Perplexity",
        "retrieval": "Sonar retrieval, recency-weighted, 8-12 sources/answer.",
        "high_leverage": [
            "stats_quote",
            "comparison_page",
            "definition_first",
        ],
        "note": (
            "Refresh flagship pages monthly. Reddit was huge until the Oct "
            "2025 lawsuit; YouTube absorbed the gap."
        ),
    },
    "google_ai_overviews": {
        "label": "Google AI Overviews",
        "retrieval": "Domain authority + Reddit (21%) + YouTube (18.8%).",
        "high_leverage": [
            "faq_schema",
            "wikidata_schema",
            "reddit_draft",
        ],
        "note": "Schema is the strongest controllable signal here.",
    },
    "claude": {
        "label": "Claude",
        "retrieval": "Long-form blog editorial bias (~43.8% of top citations).",
        "high_leverage": [
            "definition_first",
            "stats_quote",
            "comparison_page",
        ],
        "note": "Canonical URLs. No soft-paywall games. Long-form depth wins.",
    },
    "gemini": {
        "label": "Gemini",
        "retrieval": "Knowledge Graph integration, Wikidata-heavy.",
        "high_leverage": [
            "wikidata_schema",
            "faq_schema",
            "comparison_page",
        ],
        "note": "Reddit citation share is ~0.1% — don't over-invest there.",
    },
}


def action_type_label(action_type: str) -> str:
    return _LABELS.get(action_type, action_type)


def action_type_summary(action_type: str) -> str:
    return _SUMMARIES.get(action_type, "")
