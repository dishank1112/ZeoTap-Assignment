"""
IMS — Incident Management System
FastAPI application entry point.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import orjson
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.logger import get_logger, setup_logger

setup_logger()
logger = get_logger("main")


# ── Background Worker ─────────────────────────────────────────────────────────

async def _signal_worker(queue: asyncio.Queue, worker_id: int) -> None:
    """
    Drains the signal queue. Currently just logs — DB writes added next phase.
    Multiple coroutines of this run concurrently for throughput.
    """
    logger.info("worker_started", worker_id=worker_id)
    while True:
        try:
            signal = await queue.get()
            # ── Phase 1: just log it ──────────────────────────────────────
            logger.debug(
                "signal_processed",
                worker_id=worker_id,
                signal_id=signal.id,
                component_id=signal.component_id,
                severity=signal.severity,
                queue_remaining=queue.qsize(),
            )
            # TODO Phase 2: write to MongoDB, debounce → Postgres, cache Redis
            queue.task_done()
        except asyncio.CancelledError:
            logger.info("worker_stopped", worker_id=worker_id)
            break
        except Exception as exc:
            logger.error("worker_error", worker_id=worker_id, error=str(exc))
            queue.task_done()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    logger.info("startup", app=settings.APP_NAME, version=settings.APP_VERSION)

    # Create bounded async queue (backpressure if full)
    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.SIGNAL_QUEUE_MAXSIZE)
    app.state.signal_queue = queue

    # Spin up N concurrent worker coroutines
    workers = [
        asyncio.create_task(_signal_worker(queue, i))
        for i in range(settings.SIGNAL_WORKER_CONCURRENCY)
    ]
    app.state.workers = workers
    logger.info("workers_started", count=settings.SIGNAL_WORKER_CONCURRENCY)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("shutdown_initiated", pending_signals=queue.qsize())

    # Wait for queue to drain (max 10 seconds)
    try:
        await asyncio.wait_for(queue.join(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("drain_timeout", dropped=queue.qsize())

    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    logger.info("shutdown_complete")


# ── App Factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Incident Management System — ingests failure signals from distributed "
        "components, groups them into incidents, and drives a workflow to closure."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — open for dev; restrict origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Custom Exception Handlers ─────────────────────────────────────────────────

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Health Endpoints ──────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_live():
    """Liveness check — is the process up?"""
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health/ready", tags=["Health"])
async def health_ready(request: Request):
    """Readiness check — is the queue operational?"""
    queue: asyncio.Queue = request.app.state.signal_queue
    return {
        "status": "ready",
        "queue_depth": queue.qsize(),
        "queue_max": settings.SIGNAL_QUEUE_MAXSIZE,
        "workers": settings.SIGNAL_WORKER_CONCURRENCY,
    }


@app.get("/metrics", tags=["Health"])
async def metrics(request: Request):
    """Live metrics — queue depth and worker count."""
    queue: asyncio.Queue = request.app.state.signal_queue
    return {
        "queue_depth": queue.qsize(),
        "queue_capacity": settings.SIGNAL_QUEUE_MAXSIZE,
        "queue_utilization_pct": round(queue.qsize() / settings.SIGNAL_QUEUE_MAXSIZE * 100, 2),
        "active_workers": settings.SIGNAL_WORKER_CONCURRENCY,
    }


# ── Mount API Router ──────────────────────────────────────────────────────────

app.include_router(api_router, prefix="/api/v1")
