from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RCASubmit(BaseModel):
    root_cause_category: str = Field(..., min_length=1, max_length=128)
    fix_applied: str = Field(..., min_length=1, max_length=4000)
    prevention_steps: str = Field(..., min_length=1, max_length=4000)

    @field_validator("root_cause_category", "fix_applied", "prevention_steps", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be blank")
        return stripped


class RCAResponse(BaseModel):
    id: str
    incident_id: str
    root_cause_category: str
    fix_applied: str
    prevention_steps: str
    submitted_at: datetime
    valid: bool
