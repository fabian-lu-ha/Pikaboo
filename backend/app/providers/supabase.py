from app.config import settings


def _client():
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "DEPLOY_MODE=supabase requires SUPABASE_URL and SUPABASE_KEY"
        )
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_key)


class SupabaseAuthService:
    def __init__(self) -> None:
        self._c = _client()

    async def current_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        result = self._c.auth.get_user(token)
        if not result or not result.user:
            return None
        return {"id": result.user.id, "email": result.user.email}


class SupabaseStorageService:
    BUCKET = "brand-autopilot"

    def __init__(self) -> None:
        self._c = _client()

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        self._c.storage.from_(self.BUCKET).upload(
            path=key, file=data, file_options={"content-type": content_type}
        )
        return key

    async def get_url(self, key: str) -> str:
        return self._c.storage.from_(self.BUCKET).get_public_url(key)
