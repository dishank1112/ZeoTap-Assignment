from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logger import get_logger
from app.schemas.signal import SignalResponse
from app.services.debounce_service import DebounceService
from app.services.incident_service import (
    cache_incident_dashboard_state,
    increment_incident_signal_count,
)

logger = get_logger("ingestion")


def _signal_document(signal: SignalResponse, incident_id: str) -> dict[str, Any]:
    return {
        "_id": signal.id,
        "timestamp": signal.timestamp,
        "component_id": signal.component_id,
        "component_type": signal.component_type.value,
        "severity": signal.severity.value,
        "message": signal.message,
        "payload": signal.payload,
        "incident_id": incident_id,
        "received_at": signal.received_at,
        "stored_at": datetime.now(timezone.utc),
    }


class IngestionService:
    def __init__(
        self,
        *,
        mongo: AsyncIOMotorDatabase,
        postgres: asyncpg.Pool,
        redis: aioredis.Redis,
    ) -> None:
        self.mongo = mongo
        self.postgres = postgres
        self.redis = redis
        self.debounce = DebounceService(redis, postgres)

    async def process_signal(self, signal: SignalResponse) -> str:
        incident_id = await self.debounce.get_or_create_incident_id(signal)
        await self.mongo.raw_signals.insert_one(_signal_document(signal, incident_id))
        incident = await increment_incident_signal_count(self.postgres, incident_id)
        await cache_incident_dashboard_state(self.redis, incident)
        logger.debug(
            "signal_persisted",
            signal_id=signal.id,
            incident_id=incident_id,
            component_id=signal.component_id,
        )
        return incident_id
