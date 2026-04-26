"""Peec MCP connection API.

OAuth dance:
  POST /api/peec/mcp/login/start    -> {auth_url, state}
  GET  /api/peec/mcp/login/callback -> redirected here by Peec; finishes
                                       the exchange, then HTML-redirects the
                                       user back to the frontend
  GET  /api/peec/mcp/status         -> connected / disconnected
  POST /api/peec/mcp/disconnect     -> revoke + wipe local tokens
  GET  /api/peec/mcp/tools          -> debug: list discovered tools
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.events.bus import bus
from app.events.types import Events
from app.services.peec import mcp_auth
from app.services.peec.mcp_client import (
    PeecMCPNotConnectedError,
    list_tools as mcp_list_tools,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/peec/mcp")


class LoginStartIn(BaseModel):
    redirect_uri: str | None = None


class LoginStartOut(BaseModel):
    auth_url: str
    state: str


@router.post("/login/start", response_model=LoginStartOut)
async def login_start(body: LoginStartIn | None = None) -> LoginStartOut:
    redirect_uri = (body.redirect_uri if body else None) or None
    try:
        url, state = await mcp_auth.build_authorization_url(redirect_uri)
    except mcp_auth.PeecMCPAuthError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return LoginStartOut(auth_url=url, state=state)


@router.get("/login/callback", response_class=HTMLResponse)
async def login_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    """Peec redirects here after the user consents. We exchange the code,
    persist tokens, and render a tiny page that closes the popup or
    auto-redirects back to the frontend."""
    if error:
        msg = error_description or error
        return _render_callback_page(False, msg)
    if not code or not state:
        return _render_callback_page(False, "missing code/state")

    try:
        await mcp_auth.exchange_code(code, state)
    except mcp_auth.PeecMCPAuthError as e:
        log.warning("peec_mcp callback exchange failed: %s", e)
        return _render_callback_page(False, str(e))

    bus.emit(Events.PEEC_MCP_CONNECTED, {})
    return _render_callback_page(True, "Peec MCP connected")


@router.get("/status")
async def status() -> dict:
    return mcp_auth.status()


@router.post("/disconnect")
async def disconnect() -> dict:
    await mcp_auth.disconnect()
    bus.emit(Events.PEEC_MCP_DISCONNECTED, {})
    return {"ok": True}


@router.get("/tools")
async def tools() -> dict:
    try:
        tools = await mcp_list_tools()
    except PeecMCPNotConnectedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("peec_mcp tools listing failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"tools": tools}


def _render_callback_page(ok: bool, message: str) -> HTMLResponse:
    color = "#22a07a" if ok else "#d04848"
    title = "Peec MCP connected" if ok else "Peec MCP connection failed"
    safe_message = (
        message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font: 14px/1.5 system-ui, sans-serif; padding: 40px;
         color: #1a1a2e; background: #f5f5f7; }}
  .card {{ max-width: 480px; margin: 80px auto; padding: 32px;
          border-radius: 16px; background: white;
          box-shadow: 0 8px 30px rgba(20,20,40,0.08); }}
  h1 {{ font-size: 18px; margin: 0 0 12px; color: {color}; }}
  p  {{ margin: 0 0 16px; color: #64647e; }}
  code {{ font-size: 12px; color: #6f5cff; }}
</style></head>
<body><div class="card">
  <h1>{title}</h1>
  <p>{safe_message}</p>
  <p>You can close this window.</p>
  <script>setTimeout(() => window.close(), 1500);</script>
</div></body></html>"""
    return HTMLResponse(body, status_code=200 if ok else 400)
