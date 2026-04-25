from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthService(Protocol):
    async def current_user(self, token: str | None) -> dict | None: ...


@runtime_checkable
class StorageService(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str: ...

    async def get_url(self, key: str) -> str: ...
