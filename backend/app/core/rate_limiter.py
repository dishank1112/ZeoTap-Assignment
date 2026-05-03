from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.core.config import settings


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    scope: str
    limit: int
    used: int
    reset_after_seconds: int


class RedisRateLimiter:
    """Fixed-window Redis rate limiter for signal ingestion."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis

    async def consume(self, client_id: str, amount: int = 1) -> RateLimitResult:
        window_seconds = settings.RATE_LIMIT_WINDOW_SECONDS
        now = int(time.time())
        window = now // window_seconds
        reset_after = window_seconds - (now % window_seconds)

        global_result = await self._consume_key(
            key=f"rate:global:{window}",
            amount=amount,
            limit=settings.RATE_LIMIT_GLOBAL,
            ttl=reset_after + 1,
            scope="global",
            reset_after=reset_after,
        )
        if not global_result.allowed:
            return global_result

        safe_client_id = client_id.replace(":", "_")
        return await self._consume_key(
            key=f"rate:ip:{safe_client_id}:{window}",
            amount=amount,
            limit=settings.RATE_LIMIT_PER_IP,
            ttl=reset_after + 1,
            scope="ip",
            reset_after=reset_after,
        )

    async def _consume_key(
        self,
        *,
        key: str,
        amount: int,
        limit: int,
        ttl: int,
        scope: str,
        reset_after: int,
    ) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(True, scope, limit, 0, reset_after)

        used = await self.redis.incrby(key, amount)
        if used == amount:
            await self.redis.expire(key, ttl)

        return RateLimitResult(
            allowed=used <= limit,
            scope=scope,
            limit=limit,
            used=int(used),
            reset_after_seconds=reset_after,
        )
