# IMS Backend

FastAPI backend for the Incident Management System MVP.

## What This Phase Implements

- Async signal ingestion through a bounded in-memory queue.
- PostgreSQL source-of-truth tables for incidents and RCA records.
- MongoDB raw signal audit log with indexes for component, incident, severity, and time queries.
- Redis hot-path state for debounce windows and dashboard incident snapshots.
- Debouncing by `component_id`: many signals inside the configured window map to one incident.
- Alerting Strategy pattern for component-specific alert type and priority assignment.
- Incident read APIs.

## Local Setup Without Docker

1. Create PostgreSQL database:

   ```powershell
   createdb -U postgres ims_db
   ```

2. Start local MongoDB and Redis services using your normal Windows installation.

3. Install Python dependencies:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Check `.env` values:

   ```env
   POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/ims_db
   MONGO_URI=mongodb://localhost:27017
   MONGO_DB=ims_raw
   REDIS_URL=redis://localhost:6379/0
   ```

5. Start the API:

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
