"""PostgreSQL connection pool and schema bootstrap."""
from __future__ import annotations

import asyncpg
from asyncpg import InvalidCatalogNameError

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("db.postgres")

_pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY,
    component_id VARCHAR(128) NOT NULL,
    component_type VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    priority VARCHAR(8) NOT NULL DEFAULT 'P3',
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    alert_type VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    signal_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_time TIMESTAMPTZ,
    mttr_seconds DOUBLE PRECISION,
    CONSTRAINT incidents_status_check
        CHECK (status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED')),
    CONSTRAINT incidents_severity_check
        CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'))
);

CREATE INDEX IF NOT EXISTS idx_incidents_component_status
    ON incidents (component_id, status);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at
    ON incidents (created_at DESC);

ALTER TABLE incidents
    ADD COLUMN IF NOT EXISTS priority VARCHAR(8) NOT NULL DEFAULT 'P3';

CREATE TABLE IF NOT EXISTS rcas (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL UNIQUE REFERENCES incidents(id) ON DELETE CASCADE,
    root_cause_category VARCHAR(128) NOT NULL,
    fix_applied TEXT NOT NULL,
    prevention_steps TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_rcas_incident_id
    ON rcas (incident_id);
"""


async def create_pg_pool() -> asyncpg.Pool:
    """Create and return the asyncpg connection pool."""
    global _pool
    logger.info(
        "pg_pool_creating",
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
    )
    try:
        _pool = await _create_pool()
    except InvalidCatalogNameError:
        if settings.POSTGRES_DSN:
            raise
        logger.warning(
            "pg_database_missing_creating",
            database=settings.POSTGRES_DB,
        )
        await ensure_database_exists()
        _pool = await _create_pool()
    logger.info("pg_pool_created")
    return _pool


async def _create_pool() -> asyncpg.Pool:
    if settings.POSTGRES_DSN:
        return await asyncpg.create_pool(
            dsn=settings.POSTGRES_DSN,
            min_size=5,
            max_size=20,
            command_timeout=30,
        )
    return await asyncpg.create_pool(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        min_size=5,
        max_size=20,
        command_timeout=30,
    )


async def ensure_database_exists() -> None:
    """Create the configured database using the default maintenance database."""
    conn = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database="postgres",
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            settings.POSTGRES_DB,
        )
        if not exists:
            db_name = settings.POSTGRES_DB.replace('"', '""')
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            logger.info("pg_database_created", database=settings.POSTGRES_DB)
    finally:
        await conn.close()


async def init_pg_schema(pool: asyncpg.Pool | None = None) -> None:
    """Create the MVP source-of-truth tables if they do not exist."""
    active_pool = pool if pool is not None else await get_pg_pool()
    async with active_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("pg_schema_ready")


async def get_pg_pool() -> asyncpg.Pool:
    """Return the existing pool."""
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialised. Call create_pg_pool() first.")
    return _pool


async def close_pg_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("pg_pool_closed")
