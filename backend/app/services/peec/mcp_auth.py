"""OAuth 2.1 + Dynamic Client Registration for Peec MCP.

Peec advertises itself as both the protected resource and the auth server
(https://api.peec.ai/mcp). It supports authorization_code + refresh_token
grants with PKCE S256 and accepts ``token_endpoint_auth_method=none``, so we
register as a public client and rely on PKCE for the security guarantee.

Persistence: client credentials and tokens live under
``{storage_dir}/peec_mcp/`` as plain JSON. Hackathon-grade, single-tenant.

Flow:
  1. ``ensure_client_registered()`` — DCR on first use, caches client_id/secret
  2. ``build_authorization_url(redirect_uri)`` — generates PKCE pair + state,
     stashes verifier in memory, returns the consent URL
  3. ``exchange_code(code, state, redirect_uri)`` — completes the dance,
     persists access + refresh tokens
  4. ``get_access_token()`` — returns a live token, auto-refreshing if expired
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Standard OAuth-protected-resource discovery (RFC 9728). Peec lives at the
# `/mcp` subpath, so the metadata is served from /.well-known/.../mcp.
AUTHZ_METADATA_URL = (
    "https://api.peec.ai/.well-known/oauth-authorization-server/mcp"
)
RESOURCE_URL = "https://api.peec.ai/mcp"


@dataclass
class _Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: float  # epoch seconds
    token_type: str = "Bearer"
    scope: str | None = None
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "scope": self.scope,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_Tokens":
        return cls(
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token"),
            expires_at=float(d.get("expires_at") or 0),
            token_type=d.get("token_type", "Bearer"),
            scope=d.get("scope"),
            raw=d.get("raw") or {},
        )


@dataclass
class _ClientInfo:
    client_id: str
    client_secret: str | None
    auth_endpoint: str
    token_endpoint: str
    revocation_endpoint: str | None
    registration_endpoint: str | None
    issuer: str
    redirect_uris: list[str]

    def as_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "_ClientInfo":
        return cls(**d)


# ---------------------------------------------------------------------------
# Disk persistence — single-tenant JSON files under storage_dir/peec_mcp/
# ---------------------------------------------------------------------------


def _store_dir() -> Path:
    """Anchor the OAuth token cache to an absolute path so it doesn't
    drift between cwds.

    ``settings.storage_dir`` defaults to ``./storage`` — that resolves
    relative to wherever uvicorn was launched. Running ``uvicorn
    app.main:app`` from ``backend/`` writes to ``backend/storage``;
    running ``uvicorn backend.app.main:app`` from the repo root writes
    to ``./storage``. The OAuth callback would land tokens in one and
    the snapshot fetcher would look in the other. Anchoring to the
    backend directory makes the path stable regardless of cwd.
    """
    raw = Path(settings.storage_dir)
    if not raw.is_absolute():
        # __file__ → backend/app/services/peec/mcp_auth.py
        # parents[3] → backend/
        backend_root = Path(__file__).resolve().parents[3]
        raw = backend_root / raw
    p = raw / "peec_mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _client_path() -> Path:
    return _store_dir() / "client.json"


def _tokens_path() -> Path:
    return _store_dir() / "tokens.json"


def _read_client() -> _ClientInfo | None:
    p = _client_path()
    if not p.exists():
        return None
    try:
        return _ClientInfo.from_dict(json.loads(p.read_text()))
    except Exception as e:  # noqa: BLE001
        log.warning("peec_mcp: bad client.json (%s) — re-registering", e)
        return None


def _write_client(info: _ClientInfo) -> None:
    _client_path().write_text(json.dumps(info.as_dict(), indent=2))


def _read_tokens() -> _Tokens | None:
    p = _tokens_path()
    if not p.exists():
        return None
    try:
        return _Tokens.from_dict(json.loads(p.read_text()))
    except Exception as e:  # noqa: BLE001
        log.warning("peec_mcp: bad tokens.json (%s)", e)
        return None


def _write_tokens(tok: _Tokens) -> None:
    _tokens_path().write_text(json.dumps(tok.as_dict(), indent=2))


def _delete_tokens() -> None:
    p = _tokens_path()
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# In-memory auth state (state -> pkce_verifier). Survives the brief window
# between /login/start and the user's redirect-back. Process-local; if the
# server restarts mid-flow the user re-clicks Connect.
# ---------------------------------------------------------------------------

_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_TTL_SECONDS = 600  # 10 minutes
_lock = asyncio.Lock()


def _gc_pending() -> None:
    now = time.time()
    stale = [k for k, v in _PENDING.items() if now - v["created_at"] > _PENDING_TTL_SECONDS]
    for k in stale:
        _PENDING.pop(k, None)


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    )
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# OAuth metadata discovery
# ---------------------------------------------------------------------------


async def _discover_metadata() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(AUTHZ_METADATA_URL)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PeecMCPAuthError(Exception):
    """Anything that goes wrong in the OAuth dance."""


def default_redirect_uri() -> str:
    base = settings.server_base_url.rstrip("/")
    return f"{base}/api/peec/mcp/login/callback"


async def ensure_client_registered(
    redirect_uri: str | None = None,
) -> _ClientInfo:
    """DCR on first use; cache the result. Returns the cached client info on
    subsequent calls. ``redirect_uri`` defaults to ``default_redirect_uri()``.
    """
    redirect_uri = redirect_uri or default_redirect_uri()
    existing = _read_client()
    if existing is not None and redirect_uri in existing.redirect_uris:
        return existing

    meta = await _discover_metadata()
    reg_endpoint = meta.get("registration_endpoint")
    if not reg_endpoint:
        raise PeecMCPAuthError(
            "auth server doesn't advertise registration_endpoint"
        )

    body = {
        "client_name": "Brand Autopilot",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # public client + PKCE
    }
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(reg_endpoint, json=body)
    if r.status_code not in (200, 201):
        raise PeecMCPAuthError(
            f"DCR failed: {r.status_code} {r.text[:200]}"
        )
    data = r.json()

    info = _ClientInfo(
        client_id=data["client_id"],
        client_secret=data.get("client_secret"),
        auth_endpoint=meta["authorization_endpoint"],
        token_endpoint=meta["token_endpoint"],
        revocation_endpoint=meta.get("revocation_endpoint"),
        registration_endpoint=reg_endpoint,
        issuer=meta.get("issuer") or RESOURCE_URL,
        redirect_uris=[redirect_uri],
    )
    _write_client(info)
    return info


async def build_authorization_url(
    redirect_uri: str | None = None,
) -> tuple[str, str]:
    """Start a login. Returns ``(auth_url, state)``. Caller redirects the
    user's browser to ``auth_url``."""
    redirect_uri = redirect_uri or default_redirect_uri()
    client = await ensure_client_registered(redirect_uri)

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    async with _lock:
        _gc_pending()
        _PENDING[state] = {
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "created_at": time.time(),
        }

    params = {
        "response_type": "code",
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "mcp",  # harmless if server ignores
    }
    qs = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return f"{client.auth_endpoint}?{qs}", state


