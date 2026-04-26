"""Pioneer AI (Fastino Labs) HTTP client — real fine-tune API.

Mapped against ``https://agent.pioneer.ai/openapi.json`` on 2026-04-26.
The press release (and the example app at ``fastino-ai/pioneer-example``)
described a separate "personalization" product that lives at a different
URL — that's not this. Pioneer's actual fine-tune API lives at
``api.pioneer.ai`` and follows the standard {project, dataset, training-
job, deployment} pattern.

Pioneer DOESN'T support Gemma despite the press release — the trainable
catalog at /base-models is Llama 3.x + Qwen3 + Qwen2.5. We use
``Qwen/Qwen3-4B-Instruct-2507`` as our default — same 4B size as Gemma
3 4B, 262K context window, supports LoRA training.

End-to-end flow:

1. ``POST /projects`` — one project per tenant
2. ``POST /felix/datasets/upload/url`` → returns a presigned URL
3. ``PUT <presigned_url>`` — upload the JSONL
4. ``POST /felix/datasets/upload/process`` → register the upload
5. ``POST /felix/training-jobs`` — kick LoRA training on Qwen3 4B
6. ``GET /felix/training-jobs/{job_id}`` — poll until succeeded/failed
7. ``POST /projects/{project_id}/deployments`` — deploy the trained model
8. ``POST /v1/chat/completions`` — OpenAI-compatible inference

TLS note: Pioneer's certs at ``api.pioneer.ai`` were observed to be
expired/misissued on 2026-04-26. We pass ``verify=False`` to httpx so
the demo doesn't die on cert errors. Re-enable once they fix it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


@dataclass
class JobStatus:
    job_id: str
    status: str  # pending | running | succeeded | failed | stopped
    progress: float  # 0.0–1.0
    stage: str
    model_id: str | None
    error: str | None = None
    # Timing fields (all parsed from Pioneer's response). Used to
    # compute ETA + render epoch counter in the UI.
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    current_epoch: int | None = None
    total_epochs: int | None = None
    metrics: dict[str, Any] | None = None
    provider_name: str | None = None  # "fireworks" etc.


class _PioneerClient:
    def __init__(self, api_key: str, base_url: str, base_model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._base_model = base_model
        # Pioneer wants ``X-API-Key`` (capitalised). Sending both for
        # robustness.
        self._headers = {
            "X-API-Key": api_key,
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

    @property
    def is_simulator(self) -> bool:
        return False

    def _client(self, *, timeout: float = 30.0) -> httpx.AsyncClient:
        # ``verify=False`` because Pioneer's TLS cert on api.pioneer.ai
        # is currently expired / misissued (observed 2026-04-26). Re-
        # enable when Fastino fixes the cert.
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=timeout,
            verify=False,
        )

    # --- project lifecycle --------------------------------------------------

    async def create_project(self, *, name: str, description: str = "") -> str:
        """Idempotent project creation.

        Pioneer returns 409 Conflict if a project with the same name
        already exists. To make retries safe (especially during demos
        where the worker may run repeatedly), we catch 409 and look the
        project up via ``GET /projects`` to return the existing id.
        """
        async with self._client() as client:
            r = await client.post(
                "/projects",
                json={"name": name, "description": description},
            )
            if r.status_code == 409:
                # Already exists — find it and reuse.
                log.info("project %r exists; reusing", name)
                lr = await client.get("/projects")
                lr.raise_for_status()
                projects = lr.json()
                if isinstance(projects, dict):
                    projects = projects.get("projects") or projects.get("items") or []
                for p in projects:
                    if p.get("name") == name:
                        pid = p.get("id") or p.get("project_id")
                        if pid:
                            return str(pid)
                raise RuntimeError(
                    f"create_project: 409 Conflict but project {name!r} "
                    "not found in /projects list"
                )
            if r.status_code >= 400:
                log.error(
                    "create_project %s — name=%s — body=%s",
                    r.status_code, name, r.text[:300],
                )
                raise RuntimeError(
                    f"create_project HTTP {r.status_code}: {r.text[:200]}"
                )
        body = r.json()
        project_id = body.get("id") or body.get("project_id")
        if not project_id:
            raise RuntimeError(f"create_project: no id in {body}")
        return str(project_id)

    # --- cleanup ------------------------------------------------------------

    async def delete_project(self, project_id: str) -> bool:
        """Best-effort delete. Returns True on 2xx/404, False on other errors."""
        async with self._client() as client:
            r = await client.delete(f"/projects/{project_id}")
        if r.status_code in (200, 202, 204, 404):
            return True
        log.warning(
            "delete_project %s → %s: %s", project_id, r.status_code, r.text[:200]
        )
        return False

    async def delete_training_job(self, job_id: str) -> bool:
        async with self._client() as client:
            r = await client.delete(f"/felix/training-jobs/{job_id}")
        if r.status_code in (200, 202, 204, 404):
            return True
        log.warning(
            "delete_training_job %s → %s: %s", job_id, r.status_code, r.text[:200]
        )
        return False

    async def delete_dataset(self, dataset_name: str) -> bool:
        """Delete every version of the named dataset."""
        async with self._client() as client:
            r = await client.delete(f"/felix/datasets/{dataset_name}")
        if r.status_code in (200, 202, 204, 404):
            return True
        log.warning(
            "delete_dataset %s → %s: %s",
            dataset_name, r.status_code, r.text[:200],
        )
        return False

    # --- dataset upload -----------------------------------------------------

    async def request_upload_url(
        self, *, dataset_name: str, dataset_type: str = "decoder", fmt: str = "jsonl"
    ) -> dict[str, Any]:
        """POST /felix/datasets/upload/url → presigned URL + dataset_id."""
        payload = {
            "dataset_name": dataset_name,
            "dataset_type": dataset_type,
            "format": fmt,
        }
        async with self._client() as client:
            r = await client.post("/felix/datasets/upload/url", json=payload)
        r.raise_for_status()
        return r.json()

    async def upload_to_presigned(
        self, *, presigned_url: str, jsonl_path: str
    ) -> None:
        """PUT the JSONL to the presigned URL Pioneer handed us."""
        path = Path(jsonl_path)
        if not path.exists():
            raise FileNotFoundError(jsonl_path)
        async with httpx.AsyncClient(timeout=300.0, verify=False) as client:
            with path.open("rb") as fh:
                # Pioneer signs the presigned URL with
                # ``content-type=application/octet-stream`` — sending a
                # different Content-Type header makes the S3 signature
                # check fail with 403. Match exactly.
                r = await client.put(
                    presigned_url,
                    content=fh.read(),
                    headers={"Content-Type": "application/octet-stream"},
                )
        r.raise_for_status()

    async def process_upload(self, *, dataset_id: str) -> dict[str, Any]:
        async with self._client() as client:
            r = await client.post(
                "/felix/datasets/upload/process",
                json={"dataset_id": dataset_id},
            )
        r.raise_for_status()
        return r.json()

    async def wait_for_dataset_ready(
        self,
        *,
        dataset_name: str,
        version: str = "1",
        timeout_seconds: float = 90.0,
        poll_interval: float = 2.0,
    ) -> dict[str, Any]:
        """Poll ``GET /felix/datasets/{name}/{version}`` until status is
        terminal-positive.

        Pioneer's ``/upload/process`` returns 202 (async). Firing
        ``create_training_job`` immediately yields a 400 with
        "dataset artifacts are missing in storage". We poll the dataset
        endpoint and return once Pioneer reports it as ready (or raise
        on failure / timeout).
        """
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        last_status = None
        async with self._client() as client:
            while True:
                r = await client.get(
                    f"/felix/datasets/{dataset_name}/{version}"
                )
                if r.status_code < 400:
                    body = r.json()
                    status = (
                        body.get("status")
                        or body.get("normalized_status")
                        or body.get("state")
                        or ""
                    ).lower()
                    if status != last_status:
                        log.info(
                            "dataset %s v%s status=%s",
                            dataset_name, version, status,
                        )
                        last_status = status
                    if status in ("ready", "available", "processed", "active", "completed"):
                        return body
                    if status in ("failed", "error"):
                        raise RuntimeError(
                            f"dataset processing failed: {body}"
                        )
                    # Some Pioneer responses don't include a status
                    # field when ready — if size/sample_size are
                    # populated, treat as ready too.
                    if body.get("size") and body.get("sample_size"):
                        log.info("dataset %s v%s appears ready (size populated)",
                                 dataset_name, version)
                        return body
                if asyncio.get_event_loop().time() > deadline:
                    raise RuntimeError(
                        f"dataset {dataset_name} v{version} not ready after "
                        f"{timeout_seconds}s (last_status={last_status})"
                    )
                await asyncio.sleep(poll_interval)

    # --- training -----------------------------------------------------------

    async def create_training_job(
        self,
        *,
        model_name: str,
        dataset_name: str,
        project_id: str | None = None,
        nr_epochs: int = 2,
        learning_rate: float = 2e-5,
        batch_size: int = 4,
    ) -> str:
        """Create a Pioneer training job. Pass ``project_id`` so the job
        is linkable from ``POST /projects/{pid}/deployments`` later —
        without it, deploy 404s with "Resource not found"."""
        payload: dict[str, Any] = {
            "model_name": model_name,
            "base_model": self._base_model,
            "datasets": [{"name": dataset_name}],
            "training_type": "lora",
            "nr_epochs": nr_epochs,
            "learning_rate": learning_rate,
            "batch_size": batch_size,
        }
        if project_id:
            payload["project_id"] = project_id
        async with self._client(timeout=60.0) as client:
            r = await client.post("/felix/training-jobs", json=payload)
        if r.status_code >= 400:
            # Surface Pioneer's error body — raise_for_status would
            # swallow it, leaving us guessing what they didn't like.
            log.error(
                "create_training_job %s — payload=%s — response=%s",
                r.status_code, payload, r.text[:400],
            )
            raise RuntimeError(
                f"create_training_job HTTP {r.status_code}: {r.text[:200]}"
            )
        body = r.json()
        job_id = body.get("id") or body.get("job_id")
        if not job_id:
            raise RuntimeError(f"create_training_job: no id in {body}")
        return str(job_id)

    async def get_training_job(self, job_id: str) -> JobStatus:
        async with self._client() as client:
            r = await client.get(f"/felix/training-jobs/{job_id}")
        r.raise_for_status()
        body = r.json()
        # Verified field names from a real GET on 2026-04-26:
        # ``normalized_status`` is the canonical lifecycle status,
        # ``progress_percent`` (0-100) and ``current_epoch`` give
        # explicit progress signals, ``trained_model_path`` is set once
        # training completes.
        status = (
            body.get("normalized_status")
            or body.get("status")
            or "requested"
        ).lower()
        progress_percent = body.get("progress_percent")
        if progress_percent is not None:
            progress = float(progress_percent) / 100.0
        else:
            progress = float(body.get("progress") or 0.0)
            if progress > 1.0:
                progress = progress / 100.0
        stage = (
            body.get("current_stage")
            or body.get("stage")
            or status
        )
        model_id = (
            body.get("trained_model_path")
            or body.get("trained_model_id")
            or body.get("fine_tuned_model")
            or body.get("model_id")
        )
        return JobStatus(
            job_id=job_id,
            status=status,
            progress=progress,
            stage=str(stage),
            model_id=model_id,
            error=body.get("error") or body.get("error_message"),
            created_at=body.get("created_at"),
            started_at=body.get("started_at"),
            completed_at=body.get("completed_at"),
            current_epoch=body.get("current_epoch"),
            total_epochs=body.get("nr_epochs"),
            metrics=body.get("metrics"),
            provider_name=body.get("provider_name"),
        )

    async def get_training_logs(
        self, job_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Pull recent structured log entries for a training job.

        Each entry: {id, job_id, timestamp, level, message, source}.
        We surface the latest INFO line in the UI so users see
        meaningful progress like "Uploading 300 training examples to
        Fireworks..." instead of just "training".
        """
        async with self._client() as client:
            r = await client.get(
                f"/felix/training-jobs/{job_id}/logs",
                params={"limit": limit},
            )
        if r.status_code >= 400:
            return []
        body = r.json()
        if isinstance(body, dict):
            return body.get("logs") or []
        if isinstance(body, list):
            return body
        return []

    # --- deployment ---------------------------------------------------------

    async def deploy(
        self, *, project_id: str, training_job_id: str
    ) -> dict[str, Any]:
        async with self._client(timeout=60.0) as client:
            r = await client.post(
                f"/projects/{project_id}/deployments",
                json={"training_job_id": training_job_id},
            )
        r.raise_for_status()
        return r.json()

    # --- inference ----------------------------------------------------------

    async def chat_completion(
        self,
        *,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """OpenAI-compatible chat completion against a Pioneer model."""
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async with self._client(timeout=120.0) as client:
            r = await client.post("/v1/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()


def _extract_lora_text(body: dict[str, Any]) -> str:
    """Pull the assistant's content out of an OpenAI-shaped response."""
    try:
        choices = body.get("choices") or []
        content = choices[0]["message"]["content"]
        return content if isinstance(content, str) else ""
    except Exception:
        return ""


def _parse_envelope(content: str) -> dict[str, Any]:
    """Parse a JSON envelope from text; fall back to caption-only wrap."""
    import json
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"caption": content, "hashtags": [], "cta": ""}


async def chat_via_adapter(
    adapter_url: str,
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any] | None = None,
    api_key: str | None = None,  # noqa: ARG001 — uses settings
    refine_with_gemini: bool = True,
) -> dict[str, Any]:
    """Two-stage brand-voice inference.

    1. **Pioneer LoRA** drafts the post — voice fidelity, recurring
       phrases, vocabulary all baked in from the per-tenant fine-tune.
    2. **Gemini Pro** reads the LoRA draft as a reference and produces
       a sharper, more coherent version while preserving the LoRA's
       voice. Set ``refine_with_gemini=False`` to skip stage 2 (used by
       the side-by-side benchmark to see the raw LoRA output).

    Returns a single JSON envelope ({caption, hashtags, cta}) plus, when
    refinement runs, ``_lora_draft`` and ``_refined: true`` for UI
    display of both stages.
    """
    if not adapter_url.startswith("pioneer://"):
        from app.services.llm.client import chat_json as gemini_chat_json
        log.warning("chat_via_adapter: unrecognised adapter %r", adapter_url)
        return await gemini_chat_json(messages, schema=schema)

    model_id = adapter_url.removeprefix("pioneer://")
    client = get_client()

    # ── Stage 1: LoRA draft ─────────────────────────────────────────
    body = await client.chat_completion(
        model_id=model_id, messages=messages, max_tokens=800
    )
    lora_content = _extract_lora_text(body)
    lora_envelope = _parse_envelope(lora_content)

    if not refine_with_gemini or not lora_content:
        return lora_envelope

    # ── Stage 2: Gemini Pro refines while preserving voice ─────────
    try:
        refined = await _refine_with_gemini(
            messages=messages,
            lora_draft=lora_content,
            schema=schema,
        )
    except Exception as e:
        log.warning("two-stage refine failed; returning LoRA draft: %s", e)
        return lora_envelope

    # Tag the result so the UI can show both stages.
    refined["_lora_draft"] = lora_envelope
    refined["_refined"] = True
    return refined


