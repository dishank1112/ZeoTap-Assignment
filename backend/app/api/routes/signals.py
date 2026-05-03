"""Signal ingestion and raw-log lookup routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.logger import get_logger
from app.core.rate_limiter import RedisRateLimiter
from app.db.mongo import get_mongo_db
from app.schemas.signal import (
    ComponentType,
    Severity,
    SignalBatchCreate,
    SignalCreate,
    SignalIngestResponse,
    SignalResponse,
)
from app.services.load_balancer import SignalLoadBalancer

router = APIRouter(prefix="/signals", tags=["Signals"])
logger = get_logger("signals")


def _get_load_balancer(request: Request) -> SignalLoadBalancer:
    return request.app.state.signal_load_balancer


def _get_rate_limiter(request: Request) -> RedisRateLimiter:
    return request.app.state.rate_limiter


def _client_id(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


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


async def _enforce_rate_limit(request: Request, amount: int) -> None:
    limiter = _get_rate_limiter(request)
    result = await limiter.consume(_client_id(request), amount=amount)
    if result.allowed:
        return

    logger.warning(
        "rate_limit_exceeded",
        scope=result.scope,
        limit=result.limit,
        used=result.used,
        amount=amount,
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "Rate limit exceeded",
            "scope": result.scope,
            "limit": result.limit,
            "used": result.used,
            "retry_after_seconds": result.reset_after_seconds,
        },
        headers={"Retry-After": str(result.reset_after_seconds)},
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalIngestResponse,
    summary="Ingest a single failure signal",
)
async def ingest_signal(payload: SignalCreate, request: Request):
    await _enforce_rate_limit(request, amount=1)
    load_balancer = _get_load_balancer(request)
    signal = _build_signal_response(payload)

    result = load_balancer.enqueue(signal)
    if not result.accepted:
        logger.warning(
            "queue_full",
            component_id=signal.component_id,
            shard_id=result.shard_id,
            queue_size=result.shard_depth,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Signal buffer is full; backpressure active",
                "shard_id": result.shard_id,
                "shard_depth": result.shard_depth,
                "queue_depth": result.total_depth,
                "hint": "Reduce send rate or increase SIGNAL_QUEUE_MAXSIZE",
            },
        )

    logger.info(
        "signal_accepted",
        signal_id=signal.id,
        component_id=signal.component_id,
        severity=signal.severity.value,
        shard_id=result.shard_id,
        queue_depth=result.total_depth,
    )
    return SignalIngestResponse(accepted=1, queued_total=result.total_depth)


@router.post(
    "/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalIngestResponse,
    summary="Ingest a batch of failure signals",
)
async def ingest_signals_batch(payload: SignalBatchCreate, request: Request):
    await _enforce_rate_limit(request, amount=len(payload.signals))
    load_balancer = _get_load_balancer(request)
    accepted = 0
    rejected = 0
    last_total_depth = load_balancer.total_depth

    for raw in payload.signals:
        signal = _build_signal_response(raw)
        result = load_balancer.enqueue(signal)
        last_total_depth = result.total_depth
        if result.accepted:
            accepted += 1
        else:
            rejected += 1

    if accepted == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "All signals rejected; buffer full",
                "queue_depth": load_balancer.total_depth,
            },
        )

    logger.info(
        "batch_accepted",
        accepted=accepted,
        rejected=rejected,
        queue_depth=last_total_depth,
    )
    return SignalIngestResponse(
        accepted=accepted,
        rejected=rejected,
        queued_total=last_total_depth,
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
