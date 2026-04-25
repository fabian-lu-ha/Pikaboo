from functools import lru_cache

from app.config import settings
from app.providers.interfaces import AuthService, StorageService


@lru_cache
def get_auth() -> AuthService:
    if settings.deploy_mode == "supabase":
        from app.providers.supabase import SupabaseAuthService

        return SupabaseAuthService()
    from app.providers.local import LocalAuthService

    return LocalAuthService()


@lru_cache
def get_storage() -> StorageService:
    if settings.deploy_mode == "supabase":
        from app.providers.supabase import SupabaseStorageService

        return SupabaseStorageService()
    from app.providers.local import LocalStorageService

    return LocalStorageService()
