"""Regex-based PII redactor.

Inspired by **OpenAI Privacy Filter** (April 2026, Apache-2.0) — a
1.5B-parameter local PII model trained against an 8-category taxonomy
(NAME, EMAIL, PHONE, STREET, URL, DATE, ACCOUNT_NUMBER, SECRET). The
filter itself is not a dependency; this module mirrors the same
category set as a fully offline regex fallback so a no-cloud demo can
still claim coverage parity. Cloud DLP / Gemini-classifier paths in
``redactor.py`` remain primary when configured.

Stable within one ``redact`` call — same value gets the same token.
The companion ``rehydrate`` swaps tokens back. Pattern order is
deliberate: structured patterns (EMAIL/URL/SECRET/PHONE) run before
loose ones (NAME, DATE) so the looser patterns never eat fragments of
the structured matches.
"""
from __future__ import annotations

import re

from app.services.pii.types import RedactionResult


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_URL_RE = re.compile(r"https?://[^\s)>\"']+")
# E.164-ish + common (xxx) xxx-xxxx, with optional country code. Requires at
# least one non-digit separator so a 10+-digit run with no formatting is left
# for the ACCOUNT_NUMBER pass.
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?"
    r"(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{2,4}[\s.-]\d{2,4}(?:[\s.-]\d{2,4})?"
    r"(?!\w)"
)
# Rough street: number followed by capitalized words ending in St/Ave/Rd/etc.
_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Way|Drive|Dr)\b"
)
# Capitalized bigram (First Last) — runs LAST so emails/streets get caught first.
_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b")

# DATE — ISO 8601 (YYYY-MM-DD), slash dates (M/D/YYYY or D/M/YYYY), and
# spelled-out month-day-year. Conservative on purpose: bare 4-digit
# years are NOT matched (too many false positives in product copy /
# prices / counts). Two-digit-year slash dates require a leading
# 1-or-2-digit month/day so "1/2" alone doesn't trigger.
_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{4}-\d{2}-\d{2}"  # 2026-04-26
    r"|\d{1,2}/\d{1,2}/\d{2,4}"  # 4/26/2026 or 26/4/26
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+\d{1,2}(?:,\s*\d{4})?"  # April 26, 2026
    r")\b"
)

# SECRET — looks-like API keys / tokens / long base64ish secrets.
# Order: provider-prefixed keys first (sk_*, pk_*, key_*, AKIA…), then
# generic high-entropy runs of 32+ chars in the [A-Za-z0-9_-] alphabet.
# The 32-char floor keeps us from grabbing slugs or hashes inside URLs.
_SECRET_RE = re.compile(
    r"\b(?:"
    r"(?:sk|pk|rk|key|api|token|secret)_[A-Za-z0-9_\-]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|[A-Za-z0-9_\-]{32,}"
    r")\b"
)

# ACCOUNT_NUMBER — long digit runs that survived the PHONE pass.
# 9-26 digits, with optional spaces/dashes every 3-5 chars (IBAN-ish or
# bank-account formatting). Lower bound 9 dodges short codes; upper
# bound 26 dodges accidental cross-line concatenation.
_ACCOUNT_RE = re.compile(
    r"(?<!\w)(?:\d[ \-]?){8,25}\d(?!\w)"
)


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

        # Order matters: structured patterns run first so loose patterns
        # (NAME, ACCOUNT) never eat fragments of a more specific match.
        # DATE before PHONE so 2026-04-26 doesn't get phone-tokenized.
        # ACCOUNT after PHONE so formatted phone numbers don't slip through
        # as account numbers.
        out = text
        out = sub_with(_EMAIL_RE, "EMAIL", out)
        out = sub_with(_URL_RE, "URL", out)
        out = sub_with(_SECRET_RE, "SECRET", out)
        out = sub_with(_DATE_RE, "DATE", out)
        out = sub_with(_PHONE_RE, "PHONE", out)
        out = sub_with(_ACCOUNT_RE, "ACCOUNT_NUMBER", out)
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
