from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import asyncpg
import redis.asyncio as aioredis

from app.schemas.incident import IncidentResponse, IncidentStatus
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
                id, component_id, component_type, severity, priority, status, alert_type,
                summary, signal_count, created_at, updated_at, start_time
            )
            VALUES ($1, $2, $3, $4, $5, 'OPEN', $6, $7, 0, $8, $8, $9)
            RETURNING *
            """,
            incident_id,
            signal.component_id,
            signal.component_type.value,
            signal.severity.value,
            decision.priority,
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
            ORDER BY 
                CASE priority 
                    WHEN 'P0' THEN 0
                    WHEN 'P1' THEN 1
                    WHEN 'P2' THEN 2
                    ELSE 3
                END,
                created_at DESC
            LIMIT ${len(args) - 1}
            OFFSET ${len(args)}
            """,
            *args,
        )
    return int(total), [_record_to_incident(record) for record in records]


ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING},
    IncidentStatus.INVESTIGATING: {IncidentStatus.RESOLVED},
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED},
    IncidentStatus.CLOSED: set(),
}


async def transition_incident_status(
    pool: asyncpg.Pool,
    incident_id: str,
    target_status: IncidentStatus,
) -> IncidentResponse:
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                "SELECT * FROM incidents WHERE id = $1::uuid FOR UPDATE",
                incident_id,
            )
            if current is None:
                raise LookupError(f"Incident '{incident_id}' not found")

            current_status = IncidentStatus(current["status"])
            if current_status == target_status:
                return _record_to_incident(current)

            if target_status not in ALLOWED_TRANSITIONS[current_status]:
                raise ValueError(
                    f"Invalid transition: {current_status.value} -> {target_status.value}"
                )

            if target_status == IncidentStatus.CLOSED:
                has_valid_rca = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM rcas
                        WHERE incident_id = $1::uuid AND valid = TRUE
                    )
                    """,
                    incident_id,
                )
                if not has_valid_rca:
                    raise ValueError("Incident cannot be closed until a valid RCA exists")

            if target_status == IncidentStatus.RESOLVED:
                record = await conn.fetchrow(
                    """
                    UPDATE incidents
                    SET status = $2,
                        updated_at = NOW(),
                        end_time = NOW(),
                        mttr_seconds = EXTRACT(EPOCH FROM (NOW() - start_time))
                    WHERE id = $1::uuid
                    RETURNING *
                    """,
                    incident_id,
                    target_status.value,
                )
            else:
                record = await conn.fetchrow(
                    """
                    UPDATE incidents
                    SET status = $2,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    RETURNING *
                    """,
                    incident_id,
                    target_status.value,
                )
    return _record_to_incident(record)


async def cache_incident_dashboard_state(
    redis: aioredis.Redis,
    incident: IncidentResponse,
) -> None:
    payload = json.dumps(incident.model_dump(mode="json"))
    await redis.set(f"incident:{incident.id}", payload)
    await redis.zadd("dashboard:incidents", {incident.id: incident.created_at.timestamp()})
