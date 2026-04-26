"""Brand picture book — the evergreen visual identity layer.

PIC.md is the brand-level visual style guide that sits ABOVE per-storyboard
``cinematic_brief`` and ABOVE per-shot prompts. Every image-generation call
(keyframes, ingredients, Veo clips, image edits, hero images) reads PIC.md
and prepends it as a context block, so all images cohere on one identity.

Authored by the planning model from brand record + reference_brands +
recent_posts. Refreshed on demand. Append-only "Evolution log" section
captures lessons over time so the book accumulates knowledge.
"""

from app.services.brand_book.pic import (
    PIC_FILENAME,
    append_lesson,
    compose_pic,
    ensure_pic,
    format_for_prompt,
    load_pic,
    pic_path,
    save_pic,
)

__all__ = [
    "PIC_FILENAME",
    "append_lesson",
    "compose_pic",
    "ensure_pic",
    "format_for_prompt",
    "load_pic",
    "pic_path",
    "save_pic",
]
