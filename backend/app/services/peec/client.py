"""Peec REST client — thin async wrapper around api.peec.ai/customer/v1.

Defensive: every method returns plain dicts/lists so the caller stays decoupled
from Peec's exact response shape (which is in beta per their docs). On 401 / 4xx
/ 5xx we raise PeecError with the status + body excerpt so the orchestrator can
log + fall back to mock data without crashing the demo.
"""

import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class PeecError(Exception):
    pass


class PeecClient:
    def __init__(self) -> None:
        self._key = settings.peec_api_key
        self._base = settings.peec_base_url.rstrip("/")
        if not self._key:
            raise PeecError("PEEC_API_KEY not set")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._key or "",
            "accept": "application/json",
            "user-agent": "brand-autopilot/0.1 (hackathon)",
        }

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self._base}/customer/v1{path}"
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.get(url, headers=self._headers, params=params or {})
        if resp.status_code != 200:
            raise PeecError(
                f"GET {path} {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as e:
            raise PeecError(f"GET {path}: bad JSON ({e})") from e

    async def _post(
        self, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self._base}/customer/v1{path}"
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                url, headers=self._headers, json=body or {}
            )
        if resp.status_code != 200:
            raise PeecError(
                f"POST {path} {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as e:
            raise PeecError(f"POST {path}: bad JSON ({e})") from e

    @staticmethod
    def _as_list(payload: Any) -> list[dict]:
        """Peec endpoints sometimes wrap results in {data: [...]} / {prompts: [...]} /
        {brands: [...]}. Pull whichever shape they ship."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "items", "prompts", "brands", "results"):
                v = payload.get(key)
                if isinstance(v, list):
                    return v
        return []

    async def list_brands(
        self, project_id: str | None = None
    ) -> list[dict]:
        params = {"project_id": project_id} if project_id else None
        return self._as_list(await self._get("/brands", params))

    async def list_prompts(
        self,
        project_id: str | None = None,
        topic_id: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        if topic_id:
            params["topic_id"] = topic_id
        return self._as_list(await self._get("/prompts", params or None))

    async def get_brands_report(
        self,
        project_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        dimensions: list[str] | None = None,
        filters: dict | None = None,
        limit: int = 1000,
    ) -> dict:
        body = _build_report_body(
            project_id=project_id,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            filters=filters,
            limit=limit,
        )
        return await self._post("/reports/brands", body)

    async def get_domains_report(self, **kwargs: Any) -> dict:
        return await self._post(
            "/reports/domains", _build_report_body(**kwargs)
        )

    async def get_urls_report(self, **kwargs: Any) -> dict:
        return await self._post(
            "/reports/urls", _build_report_body(**kwargs)
        )


def _clean_params(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, list):
            out[k] = ",".join(str(x) for x in v)
        else:
            out[k] = v
    return out


def _build_report_body(
    project_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    filters: dict | list | None = None,
    limit: int = 1000,
    offset: int = 0,
    order_by: list | None = None,
) -> dict[str, Any]:
    """Assemble a /reports/* POST body the way the live Peec API expects it.

    Defaults to a 90-day window ending today — without dates Peec would
    use 2026-01-01 → 2026-01-01 (a single day) and almost always return
    zero rows. project_id is optional when the API key is project-scoped
    (skp-... keys); it's only required for company-scoped keys.
    """
    from datetime import date, timedelta

    today = date.today()
    body: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "start_date": start_date or (today - timedelta(days=90)).isoformat(),
        "end_date": end_date or today.isoformat(),
    }
    if project_id:
        body["project_id"] = project_id
    if dimensions:
        body["dimensions"] = list(dimensions)
    if filters:
        body["filters"] = filters if isinstance(filters, list) else [
            {"field": k, "operator": "eq", "values": v if isinstance(v, list) else [v]}
            for k, v in filters.items()
        ]
    if order_by:
        body["order_by"] = order_by
    return body


_client: PeecClient | None = None


def get_peec() -> PeecClient | None:
    """Returns None if no API key is configured — caller MUST degrade gracefully."""
    global _client
    if _client is not None:
        return _client
    if not settings.peec_api_key:
        return None
    try:
        _client = PeecClient()
    except PeecError as e:
        log.warning("peec client init failed: %s", e)
        return None
    return _client