async def _refine_with_gemini(
    *,
    messages: list[dict[str, str]],
    lora_draft: str,
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Gemini Pro takes the LoRA's draft as a stylistic anchor and
    produces a sharper version. The instruction makes voice
    preservation explicit and non-negotiable — Gemini may improve
    structure, clarity, and substance, but never the voice itself."""
    from app.services.llm.client import chat_json as gemini_chat_json

    # Find the original user brief (the last user message in the chain).
    user_brief = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    # Find the original brand-voice system prompt for context.
    voice_system = next(
        (m["content"] for m in messages if m.get("role") == "system"),
        "",
    )

    refine_messages = [
        {
            "role": "system",
            "content": (
                "You are a senior editor. A per-tenant fine-tuned model "
                "has produced a draft in the brand's exact voice. Your "
                "job is to RETAIN the voice (every recurring phrase, "
                "vocabulary choice, sentence cadence, emoji usage, "
                "punctuation style) while sharpening the draft: tighten "
                "structure, fix any factual or logical weakness, "
                "improve flow. Do NOT introduce phrases the brand "
                "wouldn't use. Treat the brand-voice draft as a "
                "stylistic anchor — your output should be obviously "
                "the same voice, just better.\n\n"
                "Original brand-voice profile (for grounding):\n"
                + voice_system
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original brief:\n{user_brief}\n\n"
                f"Brand-trained model's draft (preserve this voice):\n"
                f"\"\"\"\n{lora_draft}\n\"\"\"\n\n"
                "Now produce a sharper version in the same voice. "
                'Output JSON: {"caption": "...", "hashtags": [...], '
                '"cta": "..."}.'
            ),
        },
    ]
    return await gemini_chat_json(
        refine_messages, schema=schema, model="gemini-3-pro-preview"
    )


_client_singleton: _PioneerClient | None = None


def get_client() -> _PioneerClient:
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton
    if not settings.pioneer_api_key:
        raise RuntimeError(
            "PIONEER_API_KEY is not set. Add it to backend/.env and restart."
        )
    log.info(
        "pioneer: real API at %s, base_model=%s",
        settings.pioneer_base_url, settings.pioneer_base_model,
    )
    _client_singleton = _PioneerClient(
        api_key=settings.pioneer_api_key,
        base_url=settings.pioneer_base_url,
        base_model=settings.pioneer_base_model,
    )
    return _client_singleton


def reset_client() -> None:
    """Test/reload helper."""
    global _client_singleton
    _client_singleton = None
