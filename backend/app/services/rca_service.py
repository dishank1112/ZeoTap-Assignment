from __future__ import annotations

from uuid import uuid4

import asyncpg

from app.schemas.rca import RCAResponse, RCASubmit


def _record_to_rca(record: asyncpg.Record) -> RCAResponse:
    data = dict(record)
    data["id"] = str(data["id"])
    data["incident_id"] = str(data["incident_id"])
    return RCAResponse(**data)


def _is_valid_rca(payload: RCASubmit) -> bool:
    return all(
        [
            bool(payload.root_cause_category.strip()),
            bool(payload.fix_applied.strip()),
            bool(payload.prevention_steps.strip()),
        ]
    )


async def submit_rca(
    pool: asyncpg.Pool,
    incident_id: str,
    payload: RCASubmit,
) -> RCAResponse:
    async with pool.acquire() as conn:
        incident_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM incidents WHERE id = $1::uuid)",
            incident_id,
        )
        if not incident_exists:
            raise LookupError(f"Incident '{incident_id}' not found")

        record = await conn.fetchrow(
            """
            INSERT INTO rcas (
                id, incident_id, root_cause_category, fix_applied,
                prevention_steps, submitted_at, valid
            )
            VALUES ($1, $2::uuid, $3, $4, $5, NOW(), $6)
            ON CONFLICT (incident_id) DO UPDATE
            SET root_cause_category = EXCLUDED.root_cause_category,
                fix_applied = EXCLUDED.fix_applied,
                prevention_steps = EXCLUDED.prevention_steps,
                submitted_at = NOW(),
                valid = EXCLUDED.valid
            RETURNING *
            """,
            uuid4(),
            incident_id,
            payload.root_cause_category,
            payload.fix_applied,
            payload.prevention_steps,
            _is_valid_rca(payload),
        )
    return _record_to_rca(record)


async def get_rca(pool: asyncpg.Pool, incident_id: str) -> RCAResponse | None:
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT * FROM rcas WHERE incident_id = $1::uuid",
            incident_id,
        )
    return _record_to_rca(record) if record else None
