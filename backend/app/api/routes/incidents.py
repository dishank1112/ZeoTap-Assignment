from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.db.postgres import get_pg_pool
from app.schemas.incident import IncidentListResponse, IncidentResponse, IncidentStatus
from app.services.incident_service import get_incident, list_incidents

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
