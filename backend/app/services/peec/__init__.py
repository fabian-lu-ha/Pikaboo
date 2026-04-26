"""Peec MCP / REST integration.

Two paths to the same data surface, fronted by ``fetch_snapshot``:

  - **MCP** (preferred) — full OAuth 2.1 + DCR + PKCE against
    ``https://api.peec.ai/mcp``. Used when the user has run the
    ``/api/peec/mcp/login/start`` flow. See ``mcp_auth`` / ``mcp_client``.
  - **REST** (fallback) — ``x-api-key`` against ``api.peec.ai/customer/v1``.
    Stays as a graceful degrade when MCP isn't connected.
"""

from app.services.peec.client import PeecClient, get_peec
from app.services.peec.mcp_client import (
    PeecMCPNotConnectedError,
    call_tool,
    list_tools,
    peec_mcp_session,
)
from app.services.peec.mcp_snapshot import fetch_snapshot_via_mcp
from app.services.peec.snapshot import (
    PeecSnapshot,
    TargetPrompt,
    fetch_snapshot,
    select_target_prompts,
)

__all__ = [
    "PeecClient",
    "PeecMCPNotConnectedError",
    "PeecSnapshot",
    "TargetPrompt",
    "call_tool",
    "fetch_snapshot",
    "fetch_snapshot_via_mcp",
    "get_peec",
    "list_tools",
    "peec_mcp_session",
    "select_target_prompts",
]
