"""
Signal routes — POST /signals, POST /signals/batch, GET /signals, GET /signals/{id}

Storage: in-memory dict for now. Will be swapped for MongoDB + Redis in next phase.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.logger import get_logger
from app.schemas.signal import (
    SignalBatchCreate,
    SignalCreate,
    SignalIngestResponse,
    SignalResponse,
    Severity,
)

router = APIRouter(prefix="/signals", tags=["Signals"])
logger = get_logger("signals")

# ── In-memory store (replaced by MongoDB in next phase) ──────────────────────
# Structure: { signal_id: SignalResponse }
_signal_store: dict[str, SignalResponse] = {}


def _get_queue(request: Request) -> asyncio.Queue:
    """Pull the shared signal queue from app state."""
    return request.app.state.signal_queue


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_signal_response(data: SignalCreate) -> SignalResponse:
    now = datetime.now(timezone.utc)
    return SignalResponse(
        id=str(uuid4()),
        component_id=data.component_id,
        component_type=data.component_type,
        severity=data.severity,
        message=data.message,
        payload=data.payload,
        timestamp=data.timestamp or now,
        incident_id=None,   # linked after debounce in worker
        received_at=now,
    )


async def _enqueue(queue: asyncio.Queue, signal: SignalResponse) -> bool:
    """Non-blocking put. Returns False if queue is full (backpressure)."""
    try:
        queue.put_nowait(signal)
        return True
    except asyncio.QueueFull:
        return False


# ── POST /signals ─────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalIngestResponse,
    summary="Ingest a single failure signal",
)
async def ingest_signal(payload: SignalCreate, request: Request):
    """
    Receive a single failure signal from any component.

    - Validated immediately (Pydantic).
    - Enqueued into the in-memory async queue for background processing.
    - Returns 202 Accepted instantly — never blocks on DB writes.
    - Returns 503 if the internal buffer is full (backpressure signal).
    """
    queue: asyncio.Queue = _get_queue(request)
    signal = _build_signal_response(payload)

    accepted = await _enqueue(queue, signal)
    if not accepted:
        logger.warning("queue_full", component_id=signal.component_id, queue_size=queue.qsize())
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Signal buffer is full — backpressure active",
                "queue_depth": queue.qsize(),
                "hint": "Reduce send rate or increase SIGNAL_QUEUE_MAXSIZE",
            },
        )

    # Mirror into in-memory store so GET endpoints work immediately
    _signal_store[signal.id] = signal

    logger.info(
        "signal_accepted",
        signal_id=signal.id,
        component_id=signal.component_id,
        severity=signal.severity,
        queue_depth=queue.qsize(),
    )

    return SignalIngestResponse(
        accepted=1,
        queued_total=queue.qsize(),
    )


# ── POST /signals/batch ────────────────────────────────────────────────────────

@router.post(
    "/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalIngestResponse,
    summary="Ingest a batch of failure signals (max 500)",
)
async def ingest_signals_batch(payload: SignalBatchCreate, request: Request):
    """
    Bulk ingestion endpoint for simulators and high-throughput producers.

    Accepts up to 500 signals per call. Signals that cannot be enqueued
    (queue full) are counted as rejected — partial success is allowed.
    """
    queue: asyncio.Queue = _get_queue(request)
    accepted = 0
    rejected = 0

    for raw in payload.signals:
        signal = _build_signal_response(raw)
        ok = await _enqueue(queue, signal)
        if ok:
            _signal_store[signal.id] = signal
            accepted += 1
        else:
            rejected += 1

    if accepted == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "All signals rejected — buffer full",
                "queue_depth": queue.qsize(),
            },
        )

    logger.info(
        "batch_accepted",
        accepted=accepted,
        rejected=rejected,
        queue_depth=queue.qsize(),
    )

    return SignalIngestResponse(
        accepted=accepted,
        rejected=rejected,
        queued_total=queue.qsize(),
        message=f"{accepted} signals accepted, {rejected} rejected (buffer full)",
    )


# ── GET /signals ──────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[SignalResponse],
    summary="List all ingested signals",
)
async def list_signals(
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    severity: Optional[Severity] = Query(default=None, description="Filter by severity"),
    component_id: Optional[str] = Query(default=None, description="Filter by component_id"),
):
    """
    Returns signals from the in-memory store (latest-first).
    Supports filtering by severity and component_id.
    """
    signals = list(_signal_store.values())

    # Apply filters
    if severity:
        signals = [s for s in signals if s.severity == severity]
    if component_id:
        signals = [s for s in signals if s.component_id == component_id.upper()]

    # Sort newest first
    signals.sort(key=lambda s: s.received_at, reverse=True)

    return signals[offset : offset + limit]


# ── GET /signals/{signal_id} ──────────────────────────────────────────────────

@router.get(
    "/{signal_id}",
    response_model=SignalResponse,
    summary="Get a specific signal by ID",
)
async def get_signal(signal_id: str):
    """Fetch a single signal by its UUID."""
    signal = _signal_store.get(signal_id)
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )
    return signal


# ── GET /signals/stats/summary ────────────────────────────────────────────────

@router.get(
    "/stats/summary",
    summary="Quick stats on ingested signals",
)
async def signal_stats():
    """Returns counts by severity and component — useful for dashboard polling."""
    signals = list(_signal_store.values())

    by_severity: dict[str, int] = {}
    by_component: dict[str, int] = {}

    for s in signals:
        by_severity[s.severity] = by_severity.get(s.severity, 0) + 1
        by_component[s.component_id] = by_component.get(s.component_id, 0) + 1

    return {
        "total": len(signals),
        "by_severity": by_severity,
        "by_component": by_component,
    }
