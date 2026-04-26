from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    analytics,
    assets,
    audience,
    brand,
    campaigns,
    chat,
    competitors,
    events_stream,
    finetune,
    geo,
    health,
    images,
    integrations,
    kanban,
    onboarding,
    onboarding_assets,
    peec,
    pipelines,
    research,
    video,
)
from app.config import settings
from app.db import models  # noqa: F401  -- registers models on Base
from app.db.session import Base, engine, _apply_migrations
from app.services import audience as _audience_listeners  # noqa: F401  -- registers shop-event listener
from app.services.agent import loop as agent_loop  # noqa: F401  -- registers chat.submitted listener
from app.services.agent.checkpoints import start_listener as start_run_checkpoints
from app.services.assets import start_listener as start_assets_listener
from app.services.peec.auto_seed import register_listener as register_peec_auto_seed
from app.services.enrichment import browser as pw_browser
from app.services.finetune import orchestrator as finetune_orchestrator
from app.services.pipeline import triggers as pipeline_triggers


@asynccontextmanager
async def lifespan(_: FastAPI):
    _apply_migrations()
    Base.metadata.create_all(bind=engine)
    start_assets_listener()
    start_run_checkpoints()
    register_peec_auto_seed()
    # Voice fine-tune jobs run as in-process asyncio tasks. Any task in
    # flight when the previous process died is gone — clear its DB
    # status so the UI doesn't show a forever-running job. Critical
    # under uvicorn --reload.
    finetune_orchestrator.recover_orphaned_jobs()
    await pw_browser.start()
    pipeline_triggers.register_listeners()
    pipeline_triggers.start_scheduler()
    try:
        yield
    finally:
        pipeline_triggers.stop_scheduler()
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
app.include_router(finetune.router, prefix="/api")
app.include_router(finetune.webhook_router, prefix="/api")
app.include_router(campaigns.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(pipelines.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(research.router, prefix="/api")
app.include_router(competitors.router, prefix="/api")
app.include_router(brand.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(geo.router, prefix="/api")
