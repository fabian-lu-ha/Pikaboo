"""Google-backed PII redactor.

Two execution modes, picked once at construction:

* **Cloud DLP REST** — preferred. Activates when ``GCP_PROJECT_ID`` is set
  and ``google-cloud-dlp`` is importable. Uses ``inspect_content`` with the
  default infoTypes (EMAIL_ADDRESS, PHONE_NUMBER, PERSON_NAME,
  STREET_ADDRESS, CREDIT_CARD_NUMBER, IP_ADDRESS). Auth via ADC.
* **Gemini classifier** — fallback. Activates when only
  ``GEMINI_API_KEY`` is configured. Asks ``gemini-3-flash`` to return
  PII spans as JSON. Different transport, same Google PII story.

Either way the redaction step itself is *local* substring substitution,
so ``rehydrate()`` never has to call back to Google.

Why local tokens instead of DLP's ``cryptoDeterministicConfig``: KMS-wrapped
deterministic tokens require a configured KMS keyring + service account
permissions, which is heavy for a hackathon. Local ``[EMAIL_1]`` style
placeholders give the LLM a clean signal AND make rehydrate a one-liner.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types as genai_types

from app.config import settings
from app.services.pii.types import RedactionResult

log = logging.getLogger(__name__)

# DLP info types we ask for. Mapped to short tokens that show up in the
# redacted text. Keep this list aligned across the DLP and Gemini paths.
_INFO_TYPES: tuple[str, ...] = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON_NAME",
    "STREET_ADDRESS",
    "CREDIT_CARD_NUMBER",
    "IP_ADDRESS",
)

_TYPE_TOKEN: dict[str, str] = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "PERSON_NAME": "NAME",
    "STREET_ADDRESS": "STREET",
    "CREDIT_CARD_NUMBER": "CARD",
    "IP_ADDRESS": "IP",
}

_GEMINI_SYSTEM = (
    "You are a PII detector. Identify spans of personal information in the "
    "input text. Output strict JSON: {\"spans\": [{\"text\": str, \"type\": "
    "str}]}. The 'type' MUST be one of: EMAIL_ADDRESS, PHONE_NUMBER, "
    "PERSON_NAME, STREET_ADDRESS, CREDIT_CARD_NUMBER, IP_ADDRESS. Use the "
    "EXACT substring as it appears in the input (preserve case + "
    "punctuation). Do not hallucinate spans that are not there. Do not "
    "tokenize URLs, product names, brand names, generic geographic terms "
    "(country / city / region), currency amounts, or dates."
)


class GoogleDLPRedactor:
    """Google-backed redactor. Picks Cloud DLP if available, else Gemini."""

    name = "google_dlp"

    def __init__(self) -> None:
        self._mode = "gemini"
        self._dlp: Any = None
        self._dlp_module: Any = None
        self._gemini: genai.Client | None = None
        self._project = os.getenv("GCP_PROJECT_ID")
        self._location = os.getenv("GCP_DLP_LOCATION", "global")

        if self._project:
            try:
                from google.cloud import dlp_v2  # type: ignore[import-not-found]

                self._dlp_module = dlp_v2
                self._dlp = dlp_v2.DlpServiceClient()
                self._mode = "dlp"
                self.name = "google_dlp_cloud"
                log.info(
                    "pii: cloud dlp ready (project=%s, location=%s)",
                    self._project,
                    self._location,
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "pii: cloud dlp init failed, falling back to gemini: %s",
                    e,
                )

        if self._mode == "gemini":
            if not settings.gemini_api_key:
                raise RuntimeError(
                    "GoogleDLPRedactor requires GEMINI_API_KEY "
                    "(set AUDIENCE_PII_PROVIDER=google) or GCP_PROJECT_ID "
                    "(for Cloud DLP)."
                )
            self._gemini = genai.Client(api_key=settings.gemini_api_key)
            self.name = "google_gemini"
            log.info(
                "pii: gemini classifier ready (model=%s)",
                settings.gemini_model,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def redact(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(redacted_text="")
        try:
            spans = (
                self._dlp_inspect(text)
                if self._mode == "dlp"
                else self._gemini_detect(text)
            )
        except Exception:  # noqa: BLE001
            # Detection failure must NOT leak PII to the LLM. Return an
            # empty redaction so callers can decide to retry / abort.
            log.exception(
                "pii: %s detection failed — returning unredacted text "
                "(caller should treat this as fail-closed)",
                self.name,
            )
            return RedactionResult(redacted_text=text)
        return self._tokenize(text, spans)

    def rehydrate(self, text: str, mapping: dict[str, str]) -> str:
        if not text or not mapping:
            return text
        # Replace longer tokens first so [NAME_10] doesn't get partially
        # eaten by [NAME_1].
        out = text
        for token in sorted(mapping.keys(), key=len, reverse=True):
            out = out.replace(token, mapping[token])
        return out

    # ------------------------------------------------------------------
    # Cloud DLP path
    # ------------------------------------------------------------------

    def _dlp_inspect(self, text: str) -> list[tuple[str, str]]:
        """Return ``[(quote, info_type_name), ...]`` for DLP findings."""
        assert self._dlp is not None and self._dlp_module is not None
        request = {
            "parent": (
                f"projects/{self._project}/locations/{self._location}"
            ),
            "inspect_config": {
                "info_types": [{"name": n} for n in _INFO_TYPES],
                "include_quote": True,
                "min_likelihood": self._dlp_module.Likelihood.POSSIBLE,
            },
            "item": {"value": text},
        }
        resp = self._dlp.inspect_content(request=request)
        out: list[tuple[str, str]] = []
        for f in resp.result.findings:
            if not f.quote:
                continue
            out.append((f.quote, f.info_type.name))
        return out

    # ------------------------------------------------------------------
    # Gemini path
    # ------------------------------------------------------------------

    _SCHEMA: dict = {
        "type": "object",
        "properties": {
            "spans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["text", "type"],
                },
            },
        },
        "required": ["spans"],
    }

    def _gemini_detect(self, text: str) -> list[tuple[str, str]]:
        assert self._gemini is not None
        resp = self._gemini.models.generate_content(
            model=settings.gemini_model,
            contents=[{"role": "user", "parts": [{"text": text}]}],
            config=genai_types.GenerateContentConfig(
                system_instruction=_GEMINI_SYSTEM,
                response_mime_type="application/json",
                response_schema=self._SCHEMA,
            ),
        )
        try:
            data = json.loads(resp.text or "{}")
        except json.JSONDecodeError:
            log.warning("pii: gemini returned non-JSON; treating as no findings")
            return []
        spans = data.get("spans") or []
        out: list[tuple[str, str]] = []
        for s in spans:
            quote = (s or {}).get("text") or ""
            type_name = (s or {}).get("type") or ""
            if quote and type_name in _INFO_TYPES:
                out.append((quote, type_name))
        return out

    # ------------------------------------------------------------------
    # Local tokenization (shared by both paths)
    # ------------------------------------------------------------------

    def _tokenize(
        self,
        text: str,
        spans: list[tuple[str, str]],
    ) -> RedactionResult:
        # Dedupe (quote, type) — same value gets the same token regardless
        # of how many times Google reports it. Sort by quote length DESC so
        # longer matches replace first; that prevents "Anna" being tokenized
        # before the longer "Anna Schmidt".
        seen_pairs: set[tuple[str, str]] = set()
        unique_spans: list[tuple[str, str]] = []
        for quote, type_name in spans:
            key = (quote, type_name)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            unique_spans.append((quote, type_name))
        unique_spans.sort(key=lambda x: len(x[0]), reverse=True)

        seen: dict[tuple[str, str], str] = {}
        counters: dict[str, int] = {}
        mapping: dict[str, str] = {}
        entities: list[dict] = []

        def assign(short: str, quote: str) -> str:
            key = (short, quote)
            if key in seen:
                return seen[key]
            counters[short] = counters.get(short, 0) + 1
            token = f"[{short}_{counters[short]}]"
            seen[key] = token
            mapping[token] = quote
            entities.append(
                {"type": short, "original": quote, "token": token}
            )
            return token

        out = text
        for quote, type_name in unique_spans:
            short = _TYPE_TOKEN.get(type_name, type_name)
            token = assign(short, quote)
            # Replace every occurrence; LLM only sees tokens.
            out = out.replace(quote, token)

        return RedactionResult(
            redacted_text=out,
            mapping=mapping,
            entities=entities,
        )
