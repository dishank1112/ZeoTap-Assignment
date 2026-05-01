from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RawSignalLog:
    id: str
    timestamp: datetime
    component_id: str
    component_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    incident_id: str
    received_at: datetime
