"""Signal ingestion and raw-log lookup routes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.logger import get_logger
from app.db.mongo import get_mongo_db
from app.schemas.signal import (
    ComponentType,
    Severity,
    SignalBatchCreate,
    SignalCreate,
    SignalIngestResponse,
    SignalResponse,
)

router = APIRouter(prefix="/signals", tags=["Signals"])
logger = get_logger("signals")


def _get_queue(request: Request) -> asyncio.Queue:
    return request.app.state.signal_queue


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
        incident_id=None,
        received_at=now,
    )


def _document_to_signal(doc: dict[str, Any]) -> SignalResponse:
    return SignalResponse(
        id=str(doc["_id"]),
        component_id=doc["component_id"],
        component_type=ComponentType(doc["component_type"]),
        severity=Severity(doc["severity"]),
        message=doc["message"],
        payload=doc.get("payload", {}),
        timestamp=doc["timestamp"],
        incident_id=doc.get("incident_id"),
        received_at=doc["received_at"],
    )


async def _enqueue(queue: asyncio.Queue, signal: SignalResponse) -> bool:
    try:
        queue.put_nowait(signal)
        return True
    except asyncio.QueueFull:
        return False


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalIngestResponse,
    summary="Ingest a single failure signal",
)
async def ingest_signal(payload: SignalCreate, request: Request):
    queue = _get_queue(request)
    signal = _build_signal_response(payload)

    accepted = await _enqueue(queue, signal)
    if not accepted:
        logger.warning("queue_full", component_id=signal.component_id, queue_size=queue.qsize())
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Signal buffer is full; backpressure active",
                "queue_depth": queue.qsize(),
                "hint": "Reduce send rate or increase SIGNAL_QUEUE_MAXSIZE",
            },
        )

    logger.info(
        "signal_accepted",
        signal_id=signal.id,
        component_id=signal.component_id,
        severity=signal.severity.value,
        queue_depth=queue.qsize(),
    )
    return SignalIngestResponse(accepted=1, queued_total=queue.qsize())


@router.post(
    "/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalIngestResponse,
    summary="Ingest a batch of failure signals",
)
async def ingest_signals_batch(payload: SignalBatchCreate, request: Request):
    queue = _get_queue(request)
    accepted = 0
    rejected = 0

    for raw in payload.signals:
        signal = _build_signal_response(raw)
        ok = await _enqueue(queue, signal)
        if ok:
            accepted += 1
        else:
            rejected += 1

    if accepted == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "All signals rejected; buffer full",
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
        message=f"{accepted} signals accepted, {rejected} rejected",
    )


@router.get("", response_model=list[SignalResponse], summary="List raw signal logs")
async def list_signals(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    severity: Optional[Severity] = Query(default=None),
    component_id: Optional[str] = Query(default=None),
    incident_id: Optional[str] = Query(default=None),
):
    mongo = await get_mongo_db()
    filters: dict[str, Any] = {}
    if severity:
        filters["severity"] = severity.value
    if component_id:
        filters["component_id"] = component_id.upper()
    if incident_id:
        filters["incident_id"] = incident_id

    cursor = (
        mongo.raw_signals.find(filters)
        .sort("received_at", -1)
        .skip(offset)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [_document_to_signal(doc) for doc in docs]


@router.get("/stats/summary", summary="Quick stats on persisted raw signals")
async def signal_stats():
    mongo = await get_mongo_db()
    by_severity_cursor = mongo.raw_signals.aggregate(
        [{"$group": {"_id": "$severity", "count": {"$sum": 1}}}]
    )
    by_component_cursor = mongo.raw_signals.aggregate(
        [{"$group": {"_id": "$component_id", "count": {"$sum": 1}}}]
    )
    by_severity = {
        row["_id"]: row["count"]
        for row in await by_severity_cursor.to_list(length=None)
    }
    by_component = {
        row["_id"]: row["count"]
        for row in await by_component_cursor.to_list(length=None)
    }
    return {
        "total": sum(by_severity.values()),
        "by_severity": by_severity,
        "by_component": by_component,
    }


@router.get("/{signal_id}", response_model=SignalResponse, summary="Get raw signal by ID")
async def get_signal(signal_id: str):
    mongo = await get_mongo_db()
    doc = await mongo.raw_signals.find_one({"_id": signal_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )
    return _document_to_signal(doc)
