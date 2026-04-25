from dataclasses import dataclass, field


@dataclass
class Post:
    platform: str
    caption: str
    media_urls: list[str] = field(default_factory=list)
    posted_at: str | None = None
    url: str | None = None
    likes: int | None = None
    # Populated post-fetch by app.services.video.analyzer.attach_analysis.
    # Shape mirrors VideoAnalysis (asdict): transcript, key_moments,
    # visual_summary, content_summary, style_observations, duration_seconds.
    video_analysis: dict | None = None


def post_to_dict(p: Post) -> dict:
    return {
        "platform": p.platform,
        "caption": p.caption,
        "media_urls": p.media_urls,
        "posted_at": p.posted_at,
        "url": p.url,
        "likes": p.likes,
        "video_analysis": p.video_analysis,
    }
