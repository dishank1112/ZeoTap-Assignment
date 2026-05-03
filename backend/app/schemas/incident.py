from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.signal import ComponentType, Severity


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus


class IncidentResponse(BaseModel):
    id: str
    component_id: str
    component_type: ComponentType
    severity: Severity
    priority: Priority
    status: IncidentStatus
    alert_type: str
    summary: str
    signal_count: int
    created_at: datetime
    updated_at: datetime
    start_time: datetime
    end_time: datetime | None = None
    mttr_seconds: float | None = None


class IncidentListResponse(BaseModel):
    total: int
    incidents: list[IncidentResponse]
