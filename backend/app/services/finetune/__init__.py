"""Pioneer-AI per-tenant fine-tuning.

Every tenant that completes onboarding becomes a candidate for a tiny
Gemma-3-4B LoRA, trained on Pioneer, that drafts in *their* voice — not
a generic marketing voice. The pipeline is corpus_builder → pioneer_client
→ orchestrator → adapter URL on the Brand row. See docs/PIONEER_FINETUNING.md.
"""

from app.services.finetune.orchestrator import (
    start_finetune,
    get_status,
)

__all__ = ["start_finetune", "get_status"]
