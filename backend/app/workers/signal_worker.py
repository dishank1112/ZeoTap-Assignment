from __future__ import annotations

import asyncio

from app.core.logger import get_logger
from app.schemas.signal import SignalResponse
from app.services.ingestion_service import IngestionService

logger = get_logger("worker.signal")


async def signal_worker(
    queue: asyncio.Queue[SignalResponse],
    worker_id: int,
    ingestion: IngestionService,
) -> None:
    logger.info("worker_started", worker_id=worker_id)
    while True:
        signal: SignalResponse | None = None
        try:
            signal = await queue.get()
            await ingestion.process_signal(signal)
        except asyncio.CancelledError:
            logger.info("worker_stopped", worker_id=worker_id)
            break
        except Exception as exc:
            logger.error(
                "worker_error",
                worker_id=worker_id,
                signal_id=getattr(signal, "id", None),
                error=str(exc),
            )
        finally:
            if signal is not None:
                queue.task_done()
