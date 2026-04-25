"""Peec MCP / REST integration.

Hackathon path is REST-first using x-api-key against api.peec.ai/customer/v1
(simpler than the MCP OAuth dance, identical data surface). The MCP wrapper
sits on top of the same data and is added later for contest-credible 'MCP
integration' framing.
"""

from app.services.peec.client import PeecClient, get_peec
from app.services.peec.snapshot import (
    PeecSnapshot,
    TargetPrompt,
    fetch_snapshot,
    select_target_prompts,
)

__all__ = [
    "PeecClient",
    "PeecSnapshot",
    "TargetPrompt",
    "fetch_snapshot",
    "get_peec",
    "select_target_prompts",
]
