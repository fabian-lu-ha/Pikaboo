"""Trello adapter.

Auth: API key + token (URL-style, classic Trello).
Webhooks: HMAC-SHA1 over (rawBody + callbackURL) using the API secret,
base64-encoded, in the ``X-Trello-Webhook`` header. Strict verification
needs the *raw* request bytes — see the note in ``parse_webhook``.
Rate limit: 300 req / 10s per token, 100 req / 10s per key.

Docs: https://developer.atlassian.com/cloud/trello/rest/
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.kanban.providers.base import KanbanProvider
from app.services.kanban.types import (
    CardEvent,
    CardEventType,
    NormalizedCard,
    ProviderConnection,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.trello.com/1"


def _auth_params(creds: dict) -> dict:
    return {"key": creds.get("api_key", ""), "token": creds.get("token", "")}


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize(card: dict, board_name: str, list_name: str) -> NormalizedCard:
    labels = [
        str(l.get("name") or l.get("color") or "")
        for l in (card.get("labels") or [])
        if l
    ]
    return NormalizedCard(
        provider="trello",
        external_id=str(card["id"]),
        board_id=str(card.get("idBoard") or ""),
        board_name=board_name,
        column=list_name,
        title=str(card.get("name") or ""),
        description=str(card.get("desc") or ""),
        labels=[l for l in labels if l],
        assignee=None,  # Trello cards have multiple members; defer
        due_date=_parse_iso(card.get("due")),
        moved_at=_parse_iso(card.get("dateLastActivity")),
        url=card.get("url"),
        raw=card,
    )


class TrelloProvider(KanbanProvider):
    name = "trello"

    async def test_connection(self, credentials: dict) -> bool:
        params = _auth_params(credentials)
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{API_BASE}/members/me", params=params)
        return r.status_code == 200

    async def list_boards(self, conn: ProviderConnection) -> list[dict]:
        params = {**_auth_params(conn.credentials), "fields": "name,url,closed"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{API_BASE}/members/me/boards", params=params)
        r.raise_for_status()
        return [
            {"id": b["id"], "name": b.get("name", ""), "url": b.get("url", "")}
            for b in r.json()
            if not b.get("closed")
        ]

    async def list_cards(
        self,
        conn: ProviderConnection,
        board_id: str,
        since: Any | None = None,
    ) -> list[NormalizedCard]:
        params = {
            **_auth_params(conn.credentials),
            "lists": "open",
            "list_fields": "name",
            "card_fields": (
                "name,desc,due,dateLastActivity,labels,idList,idBoard,url"
            ),
            "cards": "open",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{API_BASE}/boards/{board_id}", params=params)
        r.raise_for_status()
        data = r.json()
        board_name = data.get("name", "")
        lists_by_id = {
            l["id"]: l.get("name", "") for l in data.get("lists", [])
        }

        out: list[NormalizedCard] = []
        for c in data.get("cards") or []:
            list_name = lists_by_id.get(c.get("idList"), "")
            n = _normalize(c, board_name, list_name)
            if since and (not n.moved_at or n.moved_at < since):
                continue
            out.append(n)
        return out

    async def register_webhook(
        self,
        conn: ProviderConnection,
        callback_url: str,
        board_id: str,
    ) -> str:
        params = _auth_params(conn.credentials)
        body = {
            "description": f"brand-autopilot:{board_id}",
            "callbackURL": callback_url,
            "idModel": board_id,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{API_BASE}/webhooks/", params=params, json=body
            )
        r.raise_for_status()
        return str(r.json().get("id") or "")

    async def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        secret: str | None = None,
    ) -> CardEvent | None:
        # Strict signature verification needs raw body bytes; the FastAPI
        # entrypoint gives us parsed JSON. Wire raw body through before
        # treating this as authenticated.
        if secret:
            sig = headers.get("X-Trello-Webhook") or headers.get(
                "x-trello-webhook"
            )
            if not sig:
                log.warning("trello webhook: missing signature header")

        action = payload.get("action") or {}
        action_type = action.get("type", "")

        # Trello fires `webhookSelfDelete` on the registration probe.
        if not action_type or action_type == "webhookSelfDelete":
            return None

        data = action.get("data") or {}
        card = data.get("card") or {}
        if not card.get("id"):
            return None

        board = data.get("board") or {}
        list_after = data.get("listAfter") or data.get("list") or {}
        list_before = data.get("listBefore") or {}

        normalized = NormalizedCard(
            provider="trello",
            external_id=str(card["id"]),
            board_id=str(board.get("id") or ""),
            board_name=str(board.get("name") or ""),
            column=str(list_after.get("name") or ""),
            title=str(card.get("name") or ""),
            description="",
            url=(
                f"https://trello.com/c/"
                f"{card.get('shortLink') or card['id']}"
            ),
            moved_at=datetime.now(timezone.utc),
            raw=action,
        )

        if action_type == "createCard":
            event_type = CardEventType.CREATED
        elif action_type == "deleteCard":
            event_type = CardEventType.DELETED
        elif action_type == "updateCard":
            if list_after and list_before:
                event_type = CardEventType.MOVED
            elif card.get("dueComplete") is True:
                event_type = CardEventType.COMPLETED
            else:
                event_type = CardEventType.UPDATED
        else:
            event_type = CardEventType.UPDATED

        return CardEvent(
            type=event_type,
            card=normalized,
            previous_column=list_before.get("name") if list_before else None,
            received_at=datetime.now(timezone.utc),
        )
