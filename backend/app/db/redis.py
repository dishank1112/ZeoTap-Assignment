"""
Redis async client — redis-py.

Usage:
    redis = await create_redis_client()
    await redis.set("key", "value")
    await close_redis_client()
"""
from __future__ import annotations

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("db.redis")

_redis: aioredis.Redis | None = None


async def create_redis_client() -> aioredis.Redis:
    """Create and return an async Redis connection."""
    global _redis
    logger.info("redis_connecting", url=settings.REDIS_URL)
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
    )
    # Verify connection
    await _redis.ping()
    logger.info("redis_connected")
    return _redis


async def get_redis() -> aioredis.Redis:
    """Return the existing Redis client."""
    if _redis is None:
        raise RuntimeError("Redis client not initialised. Call create_redis_client() first.")
    return _redis


async def close_redis_client() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("redis_closed")
