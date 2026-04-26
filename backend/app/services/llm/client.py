import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

log = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _get_adapter_url(brand_id: str) -> str | None:
    """Return the brand's deployed Pioneer adapter URL, if any.

    Imported lazily — the LLM client is loaded at startup and we don't
    want a circular import via app.db.models. None returned on any error.
    """
    try:
        from app.db import models
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            row = db.get(models.Brand, brand_id)
            if row is None:
                return None
            url = row.voice_adapter_url
            status = row.voice_model_status
            if url and status == "ready":
                return url
            return None
    except Exception as e:
        log.warning("adapter lookup failed for brand=%s: %s", brand_id, e)
        return None


def _strip_unsupported(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {
            k: _strip_unsupported(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_strip_unsupported(item) for item in schema]
    return schema


def _split_messages(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        text = m["content"]
        if role == "system":
            system_parts.append(text)
        elif role in ("user", "assistant"):
            mapped = "user" if role == "user" else "model"
            contents.append({"role": mapped, "parts": [{"text": text}]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, contents


async def chat_json(
    messages: list[dict[str, str]],
    schema: dict[str, Any] | None = None,
    model: str | None = None,
    brand_id: str | None = None,
    force_no_schema: bool = False,
) -> dict[str, Any]:
    """JSON-shaped chat completion.

    When ``brand_id`` is supplied AND the brand has a Pioneer adapter
    deployed (status=ready), route through the adapter. **No fallback** —
    if the adapter call fails, the exception propagates so the caller
    knows the brand-voice path broke. Silent Gemini substitution would
    let bugs hide as "still working".

    When ``brand_id`` is None (or no adapter is deployed for that
    brand), Gemini is the primary path — no per-tenant model exists yet,
    so this is the legitimate generic call.

    ``force_no_schema``: when True, send ``response_mime_type=application/json``
    but DO NOT send ``response_schema`` even if one is provided. Use this for
    callers whose schema trips Gemini 3 Pro's stricter structured-output
    validator (it rejects schemas with too many top-level objects, even when
    every individual sub-schema would pass). The model still emits JSON; the
    caller is responsible for runtime validation.
    """
    if brand_id:
        adapter_url = _get_adapter_url(brand_id)
        if adapter_url:
            from app.services.finetune.pioneer_client import chat_via_adapter

            return await chat_via_adapter(
                adapter_url, messages, schema=schema
            )

    client = _get_client()
    system_instruction, contents = _split_messages(messages)

    config_kwargs: dict[str, Any] = {}
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        if not force_no_schema:
            config_kwargs["response_schema"] = _strip_unsupported(schema)
    elif force_no_schema:
        # No schema supplied but caller still wants JSON mode.
        config_kwargs["response_mime_type"] = "application/json"

    try:
        response = await client.aio.models.generate_content(
            model=model or settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        # Gemini's "Request contains an invalid argument" is famously
        # unhelpful — it can mean schema, content, or model name. Dump the
        # request shape so the next failure has a fighting chance of being
        # diagnosed without a bisect script.
        if "INVALID_ARGUMENT" in str(e):
            schema_preview = (
                json.dumps(config_kwargs.get("response_schema"))[:1500]
                if "response_schema" in config_kwargs
                else "<no schema>"
            )
            log.warning(
                "chat_json INVALID_ARGUMENT model=%s contents_msgs=%s "
                "system_chars=%s schema_preview=%s",
                model or settings.gemini_model,
                len(contents),
                len(system_instruction or ""),
                schema_preview,
            )
        raise
    return json.loads(response.text)
