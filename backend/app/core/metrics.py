from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from app.core.logger import get_logger

logger = get_logger("metrics")


@dataclass
class ThroughputSnapshot:
    """Throughput measurement snapshot."""
    timestamp: float
    signals_processed: int


class MetricsCollector:
    """Tracks signal processing throughput over sliding windows."""

    def __init__(self, window_seconds: int = 5) -> None:
        self.window_seconds = window_seconds
        self.total_processed = 0
        self.snapshots: deque[ThroughputSnapshot] = deque()
        self._lock = asyncio.Lock()

    async def record_processed(self, count: int = 1) -> None:
        """Record signals processed."""
        async with self._lock:
            self.total_processed += count

    async def _prune_snapshots(self) -> None:
        """Remove snapshots outside the window."""
        now = time.time()
        while self.snapshots and self.snapshots[0].timestamp < now - self.window_seconds:
            self.snapshots.popleft()

    async def get_throughput(self) -> float:
        """Get current throughput (signals/sec over the window)."""
        async with self._lock:
            await self._prune_snapshots()
            if not self.snapshots:
                return 0.0
            
            total = sum(s.signals_processed for s in self.snapshots)
            elapsed = time.time() - self.snapshots[0].timestamp
            if elapsed == 0:
                return 0.0
            return total / elapsed

    async def _snapshot(self) -> None:
        """Take a snapshot of current processing."""
        async with self._lock:
            now = time.time()
            self.snapshots.append(ThroughputSnapshot(
                timestamp=now,
                signals_processed=self.total_processed,
            ))
            await self._prune_snapshots()

    async def print_metrics_loop(self) -> None:
        """Background task to print metrics every window_seconds."""
        logger.info(
            "metrics_loop_started",
            window_seconds=self.window_seconds,
        )
        try:
            while True:
                await asyncio.sleep(self.window_seconds)
                await self._snapshot()
                throughput = await self.get_throughput()
                logger.info(
                    "throughput",
                    signals_per_sec=round(throughput, 2),
                    total_processed=self.total_processed,
                )
        except asyncio.CancelledError:
            logger.info("metrics_loop_stopped")
            raise