async def exchange_code(code: str, state: str) -> _Tokens:
    """Trade the auth code for tokens. Persists them on success."""
    async with _lock:
        _gc_pending()
        pending = _PENDING.pop(state, None)
    if pending is None:
        raise PeecMCPAuthError(f"unknown or expired state: {state[:8]}…")

    client = _read_client()
    if client is None:
        raise PeecMCPAuthError("client not registered (lost client.json?)")

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        "client_id": client.client_id,
        "code_verifier": pending["verifier"],
    }
    if client.client_secret:
        body["client_secret"] = client.client_secret

    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            client.token_endpoint,
            data=body,
            headers={"Accept": "application/json"},
        )
    if r.status_code != 200:
        raise PeecMCPAuthError(
            f"token exchange failed: {r.status_code} {r.text[:200]}"
        )
    data = r.json()
    tokens = _from_token_response(data)
    _write_tokens(tokens)
    return tokens


async def refresh_tokens() -> _Tokens:
    """Use the persisted refresh_token to mint a new access_token."""
    client = _read_client()
    tokens = _read_tokens()
    if client is None or tokens is None or not tokens.refresh_token:
        raise PeecMCPAuthError("no refresh_token available")

    body = {
        "grant_type": "refresh_token",
        "refresh_token": tokens.refresh_token,
        "client_id": client.client_id,
    }
    if client.client_secret:
        body["client_secret"] = client.client_secret

    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            client.token_endpoint,
            data=body,
            headers={"Accept": "application/json"},
        )
    if r.status_code != 200:
        raise PeecMCPAuthError(
            f"refresh failed: {r.status_code} {r.text[:200]}"
        )
    data = r.json()
    new_tokens = _from_token_response(data)
    # Some servers don't return a new refresh_token; carry the old one across.
    if not new_tokens.refresh_token:
        new_tokens.refresh_token = tokens.refresh_token
    _write_tokens(new_tokens)
    return new_tokens


def _from_token_response(data: dict) -> _Tokens:
    expires_in = int(data.get("expires_in") or 3600)
    return _Tokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=time.time() + max(60, expires_in - 30),  # 30s safety
        token_type=data.get("token_type", "Bearer"),
        scope=data.get("scope"),
        raw=data,
    )


async def get_access_token() -> str | None:
    """Return a live access token, refreshing if needed. None if not connected."""
    tokens = _read_tokens()
    if tokens is None:
        return None
    if time.time() < tokens.expires_at:
        return tokens.access_token
    try:
        refreshed = await refresh_tokens()
    except PeecMCPAuthError as e:
        log.warning("peec_mcp: refresh failed (%s) — disconnecting", e)
        _delete_tokens()
        return None
    return refreshed.access_token


async def disconnect() -> None:
    """Best-effort revoke + wipe local tokens."""
    client = _read_client()
    tokens = _read_tokens()
    if client and tokens and client.revocation_endpoint:
        body = {
            "token": tokens.refresh_token or tokens.access_token,
            "client_id": client.client_id,
        }
        if client.client_secret:
            body["client_secret"] = client.client_secret
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                await c.post(client.revocation_endpoint, data=body)
        except Exception as e:  # noqa: BLE001
            log.warning("peec_mcp: revoke failed: %s", e)
    _delete_tokens()


def status() -> dict:
    """Snapshot of connection state for the API."""
    tokens = _read_tokens()
    client = _read_client()
    if tokens is None:
        return {
            "connected": False,
            "registered": client is not None,
            "client_id": client.client_id if client else None,
        }
    return {
        "connected": True,
        "registered": True,
        "client_id": client.client_id if client else None,
        "expires_at": tokens.expires_at,
        "expires_in_seconds": max(0, int(tokens.expires_at - time.time())),
        "has_refresh_token": tokens.refresh_token is not None,
        "scope": tokens.scope,
    }
