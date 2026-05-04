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
from app.core.metrics import MetricsCollector
from app.core.rate_limiter import RedisRateLimiter
from app.db.mongo import close_mongo_client, create_mongo_client, init_mongo_indexes
from app.db.postgres import close_pg_pool, create_pg_pool, init_pg_schema
from app.db.redis import close_redis_client, create_redis_client
from app.services.ingestion_service import IngestionService
from app.services.load_balancer import SignalLoadBalancer
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

    load_balancer = SignalLoadBalancer(
        shard_count=settings.LOAD_BALANCER_SHARDS,
        total_capacity=settings.SIGNAL_QUEUE_MAXSIZE,
    )
    app.state.signal_load_balancer = load_balancer
    app.state.rate_limiter = RedisRateLimiter(redis)
    app.state.metrics_collector = MetricsCollector(window_seconds=5)
    app.state.ingestion_service = IngestionService(
        mongo=mongo,
        postgres=postgres,
        redis=redis,
        metrics=app.state.metrics_collector,
    )

    metrics_task = asyncio.create_task(
        app.state.metrics_collector.print_metrics_loop()
    )
    app.state.metrics_task = metrics_task

    workers = []
    worker_id = 0
    worker_count = max(settings.SIGNAL_WORKER_CONCURRENCY, load_balancer.shard_count)
    base_workers = worker_count // load_balancer.shard_count
    extra_workers = worker_count % load_balancer.shard_count
    for shard_id, queue in enumerate(load_balancer.queues):
        shard_workers = base_workers + (1 if shard_id < extra_workers else 0)
        for _ in range(shard_workers):
            workers.append(
                asyncio.create_task(
                    signal_worker(queue, worker_id, app.state.ingestion_service)
                )
            )
            worker_id += 1
    app.state.workers = workers
    logger.info(
        "workers_started",
        count=len(workers),
        shards=load_balancer.shard_count,
        shard_capacity=load_balancer.shard_capacity,
    )

    try:
        yield
    finally:
        logger.info("shutdown_initiated", pending_signals=load_balancer.total_depth)
        try:
            await asyncio.wait_for(load_balancer.join(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("drain_timeout", dropped=load_balancer.total_depth)

        app.state.metrics_task.cancel()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, app.state.metrics_task, return_exceptions=True)

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
        content={"error": "Internal server error", "detail": "Unexpected server error"},
    )


@app.get("/health", tags=["Health"])
async def health_live():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health/ready", tags=["Health"])
async def health_ready(request: Request):
    load_balancer: SignalLoadBalancer = request.app.state.signal_load_balancer
    return {
        "status": "ready",
        "queue_depth": load_balancer.total_depth,
        "queue_max": load_balancer.total_maxsize,
        "workers": len(request.app.state.workers),
        "shards": load_balancer.shard_count,
    }


@app.get("/metrics", tags=["Health"])
async def metrics(request: Request):
    load_balancer: SignalLoadBalancer = request.app.state.signal_load_balancer
    return {
        "queue_depth": load_balancer.total_depth,
        "queue_capacity": load_balancer.total_maxsize,
        "queue_utilization_pct": round(
            load_balancer.total_depth / load_balancer.total_maxsize * 100,
            2,
        ),
        "active_workers": len(request.app.state.workers),
        "load_balancer_shards": load_balancer.shard_count,
        "shards": load_balancer.shard_stats(),
        "rate_limit_window_seconds": settings.RATE_LIMIT_WINDOW_SECONDS,
        "rate_limit_global": settings.RATE_LIMIT_GLOBAL,
        "rate_limit_per_ip": settings.RATE_LIMIT_PER_IP,
    }


app.include_router(api_router, prefix="/api/v1")
