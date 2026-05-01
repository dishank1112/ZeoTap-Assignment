from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import asyncpg
import redis.asyncio as aioredis

from app.schemas.incident import IncidentResponse
from app.schemas.signal import SignalResponse
from app.services.alerting_strategy import get_alerting_strategy


def _record_to_incident(record: asyncpg.Record) -> IncidentResponse:
    data = dict(record)
    data["id"] = str(data["id"])
    return IncidentResponse(**data)


async def create_incident_from_signal(
    pool: asyncpg.Pool,
    signal: SignalResponse,
) -> IncidentResponse:
    decision = get_alerting_strategy(signal.component_type).decide(signal)
    incident_id = uuid4()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            """
            INSERT INTO incidents (
                id, component_id, component_type, severity, status, alert_type,
                summary, signal_count, created_at, updated_at, start_time
            )
            VALUES ($1, $2, $3, $4, 'OPEN', $5, $6, 0, $7, $7, $8)
            RETURNING *
            """,
            incident_id,
            signal.component_id,
            signal.component_type.value,
            signal.severity.value,
            decision.alert_type,
            decision.summary,
            now,
            signal.timestamp,
        )
    return _record_to_incident(record)


async def increment_incident_signal_count(
    pool: asyncpg.Pool,
    incident_id: str,
) -> IncidentResponse:
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            """
            UPDATE incidents
            SET signal_count = signal_count + 1,
                updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING *
            """,
            incident_id,
        )
    if record is None:
        raise LookupError(f"Incident '{incident_id}' not found")
    return _record_to_incident(record)


async def get_incident(pool: asyncpg.Pool, incident_id: str) -> IncidentResponse | None:
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT * FROM incidents WHERE id = $1::uuid",
            incident_id,
        )
    return _record_to_incident(record) if record else None


async def list_incidents(
    pool: asyncpg.Pool,
    *,
    limit: int,
    offset: int,
    component_id: str | None = None,
    status: str | None = None,
) -> tuple[int, list[IncidentResponse]]:
    filters = []
    args: list[Any] = []

    if component_id:
        args.append(component_id.upper())
        filters.append(f"component_id = ${len(args)}")
    if status:
        args.append(status)
        filters.append(f"status = ${len(args)}")

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM incidents {where}", *args)
        args.extend([limit, offset])
        records = await conn.fetch(
            f"""
            SELECT *
            FROM incidents
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(args) - 1}
            OFFSET ${len(args)}
            """,
            *args,
        )
    return int(total), [_record_to_incident(record) for record in records]


async def cache_incident_dashboard_state(
    redis: aioredis.Redis,
    incident: IncidentResponse,
) -> None:
    payload = json.dumps(incident.model_dump(mode="json"))
    await redis.set(f"incident:{incident.id}", payload)
    await redis.zadd("dashboard:incidents", {incident.id: incident.created_at.timestamp()})
