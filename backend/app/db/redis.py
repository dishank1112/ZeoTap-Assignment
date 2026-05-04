from __future__ import annotations

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("db.redis")

_redis: aioredis.Redis | "NullRedisClient" | None = None


class NullRedisClient:
    """Fallback Redis client that preserves runtime behavior when Redis is unavailable."""

    async def ping(self) -> bool:
        return True

    async def incrby(self, key: str, amount: int) -> int:
        return amount

    async def expire(self, key: str, ttl: int) -> None:
        return None

    async def get(self, key: str) -> None:
        return None

    async def set(self, key: str, value: str, **kwargs: object) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        return None

    async def aclose(self) -> None:
        return None


async def create_redis_client() -> aioredis.Redis | NullRedisClient:
    """Create and return an async Redis connection or fallback client."""
    global _redis
    logger.info("redis_connecting", url=settings.REDIS_URL)
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
    )
    try:
        await _redis.ping()
        logger.info("redis_connected")
        return _redis
    except Exception as exc:
        logger.warning(
            "redis_unavailable_fallback",
            error=str(exc),
            url=settings.REDIS_URL,
        )
        _redis = NullRedisClient()
        return _redis


async def get_redis() -> aioredis.Redis | NullRedisClient:
    """Return the existing Redis client."""
    if _redis is None:
        raise RuntimeError("Redis client not initialised. Call create_redis_client() first.")
    return _redis


async def close_redis_client() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis and not isinstance(_redis, NullRedisClient):
        await _redis.aclose()
    _redis = None
    logger.info("redis_closed")
