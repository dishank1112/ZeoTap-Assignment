from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IncidentRecord:
    id: str
    component_id: str
    component_type: str
    severity: str
    priority: str
    status: str
    alert_type: str
    summary: str
    signal_count: int
    created_at: datetime
    updated_at: datetime
    start_time: datetime
    end_time: datetime | None
    mttr_seconds: float | None
