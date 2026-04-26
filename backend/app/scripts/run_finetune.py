"""CLI entry for the Pioneer fine-tune lifecycle.

Run as: ``python -m app.scripts.run_finetune <brand_id>``

Spawned as a detached subprocess by the orchestrator's
``start_finetune`` so uvicorn ``--reload`` can't kill the work
mid-flight.

Pioneer's real fine-tune API (mapped from
``https://agent.pioneer.ai/openapi.json``) follows the standard
{project, dataset, training-job, deployment} pattern. Pioneer's
trainable catalog is Llama 3.x + Qwen3 + Qwen2.5 — NO Gemma despite
the press release. We default to ``Qwen/Qwen3-4B-Instruct-2507`` (4B
params, 262K context, supports LoRA).

Lifecycle:

1. **Build corpus** — deep_scrape + Gemini reverse-brief + synth fill
   (corpus_builder writes JSONL + updates current_stage)
2. **Create project** — POST /projects (one per tenant brand)
3. **Get presigned upload URL** — POST /felix/datasets/upload/url
4. **Upload JSONL** — PUT to the presigned URL
5. **Process dataset** — POST /felix/datasets/upload/process
6. **Create training job** — POST /felix/training-jobs (LoRA)
7. **Poll job** — GET /felix/training-jobs/{job_id} every 10s
8. **Deploy** — POST /projects/{project_id}/deployments
9. **Mark adapter live** — voice_adapter_url = ``pioneer://<model_id>``

Inference at draft time goes through ``chat_via_adapter`` which calls
Pioneer's ``POST /v1/chat/completions`` (OpenAI-compatible).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

from app.db import models
from app.db.session import SessionLocal
from app.services.finetune import corpus_builder, pioneer_client


def _configure_logging(brand_id: str) -> None:
    log_path = f"finetune-{brand_id[:8]}.log"
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("[finetune-worker] %(message)s"))
    root.addHandler(stream)


log = logging.getLogger("finetune.worker")


_POLL_INTERVAL_SECONDS = 10.0
_POLL_TIMEOUT_SECONDS = 60 * 60 * 6  # Pioneer claims ~6h average


def _set_status(brand_id: str, status: str, **extra: Any) -> None:
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return
        row.voice_model_status = status
        for k, v in extra.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()


def _set_meta(brand_id: str, **patch: Any) -> None:
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is None:
            return
        meta = dict(row.voice_corpus_meta or {})
        meta.update(patch)
        row.voice_corpus_meta = meta
        db.add(row)
        db.commit()


def _read_brand_name(brand_id: str) -> str | None:
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        return None if row is None else (row.name or "the brand")


def _safe_dataset_name(brand_id: str) -> str:
    """Pioneer dataset names look like slugs — keep it short + ASCII."""
    return f"voice-{brand_id[:8]}"


def _safe_model_name(brand_id: str, brand_name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in brand_name)[:24]
    slug = slug.strip("-") or "tenant"
    return f"{slug}-voice-{brand_id[:6]}"


async def _drive(brand_id: str) -> None:
    log.info(
        "starting Pioneer fine-tune for brand=%s pid=%s",
        brand_id, os.getpid(),
    )

    brand_name = _read_brand_name(brand_id)
    if brand_name is None:
        log.error("brand %s not found", brand_id)
        return

    try:
        client = pioneer_client.get_client()
    except RuntimeError as e:
        log.error("pioneer client unavailable: %s", e)
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage=f"failed: {e}")
        return

    # Capture the previous run's Pioneer artifacts BEFORE we wipe state.
    # We delete them so the user sees a fresh project + training job
    # each time, not a layered set of versions on the same dataset.
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        old_meta = dict(row.voice_corpus_meta or {}) if row else {}
    old_project_id = old_meta.get("pioneer_project_id")
    old_training_job_id = old_meta.get("pioneer_training_job_id")
    old_dataset_name = _safe_dataset_name(brand_id)

    if old_project_id or old_training_job_id:
        log.info(
            "cleaning up previous run: project=%s job=%s dataset=%s",
            old_project_id, old_training_job_id, old_dataset_name,
        )
    if old_training_job_id:
        try:
            await client.delete_training_job(old_training_job_id)
        except Exception as e:
            log.warning("delete old training job failed: %s", e)
    if old_project_id:
        try:
            await client.delete_project(old_project_id)
        except Exception as e:
            log.warning("delete old project failed: %s", e)
    try:
        await client.delete_dataset(old_dataset_name)
    except Exception as e:
        log.warning("delete old dataset failed: %s", e)

    # Reset ALL transient state. Clearing voice_corpus_meta too so the
    # UI doesn't carry old "done" markers (deep_scrape stats, project
    # id, training job id) into the new run before the worker re-
    # populates them.
    with SessionLocal() as db:
        row = db.get(models.Brand, brand_id)
        if row is not None:
            row.voice_model_status = "deep_scraping"
            row.voice_model_id = None
            row.voice_adapter_url = None
            row.voice_corpus_meta = {"current_stage": "starting fresh run…"}
            db.add(row)
            db.commit()

    # Phase 1+2 — corpus build (deep_scrape, GLiNER2, reverse-brief,
    # synth fill). The corpus_builder updates current_stage internally.
    corpus = await corpus_builder.build_corpus(brand_id)
    if corpus is None:
        log.error("corpus build returned None")
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage="corpus build failed")
        return
    log.info("corpus ready: %d pairs at %s", corpus.line_count, corpus.jsonl_path)

    # Phase 3 — create the Pioneer project (one per tenant).
    _set_status(brand_id, "training_queued")
    _set_meta(brand_id, current_stage="creating Pioneer project…")
    try:
        project_id = await client.create_project(
            name=_safe_model_name(brand_id, brand_name),
            description=(
                f"Per-tenant brand-voice fine-tune for {brand_name}. "
                f"Trained on {corpus.line_count} (brief, post) pairs."
            ),
        )
        log.info("pioneer project_id=%s", project_id)
    except Exception as e:
        log.exception("create_project failed")
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage=f"create project failed: {e}")
        return

    # Phase 4 — request a presigned upload URL.
    dataset_name = _safe_dataset_name(brand_id)
    _set_meta(
        brand_id,
        current_stage="requesting Pioneer upload URL…",
        pioneer_project_id=project_id,
    )
    try:
        upload_info = await client.request_upload_url(
            dataset_name=dataset_name,
            dataset_type="decoder",
            fmt="jsonl",
        )
    except Exception as e:
        log.exception("request_upload_url failed")
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage=f"upload url failed: {e}")
        return

    presigned = (
        upload_info.get("upload_url")
        or upload_info.get("url")
        or upload_info.get("presigned_url")
    )
    dataset_id = (
        upload_info.get("dataset_id")
        or upload_info.get("id")
        or dataset_name
    )
    if not presigned:
        log.error("no presigned URL in %r", upload_info)
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage="no presigned URL returned")
        return
    log.info("got presigned url + dataset_id=%s", dataset_id)

    # Phase 5 — PUT the JSONL.
    _set_meta(brand_id, current_stage="uploading JSONL to S3 presigned URL…")
    try:
        await client.upload_to_presigned(
            presigned_url=presigned, jsonl_path=corpus.jsonl_path
        )
    except Exception as e:
        log.exception("upload_to_presigned failed")
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage=f"upload failed: {e}")
        return

    # Phase 6 — Pioneer processes the upload (validation, indexing).
    # /upload/process returns 202 Accepted (async) — we then poll
    # /felix/datasets/{name}/{version} until the dataset is queryable.
    # Without this, /felix/training-jobs 400s with "dataset artifacts
    # are missing in storage".
    _set_meta(brand_id, current_stage="processing dataset on Pioneer…")
    try:
        proc_result = await client.process_upload(dataset_id=dataset_id)
        # The version Pioneer assigned (v1 on first upload, v2 on
        # second, etc). The presigned upload URL also embedded this
        # number in the path, but the process response is canonical.
        version = str(
            proc_result.get("version_number")
            or proc_result.get("version")
            or upload_info.get("version_number")
            or "1"
        )
        log.info("dataset processed; waiting for v%s to be ready", version)
        _set_meta(brand_id, current_stage=f"waiting for Pioneer to index v{version}…")
        await client.wait_for_dataset_ready(
            dataset_name=dataset_name, version=version
        )
        log.info("dataset is ready")
    except Exception as e:
        log.exception("process_upload / wait failed")
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage=f"process failed: {e}")
        return

    # Phase 7 — kick the actual fine-tune.
    _set_meta(brand_id, current_stage="kicking off LoRA training on Qwen3 4B…")
    try:
        job_id = await client.create_training_job(
            model_name=_safe_model_name(brand_id, brand_name),
            dataset_name=dataset_name,
            project_id=project_id,  # link to project so deploy works later
            nr_epochs=2,
            learning_rate=2e-5,
            batch_size=4,
        )
        log.info("pioneer training job_id=%s", job_id)
    except Exception as e:
        log.exception("create_training_job failed")
        _set_status(brand_id, "failed")
        _set_meta(brand_id, current_stage=f"training kickoff failed: {e}")
        return

    _set_status(brand_id, "training", voice_model_id=job_id)
    _set_meta(
        brand_id,
        current_stage="queued — Pioneer is provisioning the trainer…",
        training_progress=0.0,
        pioneer_training_job_id=job_id,
    )

    # Phase 8 — poll training to completion.
    deadline = asyncio.get_event_loop().time() + _POLL_TIMEOUT_SECONDS
    last_stage: str | None = None
    final_model_id: str | None = None
    while True:
        if asyncio.get_event_loop().time() > deadline:
            log.error("training timed out")
            _set_status(brand_id, "failed")
            _set_meta(brand_id, current_stage="training timed out")
            return
        try:
            status = await client.get_training_job(job_id)
        except Exception as e:
            log.warning("poll failed (will retry): %s", e)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            continue

        # Pull latest log line for richer status display in the UI.
        latest_log: str | None = None
        try:
            logs = await client.get_training_logs(job_id, limit=10)
            if logs:
                # Most-recent INFO/WARN/ERROR line.
                latest_log = logs[-1].get("message")
        except Exception:
            pass

        # Always write the timing fields — even when stage hasn't
        # changed — so ETA / epoch counter stays fresh in the UI.
        _set_meta(
            brand_id,
            current_stage=status.stage,
            training_progress=round(status.progress, 3),
            training_progress_percent=int(round(status.progress * 100)),
            current_epoch=status.current_epoch,
            total_epochs=status.total_epochs,
            started_at=status.started_at,
            created_at=status.created_at,
            provider_name=status.provider_name,
            latest_log=latest_log,
        )
        # Heartbeat the status too — heals the row if a backend
        # restart's ``recover_orphaned_jobs`` overzealously marked us
        # as failed while we're still genuinely running.
        if status.status in ("requested", "queued", "running", "training"):
            _set_status(brand_id, "training")

        if status.stage != last_stage:
            log.info(
                "training stage: %s status=%s progress=%.2f epoch=%s/%s",
                status.stage, status.status, status.progress,
                status.current_epoch, status.total_epochs,
            )
            last_stage = status.stage

        if status.status in ("succeeded", "completed", "complete"):
            final_model_id = status.model_id
            break
        if status.status in ("failed", "error", "stopped"):
            log.error("training failed: %s", status.error)
            _set_status(brand_id, "failed")
            _set_meta(
                brand_id,
                current_stage=f"training failed: {status.error or 'unknown'}",
            )
            return
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    if not final_model_id:
        # Some Pioneer responses don't include trained_model_id at job
        # success — fall back to the job_id (Pioneer accepts that as a
        # model identifier in /v1/chat/completions).
        final_model_id = job_id
        log.warning("succeeded without explicit trained_model_id; using job_id")

    # Phase 9 — deploy.
    _set_meta(brand_id, current_stage="deploying trained adapter…")
    try:
        await client.deploy(
            project_id=project_id, training_job_id=job_id
        )
    except Exception as e:
        # Deployment failure is non-fatal — we can still call the trained
        # model directly via /v1/chat/completions using the model_id.
        log.warning("deploy failed (continuing with direct inference): %s", e)
        _set_meta(brand_id, deploy_warning=str(e))

    # Phase 10 — mark adapter live.
    # Pioneer's /v1/chat/completions accepts the TRAINING JOB UUID as
    # the model identifier, NOT the Fireworks model path. Verified
    # 2026-04-26: passing accounts/.../models/pioneer-lora-... 404s
    # with "No inference provider is configured", but the bare job_id
    # returns 200 with a valid completion.
    adapter_url = f"pioneer://{job_id}"
    _set_status(
        brand_id, "ready",
        voice_model_id=final_model_id,  # informative (Fireworks path)
        voice_adapter_url=adapter_url,  # what chat_via_adapter actually uses
    )
    _set_meta(
        brand_id,
        current_stage="adapter live — drafts now route through Pioneer",
        training_progress=1.0,
    )
    log.info(
        "done — pioneer adapter live for brand=%s model=%s",
        brand_id, final_model_id,
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m app.scripts.run_finetune <brand_id>", file=sys.stderr)
        return 2
    brand_id = sys.argv[1].strip()
    _configure_logging(brand_id)
    try:
        asyncio.run(_drive(brand_id))
    except Exception:
        log.exception("worker crashed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
