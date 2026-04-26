"""Onboarding endpoints for product/asset uploads + reference brand orchestration.

Mounted alongside `app.api.onboarding`. Kept in its own module so the lead's
`onboarding.py` is untouched. Only validates at the input boundary.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import SessionLocal, get_db
from app.events.bus import bus
from app.events.types import Events
from app.providers.factory import get_storage
from app.services.onboarding import orchestrator
from app.services.pipeline import enrich_visual

log = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding")

# ---------------------------------------------------------------------------
# /onboarding/assets — multipart product/asset image upload
# ---------------------------------------------------------------------------

MAX_FILES_PER_UPLOAD = 8
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# Map content-type to a sensible extension. mimetypes covers most, but we
# guarantee a few common ones the brand-asset flow expects.
_EXT_OVERRIDES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/avif": "avif",
    "image/heic": "heic",
}


def _ext_for(content_type: str, filename: str | None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_OVERRIDES:
        return _EXT_OVERRIDES[ct]
    guess = mimetypes.guess_extension(ct) if ct else None
    if guess:
        return guess.lstrip(".")
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()[:8]
    return "bin"


@router.post("/assets")
async def post_assets(
    brand_id: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
) -> dict:
    """Upload product/brand asset images for a brand.

    Validates content-type (image/*), per-file size (<= 10 MB), and total
    file count (<= 8) at the boundary. Stores each via the configured
    storage provider, emits one ONBOARDING_ASSET_UPLOADED event per file,
    and returns the resulting URLs in the order received.
    """
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"too many files (max {MAX_FILES_PER_UPLOAD})",
        )
    if not (brand_id or "").strip():
        raise HTTPException(status_code=400, detail="brand_id required")

    storage = get_storage()
    asset_urls: list[str] = []
    asset_names: list[str] = []

    for f in files:
        ctype = (f.content_type or "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail=f"{f.filename or 'file'}: content-type must be image/*",
            )

        # Starlette's UploadFile is backed by a SpooledTemporaryFile — for
        # ~10 MB images it's fine to read once; the provider's `put` takes
        # `bytes` and we'd buffer it anyway.
        data = await f.read()
        if len(data) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"{f.filename or 'file'}: empty file",
            )
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{f.filename or 'file'}: exceeds "
                    f"{MAX_FILE_BYTES // (1024 * 1024)} MB limit"
                ),
            )

        ext = _ext_for(ctype, f.filename)
        key = f"brands/{brand_id}/assets/{uuid4()}.{ext}"
        try:
            await storage.put(key, data, ctype)
            url = await storage.get_url(key)
        except Exception as e:
            log.warning(
                "asset upload failed for brand=%s name=%s: %s",
                brand_id,
                f.filename,
                e,
            )
            raise HTTPException(
                status_code=502, detail=f"storage put failed: {e}"
            ) from e

        asset_urls.append(url)
        asset_names.append(f.filename or "")
        bus.emit(
            Events.ONBOARDING_ASSET_UPLOADED,
            {
                "brand_id": brand_id,
                "asset_url": url,
                "name": f.filename or "",
            },
        )

    # Persist to Brand.assets so post-onboarding agent runs can read them.
    # The image_gen pipeline pulls from this column on every generation.
    try:
        with SessionLocal() as db:
            brand = db.get(models.Brand, brand_id)
            if brand is not None:
                merged = list(brand.assets or []) + asset_urls
                brand.assets = merged
                db.add(brand)
                db.commit()
    except Exception as e:
        log.warning("asset persist to Brand.assets failed brand=%s: %s", brand_id, e)

    return {"asset_urls": asset_urls}


# ---------------------------------------------------------------------------
# /onboarding/references — kick off background scrape of a reference brand
# ---------------------------------------------------------------------------


class ReferenceIn(BaseModel):
    brand_id: str
    url: str


def _is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _voice_excerpt(body_markdown: str | None, max_chars: int = 600) -> str:
    if not body_markdown:
        return ""
    text = " ".join(body_markdown.split())
    return text[:max_chars]


def _append_reference_brand(brand: models.Brand, ref: dict) -> None:
    """Append to the canonical reference_brands JSON column."""
    current = list(brand.reference_brands or [])
    current.append(ref)
    brand.reference_brands = current


async def _run_reference_scrape(brand_id: str, url: str) -> None:
    try:
        ref_id = str(uuid4())
        visual = await enrich_visual(
            url, f"brands/{brand_id}/references/{ref_id}"
        )

        if visual.parked:
            bus.emit(
                Events.ONBOARDING_REFERENCE_FAILED,
                {
                    "brand_id": brand_id,
                    "url": url,
                    "error": "site is a parked domain",
                },
            )
            return

        name = (visual.title or "").split(" | ")[0].split(" — ")[0].strip()
        if not name:
            name = urlparse(visual.final_url).netloc or url

        reference = {
            "id": ref_id,
            "url": visual.final_url,
            "name": name[:120],
            "logo_url": visual.logo_url,
            "screenshot_urls": visual.screenshots,
            "palette": visual.palette,
            "palette_roles": visual.palette_roles,
            "theme_color": visual.theme_color,
            "voice_excerpt": _voice_excerpt(visual.body_markdown),
        }

        with SessionLocal() as db:
            brand = db.get(models.Brand, brand_id)
            if brand is None:
                log.warning(
                    "reference scrape: brand %s not found at persist time",
                    brand_id,
                )
                bus.emit(
                    Events.ONBOARDING_REFERENCE_FAILED,
                    {
                        "brand_id": brand_id,
                        "url": url,
                        "error": "brand not found",
                    },
                )
                return
            _append_reference_brand(brand, reference)
            db.add(brand)
            db.commit()

        bus.emit(
            Events.ONBOARDING_REFERENCE_ADDED,
            {"brand_id": brand_id, "reference": reference},
        )
    except Exception as e:
        log.warning(
            "reference scrape failed for brand=%s url=%s: %s", brand_id, url, e
        )
        bus.emit(
            Events.ONBOARDING_REFERENCE_FAILED,
            {"brand_id": brand_id, "url": url, "error": str(e)},
        )


@router.post("/references")
async def post_reference(body: ReferenceIn) -> dict:
    if not _is_http_url(body.url):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    if not (body.brand_id or "").strip():
        raise HTTPException(status_code=400, detail="brand_id required")

    asyncio.create_task(_run_reference_scrape(body.brand_id, body.url))
    return {"ok": True}


# ---------------------------------------------------------------------------
# /competitors/add — single-row add + lite enrichment
# ---------------------------------------------------------------------------

# Reach into the orchestrator's underscore export. Acceptable per spec — we
# don't modify orchestrator.py.
_enrich_competitor_lite = orchestrator.enrich_competitor


class CompetitorAddIn(BaseModel):
    brand_id: str
    name: str
    url: str | None = None


# Note: this endpoint is mounted under /onboarding/competitors/add because
# `router` has prefix=/onboarding. The lead's onboarding.py also has a
# /onboarding/competitors POST — different path (this one is /add).
@router.post("/competitors/add")
async def post_competitor_add(
    body: CompetitorAddIn, db: Annotated[Session, Depends(get_db)]
) -> dict:
    if not (body.brand_id or "").strip():
        raise HTTPException(status_code=400, detail="brand_id required")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    url = (body.url or "").strip() or None
    if url is not None and not _is_http_url(url):
        raise HTTPException(status_code=400, detail="url must be http(s)")

    row = models.Competitor(
        brand_id=body.brand_id,
        name=name,
        url=url,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    comp_id = row.id
    brand_id = body.brand_id

    async def _enrich_and_emit() -> None:
        if not url:
            return
        try:
            logo = await _enrich_competitor_lite(brand_id, comp_id, url)
        except Exception as e:
            log.warning(
                "competitor enrich failed brand=%s comp=%s: %s",
                brand_id,
                comp_id,
                e,
            )
            return
        try:
            with SessionLocal() as cdb:
                comp = cdb.get(models.Competitor, comp_id)
                if comp is None:
                    return
                comp.logo_url = logo
                cdb.add(comp)
                cdb.commit()
        except Exception as e:
            log.warning(
                "competitor logo persist failed brand=%s comp=%s: %s",
                brand_id,
                comp_id,
                e,
            )
            return
        bus.emit(
            Events.ONBOARDING_COMPETITOR_ENRICHED,
            {
                "brand_id": brand_id,
                "competitor_id": comp_id,
                "logo_url": logo,
            },
        )

    asyncio.create_task(_enrich_and_emit())

    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "logo_url": None,
    }
