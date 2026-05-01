"""
simulate_failures.py — Async failure signal simulator for the IMS backend.

Usage examples:
  # Send all signals from JSON once
  python scripts/simulate_failures.py

  # Send 500 signals total at a target rate of 200/sec
  python scripts/simulate_failures.py --count 500 --rate 200

  # Stress test: 5000 signals, 1000/sec, using batch endpoint
  python scripts/simulate_failures.py --count 5000 --rate 1000 --batch

  # Loop forever (Ctrl+C to stop)
  python scripts/simulate_failures.py --rate 100 --loop
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000/api/v1"
SIGNALS_FILE = Path(__file__).parent / "sample_signals.json"
DEFAULT_CONCURRENCY = 20   # parallel httpx coroutines


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_signal_templates() -> list[dict[str, Any]]:
    """Load signal templates from JSON file."""
    with open(SIGNALS_FILE, encoding="utf-8") as f:
        return json.load(f)


def pick_signal(templates: list[dict]) -> dict[str, Any]:
    """Pick a random signal template — randomise payload slightly for variety."""
    signal = random.choice(templates).copy()
    # Mutate payload so each signal looks unique
    signal["payload"] = {**signal["payload"], "sim_run_id": random.randint(1, 999_999)}
    return signal


# ── Single-signal sender ──────────────────────────────────────────────────────

async def send_one(
    client: httpx.AsyncClient,
    signal: dict,
    results: dict,
) -> None:
    try:
        resp = await client.post(f"{BASE_URL}/signals", json=signal, timeout=10.0)
        if resp.status_code == 202:
            results["ok"] += 1
        elif resp.status_code == 503:
            results["backpressure"] += 1
        else:
            results["error"] += 1
            if results["error"] <= 3:   # only print first few errors
                print(f"  [ERR] Unexpected {resp.status_code}: {resp.text[:120]}")
    except httpx.RequestError as e:
        results["connection_error"] += 1
        if results["connection_error"] <= 3:
            print(f"  [NET] Connection error: {e}")


# ── Batch sender ──────────────────────────────────────────────────────────────

async def send_batch(
    client: httpx.AsyncClient,
    signals: list[dict],
    results: dict,
) -> None:
    try:
        resp = await client.post(
            f"{BASE_URL}/signals/batch",
            json={"signals": signals},
            timeout=15.0,
        )
        if resp.status_code == 202:
            body = resp.json()
            results["ok"] += body.get("accepted", 0)
            results["backpressure"] += body.get("rejected", 0)
        elif resp.status_code == 503:
            results["backpressure"] += len(signals)
        else:
            results["error"] += len(signals)
            if results["error"] <= 3:
                print(f"  [ERR] Batch error {resp.status_code}: {resp.text[:120]}")
    except httpx.RequestError as e:
        results["connection_error"] += len(signals)
        if results["connection_error"] <= 3:
            print(f"  [NET] Connection error: {e}")


# ── Rate-controlled runner ─────────────────────────────────────────────────────

async def run_simulation(
    count: int,
    rate: int,
    batch_mode: bool,
    loop_forever: bool,
) -> None:
    templates = load_signal_templates()
    results = {"ok": 0, "backpressure": 0, "error": 0, "connection_error": 0}
    sem = asyncio.Semaphore(DEFAULT_CONCURRENCY)
    batch_size = 50  # signals per batch call

    print(f"\n{'='*60}")
    print(f"  IMS Failure Simulator")
    print(f"  Target URL  : {BASE_URL}")
    print(f"  Mode        : {'BATCH (50/req)' if batch_mode else 'SINGLE'}")
    print(f"  Target rate : {rate} signals/sec")
    print(f"  Total count : {'INFINITE (loop)' if loop_forever else count}")
    print(f"{'='*60}\n")

    # Verify server is up
    try:
        async with httpx.AsyncClient() as probe:
            r = await probe.get("http://localhost:8000/health", timeout=3.0)
            print(f"  [OK] Server healthy: {r.json()}\n")
    except Exception:
        print("  [ERROR] Cannot reach server at http://localhost:8000")
        print("     Start it with: uvicorn app.main:app --reload\n")
        sys.exit(1)

    start_time = time.perf_counter()
    sent = 0
    interval = 1.0 / rate  # seconds between signals

    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=50)
    ) as client:

        tasks: list[asyncio.Task] = []

        while loop_forever or sent < count:
            iteration_start = time.perf_counter()

            if batch_mode:
                # Compose a batch
                batch = [pick_signal(templates) for _ in range(min(batch_size, count - sent if not loop_forever else batch_size))]
                async with sem:
                    task = asyncio.create_task(send_batch(client, batch, results))
                    tasks.append(task)
                sent += len(batch)
                await asyncio.sleep(max(0, interval * len(batch) - (time.perf_counter() - iteration_start)))
            else:
                signal = pick_signal(templates)
                async with sem:
                    task = asyncio.create_task(send_one(client, signal, results))
                    tasks.append(task)
                sent += 1
                await asyncio.sleep(max(0, interval - (time.perf_counter() - iteration_start)))

            # Print progress every 100 signals
            if sent % 100 == 0:
                elapsed = time.perf_counter() - start_time
                actual_rate = sent / elapsed if elapsed > 0 else 0
                print(
                    f"  -> Sent: {sent:>6} | OK: {results['ok']:>6} | "
                    f"Backpressure: {results['backpressure']:>4} | "
                    f"Rate: {actual_rate:.0f}/sec | "
                    f"Queue: {await _get_queue_depth()}"
                )

        # Wait for all in-flight requests
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.perf_counter() - start_time
    print(f"\n{'='*60}")
    print(f"  Simulation Complete")
    print(f"  Elapsed       : {elapsed:.2f}s")
    print(f"  Signals sent  : {sent}")
    print(f"  Actual rate   : {sent/elapsed:.0f}/sec")
    print(f"  [OK]  Accepted     : {results['ok']}")
    print(f"  [--]  Backpressure : {results['backpressure']}")
    print(f"  [ERR] Errors       : {results['error']}")
    print(f"  [NET] Conn errors  : {results['connection_error']}")
    print(f"{'='*60}\n")


async def _get_queue_depth() -> str:
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get("http://localhost:8000/metrics", timeout=2.0)
            d = r.json()
            return f"{d['queue_depth']}/{d['queue_capacity']}"
    except Exception:
        return "?"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Async failure signal simulator for the IMS backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--count", type=int, default=100, help="Total signals to send (default: 100)")
    p.add_argument("--rate",  type=int, default=50,  help="Target signals/sec (default: 50)")
    p.add_argument("--batch", action="store_true",   help="Use /signals/batch endpoint (50 per req)")
    p.add_argument("--loop",  action="store_true",   help="Loop forever until Ctrl+C")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(run_simulation(args.count, args.rate, args.batch, args.loop))
    except KeyboardInterrupt:
        print("\n  Simulation interrupted by user.")
