"""Tavily REST client — thin async wrapper around api.tavily.com.

Mirrors the ``peec.client`` pattern: every method returns plain dicts /
lists so callers stay decoupled from Tavily's exact response shape, and
``get_tavily()`` returns None when no key is configured so the orchestrator
can skip the research leg without crashing.

Endpoints used:
  - POST /search   — web search with snippets, optional answer + raw_content
  - POST /extract  — pull clean main-body text from one or more URLs
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from app.config import settings

log = logging.getLogger(__name__)


SearchDepth = Literal["basic", "advanced"]
SearchTopic = Literal["general", "news"]


class TavilyError(Exception):
    pass


class TavilyClient:
    def __init__(self) -> None:
        self._key = settings.tavily_api_key
        self._base = settings.tavily_base_url.rstrip("/")
        if not self._key:
            raise TavilyError("TAVILY_API_KEY not set")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._key}",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "brand-autopilot/0.1 (hackathon)",
        }

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                resp = await c.post(url, headers=self._headers, json=body)
        except httpx.HTTPError as e:
            raise TavilyError(f"POST {path}: network error ({e})") from e
        if resp.status_code != 200:
            raise TavilyError(
                f"POST {path} {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as e:
            raise TavilyError(f"POST {path}: bad JSON ({e})") from e

    async def search(
        self,
        query: str,
        *,
        depth: SearchDepth | None = None,
        topic: SearchTopic = "general",
        max_results: int | None = None,
        include_answer: bool | str = False,
        days: int | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a Tavily search. Returns the raw JSON envelope:
        ``{query, answer?, results: [{title, url, content, score, ...}], ...}``.
        """
        body: dict[str, Any] = {
            "query": query.strip(),
            "search_depth": depth or settings.tavily_default_depth,
            "topic": topic,
            "max_results": max_results or settings.tavily_max_results,
            "include_answer": include_answer,
        }
        if days is not None and topic == "news":
            body["days"] = days
        if include_domains:
            body["include_domains"] = include_domains
        if exclude_domains:
            body["exclude_domains"] = exclude_domains
        return await self._post("/search", body)

    async def extract(
        self,
        urls: list[str],
        *,
        depth: SearchDepth | None = None,
    ) -> dict[str, Any]:
        """Pull clean text from up to 20 URLs in one call. Returns
        ``{results: [{url, raw_content, ...}], failed_results: [...]}``."""
        if not urls:
            return {"results": [], "failed_results": []}
        body: dict[str, Any] = {
            "urls": urls[:20],
            "extract_depth": depth or settings.tavily_default_depth,
        }
        return await self._post("/extract", body)


_client: TavilyClient | None = None


def get_tavily() -> TavilyClient | None:
    """Returns None if ``TAVILY_API_KEY`` isn't set — caller MUST degrade
    gracefully (skip research, not raise)."""
    global _client
    if _client is not None:
        return _client
    if not settings.tavily_api_key:
        return None
    try:
        _client = TavilyClient()
    except TavilyError as e:
        log.warning("tavily client init failed: %s", e)
        return None
    return _client


def normalize_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Reduce Tavily's raw search envelope to the trimmed shape we persist
    + ship over SSE. Drops fields the LLM doesn't use (favicon, raw_content
    when too big, etc.). Order preserved — Tavily already ranks by score."""
    out: list[dict[str, Any]] = []
    for r in payload.get("results") or []:
        if not isinstance(r, dict):
            continue
        url = r.get("url")
        if not isinstance(url, str) or not url:
            continue
        out.append(
            {
                "title": (r.get("title") or "").strip()[:200],
                "url": url,
                "snippet": (r.get("content") or "").strip()[:600],
                "score": r.get("score"),
                "published_date": r.get("published_date"),
            }
        )
    return out
