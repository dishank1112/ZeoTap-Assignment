from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.db.postgres import get_pg_pool
from app.db.redis import get_redis
from app.schemas.incident import (
    IncidentListResponse,
    IncidentResponse,
    IncidentStatus,
    IncidentStatusUpdate,
)
from app.services.incident_service import (
    cache_incident_dashboard_state,
    get_incident,
    list_incidents,
    transition_incident_status,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.get("", response_model=IncidentListResponse)
async def list_incident_work_items(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    component_id: Optional[str] = Query(default=None),
    status_filter: Optional[IncidentStatus] = Query(default=None, alias="status"),
):
    pool = await get_pg_pool()
    total, incidents = await list_incidents(
        pool,
        limit=limit,
        offset=offset,
        component_id=component_id,
        status=status_filter.value if status_filter else None,
    )
    return IncidentListResponse(total=total, incidents=incidents)


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident_work_item(incident_id: str):
    pool = await get_pg_pool()
    incident = await get_incident(pool, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    return incident


@router.patch("/{incident_id}/status", response_model=IncidentResponse)
async def update_incident_status(incident_id: str, payload: IncidentStatusUpdate):
    pool = await get_pg_pool()
    try:
        incident = await transition_incident_status(pool, incident_id, payload.status)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    redis = await get_redis()
    await cache_incident_dashboard_state(redis, incident)
    return incident
