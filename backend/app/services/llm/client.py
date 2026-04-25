import json
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


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
) -> dict[str, Any]:
    client = _get_client()
    system_instruction, contents = _split_messages(messages)

    config_kwargs: dict[str, Any] = {}
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = _strip_unsupported(schema)

    response = await client.aio.models.generate_content(
        model=model or settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return json.loads(response.text)
