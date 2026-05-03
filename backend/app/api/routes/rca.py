from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, status

from app.core.logger import get_logger
from app.db.postgres import get_pg_pool
from app.schemas.rca import RCAResponse, RCASubmit
from app.services.rca_service import get_rca, submit_rca

router = APIRouter(prefix="/rca", tags=["RCA"])
logger = get_logger("rca")


@router.post("/{incident_id}", response_model=RCAResponse)
async def submit_incident_rca(incident_id: UUID, payload: RCASubmit):
    pool = await get_pg_pool()
    try:
        return await submit_rca(pool, str(incident_id), payload)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except asyncpg.PostgresError as exc:
        logger.error("rca_submit_failed", incident_id=str(incident_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RCA store is temporarily unavailable",
        ) from exc


@router.get("/{incident_id}", response_model=RCAResponse)
async def get_incident_rca(incident_id: UUID):
    pool = await get_pg_pool()
    try:
        rca = await get_rca(pool, str(incident_id))
    except asyncpg.PostgresError as exc:
        logger.error("rca_get_failed", incident_id=str(incident_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RCA store is temporarily unavailable",
        ) from exc
    if rca is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RCA for incident '{str(incident_id)}' not found",
        )
    return rca
