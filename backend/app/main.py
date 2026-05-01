"""IMS FastAPI application entry point."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.logger import get_logger, setup_logger
from app.db.mongo import close_mongo_client, create_mongo_client, init_mongo_indexes
from app.db.postgres import close_pg_pool, create_pg_pool, init_pg_schema
from app.db.redis import close_redis_client, create_redis_client
from app.services.ingestion_service import IngestionService
from app.workers.signal_worker import signal_worker

setup_logger()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", app=settings.APP_NAME, version=settings.APP_VERSION)

    postgres = await create_pg_pool()
    await init_pg_schema(postgres)
    mongo = await create_mongo_client()
    await init_mongo_indexes(mongo)
    redis = await create_redis_client()

    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.SIGNAL_QUEUE_MAXSIZE)
    app.state.signal_queue = queue
    app.state.ingestion_service = IngestionService(
        mongo=mongo,
        postgres=postgres,
        redis=redis,
    )

    workers = [
        asyncio.create_task(signal_worker(queue, i, app.state.ingestion_service))
        for i in range(settings.SIGNAL_WORKER_CONCURRENCY)
    ]
    app.state.workers = workers
    logger.info("workers_started", count=settings.SIGNAL_WORKER_CONCURRENCY)

    try:
        yield
    finally:
        logger.info("shutdown_initiated", pending_signals=queue.qsize())
        try:
            await asyncio.wait_for(queue.join(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("drain_timeout", dropped=queue.qsize())

        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        await close_redis_client()
        await close_mongo_client()
        await close_pg_pool()
        logger.info("shutdown_complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Incident Management System that ingests distributed failure signals, "
        "groups them into incidents, and drives an RCA workflow."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


@app.get("/health", tags=["Health"])
async def health_live():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health/ready", tags=["Health"])
async def health_ready(request: Request):
    queue: asyncio.Queue = request.app.state.signal_queue
    return {
        "status": "ready",
        "queue_depth": queue.qsize(),
        "queue_max": settings.SIGNAL_QUEUE_MAXSIZE,
        "workers": settings.SIGNAL_WORKER_CONCURRENCY,
    }


@app.get("/metrics", tags=["Health"])
async def metrics(request: Request):
    queue: asyncio.Queue = request.app.state.signal_queue
    return {
        "queue_depth": queue.qsize(),
        "queue_capacity": settings.SIGNAL_QUEUE_MAXSIZE,
        "queue_utilization_pct": round(
            queue.qsize() / settings.SIGNAL_QUEUE_MAXSIZE * 100,
            2,
        ),
        "active_workers": settings.SIGNAL_WORKER_CONCURRENCY,
    }


app.include_router(api_router, prefix="/api/v1")
