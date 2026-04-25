"""Predicted-lift estimator.

v0 is a deterministic heuristic grounded in the KDD 2024 GEO paper — quotation
blocks (+42.6%), statistic callouts (+32.8%), schema markup (+30%), listicle
structure (+25%). It scans the actual draft text for those features and
produces a per-campaign lift estimate.

v1 (post-hackathon) replaces this with a real Peec MCP call: query for the
target prompts, return current visibility, project lift from the proposed
content's overlap with the citation surfaces of competitors who already win
those prompts.
"""

import re

_QUOTE_RE = re.compile(r'"[^"]{30,}"|"[^"]{30,}"|\*[^\*]{30,}\*')
_STAT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%|\b\d+\s*x\b", re.I)
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+", re.MULTILINE)


def predict_lift(
    user_request: str,
    target_prompts: list[str],
    draft_bodies: list[str],
) -> dict:
    body = "\n\n".join(b for b in draft_bodies if b)

    quotes = len(_QUOTE_RE.findall(body))
    stats = len(_STAT_RE.findall(body))
    list_items = len(_LIST_LINE_RE.findall(body))

    factors: list[str] = []
    lift = 0.0

    if quotes:
        contrib = min(quotes * 12.0, 30.0)
        lift += contrib
        factors.append(
            f"+{contrib:.0f}% from {quotes} quotation block(s) (KDD 2024: +42.6% per quote)"
        )
    if stats:
        contrib = min(stats * 8.0, 25.0)
        lift += contrib
        factors.append(
            f"+{contrib:.0f}% from {stats} statistic callout(s) (KDD 2024: +32.8% per stat)"
        )
    if list_items >= 3:
        lift += 10.0
        factors.append(f"+10% from listicle structure ({list_items} items)")

    if lift == 0.0:
        lift = 8.0
        factors.append("+8% baseline for new on-voice content")

    confidence = "medium" if lift > 18 else "low-medium"

    return {
        "lift_percent": round(lift, 1),
        "confidence": confidence,
        "factors": factors,
        "target_prompts": target_prompts,
        "research_basis": (
            "KDD 2024 GEO paper · quotation +42.6% · statistic +32.8% · "
            "listicle structure ~+25%. v0 mock — Peec MCP integration "
            "would replace this with real prompt-visibility data."
        ),
    }
