"""PII redaction service.

Two adapters share one Protocol:
  - ``RegexRedactor`` — default; pure regex, no network.
  - ``GoogleDLPRedactor`` — stub; orchestrator wires this in later.

Use the module-level ``redactor`` instance — selection happens at import
time based on env (``AUDIENCE_PII_PROVIDER``) and config.
"""
from app.services.pii.redactor import Redactor, redactor
from app.services.pii.types import RedactionResult

__all__ = ["redactor", "Redactor", "RedactionResult"]
