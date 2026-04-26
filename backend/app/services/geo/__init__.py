"""Generative-Engine Optimization (GEO) — closes the loop on Peec.

Peec measures: which prompts the brand is absent from, which competitor wins.
This package turns each gap into a recommended action and a generated asset.

Pipeline:
  detect_gaps(brand)      → persist GeoGap rows from latest Peec snapshot
  recommend(gap)          → Gemini call → GeoRecommendation row
  generate_asset(reco)    → per-action_type generator → GeoAsset row
  publish(asset)          → mark published + emit event

Action types correspond to the research-grounded GEO playbook (see
``playbook.py``):
  - comparison_page       (32.5% of AI citations land on listicle/comparison)
  - definition_first      (44.2% of citations from page's first 30%)
  - faq_schema            (FAQPage JSON-LD; +78% citation odds)
  - stats_quote           (Princeton GEO paper: stats + quote = +30-40% lift)
  - wikidata_schema       (Organization sameAs to Wikidata; ChatGPT entity wedge)
  - reddit_draft          (queued for human approval; never auto-posted)
"""

from app.services.geo.asset_generator import generate_asset
from app.services.geo.gap_detector import detect_gaps_for_brand, scan_for_brand
from app.services.geo.playbook import (
    ACTION_TYPES,
    ENGINE_PLAYBOOK,
    action_type_label,
    action_type_summary,
)
from app.services.geo.recommender import recommend_for_gap

__all__ = [
    "ACTION_TYPES",
    "ENGINE_PLAYBOOK",
    "action_type_label",
    "action_type_summary",
    "detect_gaps_for_brand",
    "generate_asset",
    "recommend_for_gap",
    "scan_for_brand",
]
