from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    deploy_mode: Literal["local", "supabase"] = "local"
    database_url: str = "sqlite:///./brand_autopilot.db"
    supabase_url: str | None = None
    supabase_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3-flash-preview"
    gemini_image_model: str = "nano-banana-pro-preview"
    peec_api_key: str | None = None
    peec_base_url: str = "https://api.peec.ai"
    peec_mcp_url: str = "https://api.peec.ai/mcp"
    peec_project_id: str | None = None
    storage_dir: str = "./storage"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
