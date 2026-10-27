import asyncio
import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

_MEMORY_CACHE: dict[str, str] = {}


class HybridCacheClient:
    """Client Redis asynchrone avec repli mémoire instantané si le démon Redis n'est pas joignable."""

    def __init__(self, redis_url: str | None = None) -> None:
        settings = get_settings()
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis_available: bool | None = None
        self._client = aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )

    async def set_value(self, key: str, value: str, ex: int = 3600) -> str:
        if self._redis_available is False:
            _MEMORY_CACHE[key] = value
            return "memory_fallback"
        try:
            await asyncio.wait_for(self._client.set(key, value, ex=ex), timeout=0.35)
            self._redis_available = True
            return "redis"
        except Exception:
            self._redis_available = False
            _MEMORY_CACHE[key] = value
            return "memory_fallback"

    async def get_value(self, key: str) -> str | None:
        if self._redis_available is False:
            return _MEMORY_CACHE.get(key)
        try:
            val = await asyncio.wait_for(self._client.get(key), timeout=0.35)
            self._redis_available = True
            return val
        except Exception:
            self._redis_available = False
            return _MEMORY_CACHE.get(key)

    async def set_json(self, key: str, payload: dict[str, Any], ttl_seconds: int = 3600) -> str:
        return await self.set_value(key, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        raw = await self.get_value(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def get_counter(self, key: str) -> int:
        raw = await self.get_value(key)
        if not raw:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def incr_counter(self, key: str, ttl_seconds: int = 3600) -> int:
        current = await self.get_counter(key)
        next_val = current + 1
        await self.set_value(key, str(next_val), ex=ttl_seconds)
        return next_val

    async def clear_prefix(self, prefix: str) -> None:
        for k in list(_MEMORY_CACHE.keys()):
            if k.startswith(prefix):
                _MEMORY_CACHE.pop(k, None)
        if self._redis_available is False:
            return
        try:
            keys = await asyncio.wait_for(self._client.keys(f"{prefix}*"), timeout=0.35)
            if keys:
                await asyncio.wait_for(self._client.delete(*keys), timeout=0.35)
        except Exception:
            pass

    async def health_check(self) -> dict[str, Any]:
        if self._redis_available is False:
            return {
                "status": "healthy_fallback",
                "backend": "in_memory_cache",
                "connected": False,
                "detail": "Redis daemon unreachable, using fast in-memory fallback.",
            }
        try:
            pong = await asyncio.wait_for(self._client.ping(), timeout=0.35)
            self._redis_available = bool(pong)
            return {
                "status": "healthy" if pong else "degraded",
                "backend": "redis_server",
                "connected": bool(pong),
            }
        except Exception as exc:
            self._redis_available = False
            return {
                "status": "healthy_fallback",
                "backend": "in_memory_cache",
                "connected": False,
                "detail": f"Redis daemon unreachable ({exc.__class__.__name__}), using in-memory fallback.",
            }

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._client.aclose(), timeout=0.25)
        except Exception:
            pass


cache_client = HybridCacheClient()


def get_redis_client() -> HybridCacheClient:
    return cache_client
