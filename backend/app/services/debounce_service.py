from __future__ import annotations

import asyncio
from uuid import uuid4

import asyncpg
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import get_logger
from app.schemas.signal import SignalResponse
from app.services.incident_service import create_incident_from_signal

logger = get_logger("debounce")


class DebounceService:
    """Redis-backed sliding debounce window for component incidents."""

    def __init__(self, redis: aioredis.Redis, pool: asyncpg.Pool) -> None:
        self.redis = redis
        self.pool = pool

    def _incident_key(self, component_id: str) -> str:
        return f"debounce:component:{component_id}:incident"

    def _lock_key(self, component_id: str) -> str:
        return f"debounce:component:{component_id}:lock"

    async def get_or_create_incident_id(self, signal: SignalResponse) -> str:
        incident_key = self._incident_key(signal.component_id)
        lock_key = self._lock_key(signal.component_id)
        deadline = asyncio.get_running_loop().time() + 5.0

        while True:
            existing = await self.redis.get(incident_key)
            if existing:
                await self.redis.expire(incident_key, settings.DEBOUNCE_WINDOW_SECONDS)
                return str(existing)

            token = str(uuid4())
            acquired = await self.redis.set(lock_key, token, nx=True, ex=5)
            if acquired:
                try:
                    existing_after_lock = await self.redis.get(incident_key)
                    if existing_after_lock:
                        await self.redis.expire(
                            incident_key,
                            settings.DEBOUNCE_WINDOW_SECONDS,
                        )
                        return str(existing_after_lock)

                    incident = await create_incident_from_signal(self.pool, signal)
                    await self.redis.set(
                        incident_key,
                        incident.id,
                        ex=settings.DEBOUNCE_WINDOW_SECONDS,
                    )
                    logger.info(
                        "incident_created_for_debounce_window",
                        incident_id=incident.id,
                        component_id=signal.component_id,
                    )
                    return incident.id
                finally:
                    current_token = await self.redis.get(lock_key)
                    if current_token == token:
                        await self.redis.delete(lock_key)

            if asyncio.get_running_loop().time() >= deadline:
                logger.warning(
                    "debounce_lock_wait_timeout",
                    component_id=signal.component_id,
                )
            await asyncio.sleep(0.025)
