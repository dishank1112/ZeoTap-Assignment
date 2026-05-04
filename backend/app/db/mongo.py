from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("db.mongo")

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def create_mongo_client() -> AsyncIOMotorDatabase:
    """Create Motor client and return the database handle."""
    global _client, _db
    logger.info("mongo_connecting", uri=settings.MONGO_URI, db=settings.MONGO_DB)
    _client = AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=50,
        minPoolSize=5,
        serverSelectionTimeoutMS=5000,
    )
    _db = _client[settings.MONGO_DB]
    try:
        await _client.admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        raise RuntimeError(
            "MongoDB is not reachable at MONGO_URI="
            f"{settings.MONGO_URI}. Start MongoDB locally or update backend/.env."
        ) from exc
    logger.info("mongo_connected")
    return _db


async def init_mongo_indexes(db: AsyncIOMotorDatabase | None = None) -> None:
    """Create query indexes for the raw signal audit log."""
    active_db = db if db is not None else await get_mongo_db()
    raw = active_db.raw_signals
    await raw.create_index([("component_id", 1), ("timestamp", -1)])
    await raw.create_index([("incident_id", 1), ("timestamp", -1)])
    await raw.create_index([("severity", 1), ("received_at", -1)])
    await raw.create_index([("received_at", -1)])
    logger.info("mongo_indexes_ready", collection="raw_signals")


async def get_mongo_db() -> AsyncIOMotorDatabase:
    """Return the existing database handle."""
    if _db is None:
        raise RuntimeError("MongoDB client not initialised. Call create_mongo_client() first.")
    return _db


async def close_mongo_client() -> None:
    """Close the Motor client."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("mongo_closed")
