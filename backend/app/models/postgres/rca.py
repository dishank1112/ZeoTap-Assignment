from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RCARecord:
    id: str
    incident_id: str
    root_cause_category: str
    fix_applied: str
    prevention_steps: str
    submitted_at: datetime
    valid: bool
