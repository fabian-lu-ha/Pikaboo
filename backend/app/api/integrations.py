"""Integrations API — Instagram for now.

Routes under /api/integrations/instagram:
  GET    /status     → connection summary (no token)
  POST   /connect    → take a long-lived user token, discover IG account, store
  DELETE /disconnect → wipe the connection
  GET    /insights   → account + media insights pulled live from Graph API

Tokens live on Brand.social_connections["instagram"] — never returned by any
of these endpoints. In a production deployment you'd wrap this column with
column-level encryption (Fernet, KMS, etc); for now it's plain JSON.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.db.session import get_db
from app.services.social.instagram_graph import (
    InstagramGraphError,
    account_basic,
    account_insights,
    discover_ig_business_account,
    recent_media,
)

router = APIRouter(prefix="/integrations")
log = logging.getLogger(__name__)


# ----------------------------------------------------------------- helpers


def _get_brand(db: Session, brand_id: str) -> models.Brand:
    brand = (
        db.query(models.Brand).filter(models.Brand.id == brand_id).first()
    )
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    return brand


def _ig_conn(brand: models.Brand) -> dict[str, Any] | None:
    """Pull the instagram entry out of social_connections, or None."""
    sc = brand.social_connections or {}
    entry = sc.get("instagram")
    return entry if isinstance(entry, dict) else None


def _public_status(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Token-free representation safe to return through the API."""
    if not entry or not entry.get("ig_user_id"):
        return {"connected": False}
    return {
        "connected": True,
        "ig_user_id": entry.get("ig_user_id"),
        "username": entry.get("username"),
        "display_name": entry.get("display_name"),
        "profile_picture_url": entry.get("profile_picture_url"),
        "page_id": entry.get("page_id"),
        "connected_at": entry.get("connected_at"),
    }


def _ig_handle_value(entry: dict[str, Any]) -> str | None:
    name = entry.get("username") or entry.get("display_name")
    return f"@{name}" if name else None


# ------------------------------------------------------------------ schemas


class ConnectIn(BaseModel):
    brand_id: str
    access_token: str


class StatusOut(BaseModel):
    connected: bool
    ig_user_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    profile_picture_url: str | None = None
    page_id: str | None = None
    connected_at: str | None = None


# ----------------------------------------------------------------- endpoints


@router.get("/instagram/status", response_model=StatusOut)
def status(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> StatusOut:
    brand = _get_brand(db, brand_id)
    return StatusOut(**_public_status(_ig_conn(brand)))


@router.post("/instagram/connect", response_model=StatusOut)
def connect(
    body: ConnectIn, db: Annotated[Session, Depends(get_db)]
) -> StatusOut:
    brand = _get_brand(db, body.brand_id)
    token = (body.access_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="access_token is required")

    try:
        discovered = discover_ig_business_account(token)
    except InstagramGraphError as e:
        # 401/190 → token problem. 404 → no IG business account linked.
        # Anything else surfaces as a 502 since it's an upstream issue we
        # can't fix from here.
        status_code = 401 if e.code == 190 else (e.status if e.status in (400, 404) else 502)
        raise HTTPException(status_code=status_code, detail=str(e))

    page_token = discovered.get("page_access_token") or token

    entry = {
        "ig_user_id": discovered["ig_user_id"],
        "username": discovered.get("username"),
        "display_name": discovered.get("name"),
        "profile_picture_url": discovered.get("profile_picture_url"),
        "page_id": discovered.get("page_id"),
        "access_token": page_token,
        "user_access_token": token,
        "token_kind": "long_lived_user→page",
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    sc = dict(brand.social_connections or {})
    sc["instagram"] = entry
    brand.social_connections = sc
    flag_modified(brand, "social_connections")

    # Mirror the username into Brand.handles so the rest of the app (Settings
    # social profiles card, suggestion builder, etc) sees it without needing
    # to know about social_connections.
    handles = dict(brand.handles or {})
    handle_value = _ig_handle_value(entry)
    if handle_value and handles.get("instagram") != handle_value:
        handles["instagram"] = handle_value
        brand.handles = handles
        flag_modified(brand, "handles")

    db.add(brand)
    db.commit()
    db.refresh(brand)

    return StatusOut(**_public_status(_ig_conn(brand)))


@router.delete("/instagram/disconnect", response_model=StatusOut)
def disconnect(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> StatusOut:
    brand = _get_brand(db, brand_id)
    sc = dict(brand.social_connections or {})
    if "instagram" in sc:
        del sc["instagram"]
        brand.social_connections = sc
        flag_modified(brand, "social_connections")
        db.add(brand)
        db.commit()
        db.refresh(brand)
    return StatusOut(connected=False)


@router.get("/instagram/insights")
def insights(
    brand_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict[str, Any]:
    brand = _get_brand(db, brand_id)
    entry = _ig_conn(brand)
    if not entry or not entry.get("ig_user_id") or not entry.get("access_token"):
        raise HTTPException(
            status_code=409,
            detail="Instagram is not connected for this brand.",
        )

    ig_user_id = entry["ig_user_id"]
    token = entry["access_token"]

    try:
        account = account_basic(ig_user_id, token)
        series = account_insights(ig_user_id, token)
        media = recent_media(ig_user_id, token, limit=12)
    except InstagramGraphError as e:
        # Token expired (190) → tell the client to reconnect cleanly.
        if e.code == 190 or e.status == 401:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Instagram token expired or no longer valid — "
                    "reconnect from Settings → Integrations."
                ),
            )
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "account": {
            "id": account.get("id"),
            "username": account.get("username"),
            "name": account.get("name"),
            "biography": account.get("biography"),
            "profile_picture_url": account.get("profile_picture_url"),
            "followers_count": account.get("followers_count"),
            "follows_count": account.get("follows_count"),
            "media_count": account.get("media_count"),
            "website": account.get("website"),
        },
        "series": series,
        "recent_media": media,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
