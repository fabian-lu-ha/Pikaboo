"""PII redaction shared types."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RedactionResult:
    redacted_text: str
    mapping: dict[str, str] = field(default_factory=dict)
    entities: list[dict] = field(default_factory=list)
