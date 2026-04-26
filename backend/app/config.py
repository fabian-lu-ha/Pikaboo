from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    deploy_mode: Literal["local", "supabase"] = "local"
    database_url: str = "sqlite:///./brand_autopilot.db"
    supabase_url: str | None = None
    supabase_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3-flash-preview"
    # Heavier reasoning model used for the storyboard *plan* — narrative arc,
    # cast bible, per-scene motion direction. Frame/scene gen still uses
    # nano-banana-pro / Veo, so this only fires once per /suggest call.
    gemini_planning_model: str = "gemini-3-pro-preview"
    gemini_image_model: str = "nano-banana-pro-preview"
    # Per-scene video clip generation. Veo is long-running; scene_gen picks
    # the fast or quality variant based on the request's `quality` field.
    #
    # Model selection (Apr 2026, Gemini API access):
    #   - veo-3.0-* only supports 8s clips; we ask for 4-6s. Using 3.0
    #     produced silent inflation or random failures on 4s requests.
    #   - veo-3.1-lite-generate-preview: $0.05/s 720p (HALF the price of
    #     fast), supports 4/6/8s natively, supports image-to-video AND
    #     reference images, 10 RPM / 10 concurrent — fits our 6-parallel
    #     storyboard pattern. Right default for storyboards.
    #   - veo-3.1-fast-generate-preview: $0.10/s, same capabilities, better
    #     motion fidelity. Use for hero/quality renders.
    veo_fast_model: str = "veo-3.1-lite-generate-preview"
    veo_quality_model: str = "veo-3.1-fast-generate-preview"
    # Gemini TTS — narrates the voiceover layer that's muxed onto the
    # rendered video. Returns 24kHz PCM mono; the voiceover service wraps
    # it as WAV before ffmpeg mixes it into the mp4.
    gemini_tts_model: str = "gemini-3.1-flash-tts-preview"
    peec_api_key: str | None = None
    peec_base_url: str = "https://api.peec.ai"
    peec_mcp_url: str = "https://api.peec.ai/mcp"
    peec_project_id: str | None = None
    storage_dir: str = "./storage"

    # Pioneer AI (Fastino Labs) — real fine-tune API at api.pioneer.ai.
    # Per /base-models response on 2026-04-26, Pioneer's trainable
    # catalog is Llama 3.x + Qwen3 + Qwen2.5 (NO Gemma despite the
    # press release). Closest equivalent to Gemma 3 4B is Qwen3 4B
    # Instruct — same param count, 262K context (vs Gemma's 128K),
    # supports LoRA training.
    pioneer_api_key: str | None = None
    pioneer_base_url: str = "https://api.pioneer.ai"
    pioneer_base_model: str = "Qwen/Qwen3-4B-Instruct-2507"

    # Tavily — web search + extraction for the research leg. Without a key
    # the research service is a no-op (returns empty findings) and onboarding
    # / agent loop just skip the research step. The same `gather_brand_context`
    # entry point is called from onboarding and the agent loop so behavior is
    # consistent across surfaces.
    tavily_api_key: str | None = None
    tavily_base_url: str = "https://api.tavily.com"
    # search_depth=advanced is ~2x credits but pulls 2-3x more relevant
    # snippets — matters for grounding LLM drafts. We default to advanced
    # for the agent loop (one call per campaign) and basic for onboarding
    # (multiple parallel calls per brand).
    tavily_default_depth: Literal["basic", "advanced"] = "advanced"
    # How many results to keep per query before passing to the LLM. Tavily
    # caps at 20; 6-8 is enough to ground a draft without blowing context.
    tavily_max_results: int = 6

    # Where the backend serves itself — used to rewrite /api/storage/... URLs
    # into absolute URLs the Remotion subprocess (and other out-of-process
    # consumers) can fetch over HTTP. Headless Chromium blocks file:// reads
    # of arbitrary local paths so we MUST go through HTTP for video render.
    server_base_url: str = "http://localhost:8000"

    # AI-decided inter-scene transitions (transitions.py). On by default —
    # the Gemini editor decides per-pair: veo_bridge (4s motion bridge),
    # match_cut (hard cut, the default for ~70% of pairs), or crossfade.
    # Bridges add Veo cost and ~30-60s of render latency PER bridge that
    # the editor opts into. The Remotion composition consumes the
    # `transitions` prop and interleaves bridges + applies per-pair fades.
    enable_veo_transitions: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
