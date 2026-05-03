from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass

from app.schemas.signal import SignalResponse


@dataclass(frozen=True)
class EnqueueResult:
    accepted: bool
    shard_id: int
    shard_depth: int
    total_depth: int


class SignalLoadBalancer:
    """Component-affinity queue sharder for ingestion workers."""

    def __init__(self, *, shard_count: int, total_capacity: int) -> None:
        self.shard_count = max(1, shard_count)
        self.total_capacity = max(self.shard_count, total_capacity)
        self.shard_capacity = max(1, math.ceil(self.total_capacity / self.shard_count))
        self.queues: list[asyncio.Queue[SignalResponse]] = [
            asyncio.Queue(maxsize=self.shard_capacity)
            for _ in range(self.shard_count)
        ]

    def shard_for_component(self, component_id: str) -> int:
        digest = hashlib.blake2b(component_id.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(digest, byteorder="big") % self.shard_count

    def enqueue(self, signal: SignalResponse) -> EnqueueResult:
        shard_id = self.shard_for_component(signal.component_id)
        queue = self.queues[shard_id]
        try:
            queue.put_nowait(signal)
            accepted = True
        except asyncio.QueueFull:
            accepted = False

        return EnqueueResult(
            accepted=accepted,
            shard_id=shard_id,
            shard_depth=queue.qsize(),
            total_depth=self.total_depth,
        )

    @property
    def total_depth(self) -> int:
        return sum(queue.qsize() for queue in self.queues)

    @property
    def total_maxsize(self) -> int:
        return sum(queue.maxsize for queue in self.queues)

    def shard_stats(self) -> list[dict[str, int | float]]:
        return [
            {
                "shard_id": shard_id,
                "queue_depth": queue.qsize(),
                "queue_capacity": queue.maxsize,
                "queue_utilization_pct": round(queue.qsize() / queue.maxsize * 100, 2),
            }
            for shard_id, queue in enumerate(self.queues)
        ]

    async def join(self) -> None:
        await asyncio.gather(*(queue.join() for queue in self.queues))
