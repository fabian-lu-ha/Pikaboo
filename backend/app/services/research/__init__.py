"""Tavily-backed web research.

Two surfaces:
  - ``tavily.get_tavily()`` — raw async client, returns None when no key.
  - ``orchestrator.gather_brand_context(...)`` etc. — high-level helpers
    that emit research.* events on the bus and return plain dicts safe to
    persist on the Brand row.

All callers MUST treat None / empty results as a graceful skip, not an
error — the demo still flows when ``TAVILY_API_KEY`` is unset.
"""

from app.services.research.orchestrator import (
    BrandResearch,
    CampaignResearch,
    CompetitorIntel,
    gather_brand_context,
    gather_campaign_context,
    gather_competitor_intel,
)
from app.services.research.tavily import TavilyClient, TavilyError, get_tavily

__all__ = [
    "BrandResearch",
    "CampaignResearch",
    "CompetitorIntel",
    "TavilyClient",
    "TavilyError",
    "gather_brand_context",
    "gather_campaign_context",
    "gather_competitor_intel",
    "get_tavily",
]
