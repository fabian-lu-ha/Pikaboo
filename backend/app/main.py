from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    audience,
    chat,
    events_stream,
    health,
    images,
    kanban,
    onboarding,
    onboarding_assets,
    peec,
    video,
)
from app.config import settings
from app.db import models  # noqa: F401  -- registers models on Base
from app.db.session import Base, engine, _apply_migrations
from app.services import audience as _audience_listeners  # noqa: F401  -- registers shop-event listener
from app.services.agent import loop as agent_loop  # noqa: F401  -- registers chat.submitted listener
from app.services.enrichment import browser as pw_browser


@asynccontextmanager
async def lifespan(_: FastAPI):
    _apply_migrations()
    Base.metadata.create_all(bind=engine)
    await pw_browser.start()
    try:
        yield
    finally:
        await pw_browser.stop()


app = FastAPI(title="Brand Autopilot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.deploy_mode == "local":
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    app.mount(
        "/api/storage",
        StaticFiles(directory=settings.storage_dir),
        name="storage",
    )

app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(events_stream.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(onboarding_assets.router, prefix="/api")
app.include_router(video.router, prefix="/api")
app.include_router(images.router, prefix="/api")
app.include_router(kanban.router, prefix="/api")
app.include_router(peec.router, prefix="/api")
app.include_router(audience.router, prefix="/api")
