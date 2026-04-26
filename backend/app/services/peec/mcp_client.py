"""Async context manager that yields an MCP ``ClientSession`` for Peec.

Auth is handled by ``mcp_auth`` — we call ``get_access_token`` and inject
``Authorization: Bearer ...`` via the streamable-HTTP transport's headers
arg, sidestepping the SDK's interactive ``OAuthClientProvider`` (we already
own the token persistence and refresh).

Usage::

    async with peec_mcp_session() as session:
        tools = await session.list_tools()
        result = await session.call_tool("list_prompts", {})
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import settings
from app.services.peec.mcp_auth import (
    PeecMCPAuthError,
    get_access_token,
)

log = logging.getLogger(__name__)


class PeecMCPNotConnectedError(Exception):
    """Raised when the user hasn't completed the OAuth flow yet."""


@asynccontextmanager
async def peec_mcp_session():
    """Yield an initialized MCP ``ClientSession`` connected to Peec."""
    token = await get_access_token()
    if token is None:
        raise PeecMCPNotConnectedError(
            "peec mcp not connected — run /api/peec/mcp/login/start first"
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": "2025-06-18",
    }
    async with streamablehttp_client(
        settings.peec_mcp_url, headers=headers
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_tools() -> list[dict]:
    """Discover what Peec's MCP exposes. Returns a list of tool descriptors."""
    async with peec_mcp_session() as session:
        result = await session.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.inputSchema,
        }
        for t in result.tools
    ]


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Call a Peec MCP tool by name. Returns the parsed content payload —
    the SDK normalizes ``content`` blocks; we extract text/JSON best-effort."""
    async with peec_mcp_session() as session:
        result = await session.call_tool(name, arguments or {})

    if result.isError:
        raise PeecMCPAuthError(
            f"peec mcp tool {name!r} returned error: "
            f"{[c.model_dump() for c in result.content][:1]}"
        )

    # Best-effort content unwrapping. MCP returns a list of content blocks
    # (text, image, embedded resource); for Peec we expect text/JSON.
    out: list[Any] = []
    for block in result.content:
        if block.type == "text":
            text = block.text
            try:
                import json

                out.append(json.loads(text))
            except Exception:
                out.append(text)
        else:
            out.append(block.model_dump())
    if len(out) == 1:
        return out[0]
    return out
