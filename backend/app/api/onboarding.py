import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.events.bus import bus
from app.events.types import Events
from app.services.onboarding import orchestrator

router = APIRouter(prefix="/onboarding")


class BasicsIn(BaseModel):
    name: str | None = None
    description: str | None = None
    url: HttpUrl


class BasicsOut(BaseModel):
    brand_id: str


@router.post("/basics", response_model=BasicsOut)
def post_basics(
    body: BasicsIn, db: Annotated[Session, Depends(get_db)]
) -> BasicsOut:
    brand = models.Brand(
        name=(body.name or "").strip() or "(unnamed)",
        url=str(body.url),
        description=(body.description or "").strip() or None,
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)
    bus.emit(
        Events.ONBOARDING_BASICS_SAVED,
        {"brand_id": brand.id, "url": brand.url},
    )
    return BasicsOut(brand_id=brand.id)


class ScrapeIn(BaseModel):
    brand_id: str


@router.post("/scrape")
async def post_scrape(
    body: ScrapeIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    from app.services.utils.security import is_safe_http_url

    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    if not brand.url or not is_safe_http_url(brand.url):
        raise HTTPException(status_code=400, detail="brand url is not safe")
    asyncio.create_task(orchestrator.run(body.brand_id))
    return {"ok": True}


class PostsIn(BaseModel):
    brand_id: str
    posts_text: str


@router.post("/posts")
def post_pasted_posts(
    body: PostsIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    brand.pasted_posts = body.posts_text.strip() or None
    db.add(brand)
    db.commit()
    return {"ok": True}


class CompetitorEdit(BaseModel):
    id: str | None = None
    name: str
    url: str | None = None
    reason: str | None = None


class CompetitorsIn(BaseModel):
    brand_id: str
    competitors: list[CompetitorEdit]


@router.post("/competitors")
def post_competitors(
    body: CompetitorsIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    db.query(models.Competitor).filter(
        models.Competitor.brand_id == body.brand_id
    ).delete()
    for c in body.competitors:
        db.add(
            models.Competitor(
                brand_id=body.brand_id,
                name=c.name,
                url=c.url,
                reason=c.reason,
            )
        )
    db.commit()
    return {"ok": True}


class HandlesIn(BaseModel):
    brand_id: str
    handles: dict[str, str]


@router.post("/handles")
def post_handles(
    body: HandlesIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    brand.handles = {**(brand.handles or {}), **body.handles}
    db.add(brand)
    db.commit()
    return {"ok": True}


class CompleteIn(BaseModel):
    brand_id: str


@router.post("/complete")
def post_complete(
    body: CompleteIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    brand.onboarded_at = datetime.now(timezone.utc)
    db.add(brand)
    db.commit()
    bus.emit(Events.ONBOARDING_COMPLETED, {"brand_id": body.brand_id})
    return {"ok": True}


@router.delete("/me")
def delete_me(db: Annotated[Session, Depends(get_db)]) -> dict:
    """Reset onboarding — deletes the most-recently-onboarded brand and its
    storage directory so the wizard reappears. Dev/demo affordance."""
    from pathlib import Path
    import shutil

    from app.config import settings as _settings

    brand = (
        db.query(models.Brand)
        .filter(models.Brand.onboarded_at.is_not(None))
        .order_by(models.Brand.onboarded_at.desc())
        .first()
    )
    if brand is None:
        return {"ok": True, "deleted": None}
    brand_id = brand.id
    db.delete(brand)
    db.commit()

    if _settings.deploy_mode == "local":
        path = Path(_settings.storage_dir) / "brands" / brand_id
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    return {"ok": True, "deleted": brand_id}


@router.get("/me")
def get_me(db: Annotated[Session, Depends(get_db)]) -> dict:
    brand = (
        db.query(models.Brand)
        .filter(models.Brand.onboarded_at.is_not(None))
        .order_by(models.Brand.onboarded_at.desc())
        .first()
    )
    if brand is None:
        return {"brand": None}
    return {
        "brand": {
            "id": brand.id,
            "name": brand.name,
            "url": brand.url,
            "description": brand.description,
            "logo_url": brand.logo_url,
            "screenshots": brand.screenshots,
            "theme_color": brand.theme_color,
            "palette": brand.palette,
            "palette_roles": brand.palette_roles,
            "identity": brand.identity,
            "voice_profile": brand.voice_profile,
            "handles": brand.handles,
            "competitors": [
                {
                    "id": c.id,
                    "name": c.name,
                    "url": c.url,
                    "reason": c.reason,
                    "logo_url": c.logo_url,
                }
                for c in brand.competitors
            ],
        }
    }
