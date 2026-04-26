"""Redactor selection. Defaults to the regex implementation; switches to the
Google adapter when ``AUDIENCE_PII_PROVIDER=google`` and at least one
Google credential path is present (Cloud DLP via ``GCP_PROJECT_ID``, or
Gemini via ``GEMINI_API_KEY``).

The Google adapter prefers Cloud DLP when both are set; see
``google_dlp.py`` for the mode-selection logic.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

from app.config import settings
from app.services.pii.google_dlp import GoogleDLPRedactor
from app.services.pii.regex_redactor import RegexRedactor
from app.services.pii.types import RedactionResult

log = logging.getLogger(__name__)


class Redactor(Protocol):
    name: str

    def redact(self, text: str) -> RedactionResult: ...

    def rehydrate(self, text: str, mapping: dict[str, str]) -> str: ...


def _select() -> Redactor:
    if os.getenv("AUDIENCE_PII_PROVIDER") == "google" and (
        os.getenv("GCP_PROJECT_ID") or settings.gemini_api_key
    ):
        try:
            return GoogleDLPRedactor()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "pii: google redactor init failed, falling back to regex: %s",
                e,
            )
    return RegexRedactor()


redactor: Redactor = _select()
