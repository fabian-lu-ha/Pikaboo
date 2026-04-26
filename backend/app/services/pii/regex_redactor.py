"""Regex-based PII redactor.

Detects EMAIL, PHONE, URL, NAME (shallow, capitalized-bigram), and very rough
STREET addresses. Stable within one ``redact`` call — same value gets the same
token. The companion ``rehydrate`` swaps tokens back.
"""
from __future__ import annotations

import re

from app.services.pii.types import RedactionResult


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_URL_RE = re.compile(r"https?://[^\s)>\"']+")
# E.164-ish + common (xxx) xxx-xxxx, with optional country code.
_PHONE_RE = re.compile(
    r"(?:(?<!\w)\+?\d[\d\s().-]{7,}\d)(?!\w)"
)
# Rough street: number followed by capitalized words ending in St/Ave/Rd/etc.
_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Way|Drive|Dr)\b"
)
# Capitalized bigram (First Last) — runs LAST so emails/streets get caught first.
_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b")


# Deliberately conservative noise list so common product / brand bigrams don't
# get NAME-tokenized. Personalization briefs use lowercase product names anyway.
_NAME_BLOCKLIST = {
    "Brand Autopilot",
    "United States",
    "United Kingdom",
    "New York",
    "Los Angeles",
    "San Francisco",
    "Field Notes",
    "Studio Logo",
    "Heritage Hoodie",
    "Canvas Field",
    "Insulated Bottle",
    "Enamel Pin",
    "Voice Brand",
    "Notion Brand",
}


class RegexRedactor:
    """Default redactor — pure regex, no network calls."""

    name = "regex"

    def redact(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(redacted_text=text or "")

        mapping: dict[str, str] = {}  # token -> original
        seen: dict[tuple[str, str], str] = {}  # (type, original) -> token
        entities: list[dict] = []
        counters: dict[str, int] = {}

        def assign(kind: str, original: str) -> str:
            key = (kind, original)
            if key in seen:
                return seen[key]
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[{kind}_{counters[kind]}]"
            seen[key] = token
            mapping[token] = original
            entities.append({"type": kind, "original": original, "token": token})
            return token

        def sub_with(pattern: re.Pattern, kind: str, s: str) -> str:
            def _r(m: re.Match) -> str:
                original = m.group(0)
                if kind == "NAME" and original in _NAME_BLOCKLIST:
                    return original
                return assign(kind, original)
            return pattern.sub(_r, s)

        # Order matters: catch the structured ones first so they don't get
        # eaten by the looser NAME / STREET patterns.
        out = text
        out = sub_with(_EMAIL_RE, "EMAIL", out)
        out = sub_with(_URL_RE, "URL", out)
        out = sub_with(_PHONE_RE, "PHONE", out)
        out = sub_with(_STREET_RE, "STREET", out)
        out = sub_with(_NAME_RE, "NAME", out)

        return RedactionResult(redacted_text=out, mapping=mapping, entities=entities)

    def rehydrate(self, text: str, mapping: dict[str, str]) -> str:
        if not text or not mapping:
            return text
        # Replace longer tokens first so [NAME_10] doesn't get partially matched
        # by [NAME_1].
        out = text
        for token in sorted(mapping.keys(), key=len, reverse=True):
            out = out.replace(token, mapping[token])
        return out
