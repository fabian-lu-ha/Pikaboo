"""Marketing-video keyframe + clip generator services.

Sub-services compose the 5th surface (a 12-15s marketing video):

  - storyboard.py  — Gemini 3.1 Pro Preview-driven plan: narrative + cast
    bible (with narrative_purpose enforcement) + per-frame motion direction.
  - cast.py        — in-memory registry mapping cast IDs to canonical
    reference image URLs; auto-binds brand-uploaded assets when relevant.
  - frame_gen.py   — neutral ingredient sheets (character/setting/prop)
    via nano-banana-pro and one-shot still keyframes (legacy / fallback).
  - scene_gen.py   — per-frame video clips via Veo 3.1, conditioned on
    cast canonicals; long-running operation polled to completion.
  - renderer.py    — subprocess wrapper around the Remotion CLI that
    composites either stills or Veo clips with brand-typographic captions.
"""

from app.services.video_gen.frame_gen import (
    generate_ingredient,
    generate_video_frame,
)
from app.services.video_gen.renderer import (
    RemotionNotInstalledError,
    render_video,
)
from app.services.video_gen.scene_gen import generate_scene
from app.services.video_gen.storyboard import suggest_storyboard

__all__ = [
    "RemotionNotInstalledError",
    "generate_ingredient",
    "generate_scene",
    "generate_video_frame",
    "render_video",
    "suggest_storyboard",
]
