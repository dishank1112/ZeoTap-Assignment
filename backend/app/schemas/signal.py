from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # P0 – RDBMS, MCP Host
    HIGH     = "HIGH"       # P1 – API, Async Queue
    MEDIUM   = "MEDIUM"     # P2 – Cache, NoSQL
    LOW      = "LOW"        # P3 – informational


class ComponentType(str, Enum):
    RDBMS          = "RDBMS"
    MCP_HOST       = "MCP_HOST"
    API            = "API"
    ASYNC_QUEUE    = "ASYNC_QUEUE"
    CACHE          = "CACHE"
    NOSQL          = "NOSQL"
    UNKNOWN        = "UNKNOWN"


# ── Inbound ───────────────────────────────────────────────────────────────────

class SignalCreate(BaseModel):
    """Schema for a signal sent by external producers / simulators."""

    component_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        examples=["CACHE_CLUSTER_01", "POSTGRES_PRIMARY", "API_GATEWAY"],
        description="Unique identifier of the failing component",
    )
    component_type: ComponentType = Field(
        default=ComponentType.UNKNOWN,
        description="Category of the component",
    )
    severity: Severity = Field(
        ...,
        description="Severity level of the signal",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Human-readable error message",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (stack trace, metrics, etc.)",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Signal timestamp (ISO-8601). Defaults to server time if omitted.",
    )

    @field_validator("component_id")
    @classmethod
    def strip_component_id(cls, v: str) -> str:
        return v.strip().upper()


class SignalBatchCreate(BaseModel):
    """Batch ingestion — up to 500 signals per request."""

    signals: list[SignalCreate] = Field(..., min_length=1, max_length=500)


# ── Outbound ──────────────────────────────────────────────────────────────────

class SignalResponse(BaseModel):
    """Signal returned from GET endpoints."""

    id: str
    component_id: str
    component_type: ComponentType
    severity: Severity
    message: str
    payload: dict[str, Any]
    timestamp: datetime
    incident_id: Optional[str] = None
    received_at: datetime


class SignalIngestResponse(BaseModel):
    """Immediate acknowledgement after POST /signals."""

    accepted: int = Field(description="Number of signals accepted into queue")
    rejected: int = Field(default=0, description="Signals dropped (queue full)")
    queued_total: int = Field(description="Current queue depth after this batch")
    message: str = "Signals accepted for processing"
