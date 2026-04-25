from pathlib import Path

from app.config import settings


class LocalAuthService:
    async def current_user(self, token: str | None) -> dict | None:
        return {"id": "local", "email": "local@local"}


class LocalStorageService:
    def __init__(self) -> None:
        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        path = Path(settings.storage_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def get_url(self, key: str) -> str:
        return f"/api/storage/{key}"
