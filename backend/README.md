# IMS Backend

FastAPI backend for the Incident Management System MVP.

## What This Phase Implements

- Async signal ingestion through a bounded in-memory queue.
- PostgreSQL source-of-truth tables for incidents and RCA records.
- MongoDB raw signal audit log with indexes for component, incident, severity, and time queries.
- Redis hot-path state for debounce windows and dashboard incident snapshots.
- Redis-backed fixed-window rate limiting for global and per-IP ingestion limits.
- Component-affinity load balancing across shard queues for ingestion workers.
- Debouncing by `component_id`: many signals inside the configured window map to one incident.
- Alerting Strategy pattern for component-specific alert type and priority assignment.
- Incident read APIs.

## Local Setup Without Docker

1. PostgreSQL:

   ```powershell
   # The app can create ims_db automatically if the user has CREATEDB permission.
   # Otherwise create it once:
   createdb -U postgres ims_db
   ```

2. Start local MongoDB:

   ```powershell
   Get-Service MongoDB
   Start-Service MongoDB
   ```

   If `MongoDB` is not a service yet, install MongoDB Community Server for Windows
   and enable the Windows service option, or set `MONGO_URI` to a reachable MongoDB
   instance.

3. Start local Redis:

   ```powershell
   redis-server --version
   redis-server
   ```

   If `redis-server` is not available on Windows, install Redis through Memurai,
   WSL, or another local Redis-compatible service, then keep `REDIS_URL` pointed at
   that service.

4. Install Python dependencies:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

5. Check `.env` values:

   ```env
   POSTGRES_DSN=
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=ims_db
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=<your-password>
   MONGO_URI=mongodb://localhost:27017
   MONGO_DB=ims_raw
   REDIS_URL=redis://localhost:6379/0
   SIGNAL_QUEUE_MAXSIZE=50000
   SIGNAL_WORKER_CONCURRENCY=20
   LOAD_BALANCER_SHARDS=4
   RATE_LIMIT_GLOBAL=10000
   RATE_LIMIT_PER_IP=1000
   RATE_LIMIT_WINDOW_SECONDS=10
   ```

6. Start the API:

   ```powershell
   uvicorn app.main:app --reload
   ```

The app initializes PostgreSQL tables and MongoDB indexes on startup.

## Useful Endpoints

- `GET /health`
- `GET /health/ready`
- `GET /metrics`
- `POST /api/v1/signals`
- `POST /api/v1/signals/batch`
- `GET /api/v1/signals`
- `GET /api/v1/signals?incident_id=<incident-id>`
- `GET /api/v1/signals/stats/summary`
- `GET /api/v1/incidents`
- `GET /api/v1/incidents/{incident_id}`

## Debounce Proof

Run the API, then from the repository root:

```powershell
python scripts\simulate_failures.py --count 1000 --rate 100 --batch
```

Signals with the same `component_id` inside `DEBOUNCE_WINDOW_SECONDS` should create one PostgreSQL incident while every raw signal is stored in MongoDB with the same `incident_id`.

## Rate Limiter And Load Balancer

- `RATE_LIMIT_GLOBAL` limits total accepted signals per `RATE_LIMIT_WINDOW_SECONDS`.
- `RATE_LIMIT_PER_IP` limits accepted signals from one client IP per window.
- Batch ingestion consumes one token per signal, not one token per request.
- `LOAD_BALANCER_SHARDS` creates component-affinity queues. The same `component_id`
  always maps to the same shard, which keeps burst grouping predictable while
  still distributing unrelated components across workers.
- `GET /metrics` returns total queue depth plus per-shard queue depth and capacity.
