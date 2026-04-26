"""AI-described asset library.

Calls Gemini Vision on each Asset row's image bytes to produce one concise
visual description, 5-8 entity tags, and a best-fit cast_kind hint. The
description flows into the storyboard planner so it can pick the right
asset for each cast slot it generates.
"""

from app.services.asset_describe.describe import (
    describe_asset,
    describe_brand_assets,
    schedule_describe,
)

__all__ = ["describe_asset", "describe_brand_assets", "schedule_describe"]
