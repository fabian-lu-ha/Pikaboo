"""Instagram Graph API client.

Authenticated, official-API path for Settings → Integrations → Instagram.
Distinct from `instagram.py` in this same package, which is a public-profile
scraper used during onboarding. This module talks to the Meta Graph API
on behalf of a connected user/page and only deals with their own data.

The pragmatic connect flow we expose:
  * User pastes a long-lived **User Access Token** from Meta Business Suite
    (https://business.facebook.com/settings/system-users — token must include
    `pages_show_list`, `instagram_basic`, `instagram_manage_insights`).
  * `discover_ig_business_account` walks /me/accounts → finds the first Page
    that has a linked `instagram_business_account` and returns its
    page-scoped access token + IG user id + username.
  * Insights and media calls then use the page-scoped token (which has the
    same lifetime as the long-lived user token, ~60 days, and is the right
    token to use against IG Business endpoints).

We never raise to the API surface — failures bubble up as InstagramGraphError
with a clean human-readable message; the API layer maps them to 400/401/502.

Reference: https://developers.facebook.com/docs/instagram-platform/api-reference
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v19.0"
DEFAULT_TIMEOUT = 15.0


class InstagramGraphError(Exception):
    """Raised on any non-recoverable Graph API failure.

    `status` is the HTTP status (or 0 when the call never landed).
    `code` is the Meta error subcode when present (e.g. 190 = OAuth).
    """

    def __init__(
        self, message: str, *, status: int = 0, code: int | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _raise_from_response(resp: httpx.Response) -> None:
    """Convert a non-2xx Graph response into a clean InstagramGraphError."""
    status = resp.status_code
    try:
        data = resp.json()
    except Exception:
        data = {}
    err = (data or {}).get("error") or {}
    msg = err.get("message") or f"Graph API error {status}"
    code = err.get("code")
    raise InstagramGraphError(msg, status=status, code=code)


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    try:
        resp = httpx.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as e:
        raise InstagramGraphError(f"Graph API unreachable: {e}") from e
    if resp.status_code >= 400:
        _raise_from_response(resp)
    return resp.json() or {}


# ----------------------------------------------------------------- discovery


def discover_ig_business_account(user_access_token: str) -> dict[str, Any]:
    """Walk the user's Pages, return the first IG Business Account found.

    Returns dict with: ig_user_id, username, name, profile_picture_url,
    page_id, page_access_token. Raises InstagramGraphError if none found.
    """
    data = _get(
        "me/accounts",
        params={
            "fields": (
                "id,name,access_token,"
                "instagram_business_account{id,username,name,profile_picture_url}"
            ),
            "access_token": user_access_token,
        },
    )
    pages = data.get("data") or []
    for page in pages:
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            return {
                "ig_user_id": ig["id"],
                "username": ig.get("username"),
                "name": ig.get("name"),
                "profile_picture_url": ig.get("profile_picture_url"),
                "page_id": page.get("id"),
                "page_access_token": page.get("access_token"),
            }
    raise InstagramGraphError(
        "No Instagram Business account is linked to any of the Facebook "
        "Pages this token can access. Make sure your IG account is set "
        "to Business or Creator and linked to a Page.",
        status=404,
    )


# -------------------------------------------------------------- account info


def account_basic(ig_user_id: str, access_token: str) -> dict[str, Any]:
    """Profile-level metadata: followers, follows, media count, picture."""
    return _get(
        ig_user_id,
        params={
            "fields": (
                "id,username,name,biography,profile_picture_url,"
                "followers_count,follows_count,media_count,website"
            ),
            "access_token": access_token,
        },
    )


# ----------------------------------------------------------------- insights


# Account-level metrics broken into groups by required `metric_type`.
# Graph API v18+ split insights into "total_value" vs "time_series" — and
# kept rotating the metric names every few releases. We attempt each group
# independently and ignore individual-group failures so a single deprecated
# metric does not blank the whole panel.
_TIME_SERIES_METRICS = ("reach", "profile_views")


def account_time_series(
    ig_user_id: str,
    access_token: str,
    *,
    metric: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Daily series for a single account-level metric over the last N days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=max(1, days))
    try:
        data = _get(
            f"{ig_user_id}/insights",
            params={
                "metric": metric,
                "period": "day",
                "since": int(since.timestamp()),
                "until": int(until.timestamp()),
                "metric_type": "time_series",
                "access_token": access_token,
            },
        )
    except InstagramGraphError as e:
        log.info("ig insights %s skipped: %s", metric, e)
        return []
    rows = (data.get("data") or [{}])[0].get("values") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        end = r.get("end_time")
        v = r.get("value")
        if end is None or v is None:
            continue
        out.append({"date": end, "value": v})
    return out


def account_insights(ig_user_id: str, access_token: str) -> dict[str, list]:
    """Bundle of supported account-level time-series metrics for the past 7 days."""
    out: dict[str, list] = {}
    for metric in _TIME_SERIES_METRICS:
        series = account_time_series(
            ig_user_id, access_token, metric=metric, days=7
        )
        if series:
            out[metric] = series
    return out


# -------------------------------------------------------------------- media


def recent_media(
    ig_user_id: str, access_token: str, *, limit: int = 12
) -> list[dict[str, Any]]:
    """Last N media items with their built-in counters (no extra insights call)."""
    data = _get(
        f"{ig_user_id}/media",
        params={
            "fields": (
                "id,caption,media_type,media_url,permalink,thumbnail_url,"
                "timestamp,like_count,comments_count"
            ),
            "limit": max(1, min(50, limit)),
            "access_token": access_token,
        },
    )
    items = data.get("data") or []
    return items
