"""Video analysis service.

Downloads short-form video posts (TikTok / YouTube Shorts & videos /
Instagram Reels) via yt-dlp and analyzes them with Gemini's multimodal
video understanding to produce a transcript, visual summary, key moments,
and style observations the rest of the brand pipeline can reason over.
"""

from app.services.video.analyzer import (
    VideoAnalysis,
    analyze_post,
    attach_analysis,
    is_video_post,
)

__all__ = [
    "VideoAnalysis",
    "analyze_post",
    "attach_analysis",
    "is_video_post",
]
