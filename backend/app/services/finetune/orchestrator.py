"""Per-tenant Pioneer fine-tune lifecycle.

Single entry point: ``start_finetune(brand_id)``. It spawns a
**detached subprocess** (``app.scripts.run_finetune``) that walks
corpus → upload → train → deploy. Detaching matters because uvicorn
``--reload`` fires constantly when peer agents save Python files — an
asyncio task in the request loop would die mid-training. The
subprocess's own process group (``start_new_session=True``) survives
the reload, and writes its progress straight to ``Brand.voice_model_*``
+ ``Brand.voice_corpus_meta.current_stage`` so the frontend can poll
``/api/finetune/status`` to render the live state.

Re-entry guard: we look at the brand's persisted status. If it's in a
transient state we assume a worker is alive and refuse to start a
duplicate. Recovery on app startup clears any rows that look stuck
(``recover_orphaned_jobs``).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.db import models
from app.db.session import SessionLocal
from app.events.bus import bus
from app.events.types import Events
from app.services.finetune import pioneer_client

log = logging.getLogger(__name__)

# Statuses that imply an in-flight worker subprocess. On startup we clear
# these — any task in flight died with the previous process, so the DB
# is lying. Without this, uvicorn --reload (which fires constantly when
# peer agents edit code) leaves brands stuck on "corpus_building" and
# the UI just sits there waiting for events that will never come.
_TRANSIENT_STATUSES = (
    "deep_scraping",
    "corpus_building",
    "corpus_built",
    "training_queued",
    "training",
)


def recover_orphaned_jobs() -> int:
    """Clear any brand stuck in a transient status with no live worker.

    Workers run as detached subprocesses (start_new_session=True), so
    they survive uvicorn reloads. This recovery only marks the row
    failed if there's no ``app.scripts.run_finetune <brand_id>``
    subprocess actually running on the machine — without that check we
    used to wipe live training jobs when the backend restarted, leaving
    the worker writing fields nobody read.
    """
    import subprocess
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,command"], capture_output=True, text=True, timeout=5
        )
        live_lines = [
            ln for ln in ps.stdout.splitlines()
            if "run_finetune" in ln and "grep" not in ln
        ]
        live_brand_ids = set()
        for ln in live_lines:
            for tok in ln.split():
                # brand_id is a UUID; treat any 36-char dash-separated
                # token as one. Cheap + correct enough.
                if len(tok) == 36 and tok.count("-") == 4:
                    live_brand_ids.add(tok)
    except Exception as e:
        log.warning("recover: ps probe failed (%s) — will mark all stale", e)
        live_brand_ids = set()

    with SessionLocal() as db:
        rows = (
            db.query(models.Brand)
            .filter(models.Brand.voice_model_status.in_(_TRANSIENT_STATUSES))
            .all()
        )
        cleared = 0
        skipped = 0
        for row in rows:
            if row.id in live_brand_ids:
                log.info(
                    "voice fine-tune: brand=%s status=%s has live worker — skipping recovery",
                    row.id, row.voice_model_status,
                )
                skipped += 1
                continue
            log.warning(
                "voice fine-tune: clearing orphaned status=%s on brand=%s",
                row.voice_model_status, row.id,
            )
            row.voice_model_status = "failed"
            cleared += 1
        if cleared:
            db.commit()
        if skipped:
            log.info("recover: skipped %d brand(s) with live workers", skipped)
        return cleared


def _set_status(brand_id: str, status: str, **extra: Any) -> None:
    """Persist status + arbitrary updates on the Brand row."""
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return
        row.voice_model_status = status
        for k, v in extra.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()


def _get_brand_snapshot(brand_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "name": row.name or "the brand",
            "voice_model_id": row.voice_model_id,
            "voice_model_status": row.voice_model_status or "idle",
            "voice_adapter_url": row.voice_adapter_url,
            "voice_corpus_meta": dict(row.voice_corpus_meta or {}),
        }


def _backend_root() -> Path:
    """Absolute path to the backend dir (cwd of the subprocess).

    ``app/services/finetune/orchestrator.py`` → ``backend/``.
    """
    return Path(__file__).resolve().parents[3]


def start_finetune(brand_id: str) -> dict[str, Any]:
    """Public entry — spawns a detached subprocess that survives uvicorn
    reloads. Returns current status payload."""
    snap = _get_brand_snapshot(brand_id)
    if snap is None:
        return {"ok": False, "error": "brand not found"}

    if snap["voice_model_status"] in _TRANSIENT_STATUSES:
        # Re-entry guard. Recovery on next backend restart clears any
        # truly orphaned row.
        return {
            "ok": True,
            "already_running": True,
            "status": snap["voice_model_status"],
        }

    backend_root = _backend_root()
    log_path = backend_root / f"finetune-{brand_id[:8]}.log"
    cmd = [sys.executable, "-m", "app.scripts.run_finetune", brand_id]
    env = os.environ.copy()
    # Make sure the subprocess can find ``app.*`` even if the parent was
    # launched with a different cwd.
    env["PYTHONPATH"] = str(backend_root) + os.pathsep + env.get("PYTHONPATH", "")

    try:
        with log_path.open("a", encoding="utf-8") as logfile:
            proc = subprocess.Popen(
                cmd,
                cwd=str(backend_root),
                env=env,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                # The critical bit: a fresh process group means the
                # child won't be killed when uvicorn's worker process
                # exits during --reload.
                start_new_session=True,
                close_fds=True,
            )
    except Exception as e:
        log.exception("failed to spawn finetune worker")
        _set_status(brand_id, "failed")
        bus.emit(
            Events.VOICE_TRAINING_FAILED,
            {"brand_id": brand_id, "error": f"spawn: {e}"},
        )
        return {"ok": False, "error": str(e)}

    log.info(
        "spawned finetune worker pid=%s brand=%s log=%s",
        proc.pid, brand_id, log_path,
    )
    # Mark the brand immediately so the next status poll reflects the
    # transition without waiting for the subprocess to write.
    _set_status(brand_id, "deep_scraping")
    return {
        "ok": True,
        "already_running": False,
        "pid": proc.pid,
        "status": "deep_scraping",
        "log_path": str(log_path),
    }


def get_status(brand_id: str) -> dict[str, Any]:
    snap = _get_brand_snapshot(brand_id)
    if snap is None:
        return {"ok": False, "error": "brand not found"}
    in_progress = snap["voice_model_status"] in _TRANSIENT_STATUSES
    try:
        simulator = pioneer_client.get_client().is_simulator
    except RuntimeError:
        simulator = None
    return {
        "ok": True,
        "in_progress": in_progress,
        "status": snap["voice_model_status"],
        "voice_model_id": snap["voice_model_id"],
        "voice_adapter_url": snap["voice_adapter_url"],
        "corpus_meta": snap["voice_corpus_meta"],
        "simulator": simulator,
    }
