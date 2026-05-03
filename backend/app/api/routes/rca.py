from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.db.postgres import get_pg_pool
from app.schemas.rca import RCAResponse, RCASubmit
from app.services.rca_service import get_rca, submit_rca

router = APIRouter(prefix="/rca", tags=["RCA"])


@router.post("/{incident_id}", response_model=RCAResponse)
async def submit_incident_rca(incident_id: str, payload: RCASubmit):
    pool = await get_pg_pool()
    try:
        return await submit_rca(pool, incident_id, payload)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{incident_id}", response_model=RCAResponse)
async def get_incident_rca(incident_id: str):
    pool = await get_pg_pool()
    rca = await get_rca(pool, incident_id)
    if rca is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RCA for incident '{incident_id}' not found",
        )
    return rca
