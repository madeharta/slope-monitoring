# Running the Variant-A pipeline + dashboard

Full stack: fleet → MQTT → db-writer → TimescaleDB → FastAPI (registry/SSE) →
React dashboard.

## One-time setup

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt -r consumers/api/requirements.txt
cd frontend && npm install && cd ..
```

## Start (each in its own terminal, from the repo root)

```bash
# 1. infrastructure (MQTT broker + TimescaleDB)
docker compose -f infra/variant-a/docker-compose.yml up -d

# env used by the Python processes
export MQTT_HOST=localhost MQTT_PORT=1883 \
       DB_HOST=localhost DB_PORT=5432 DB_NAME=magris DB_USER=magris DB_PASSWORD=magris_dev

# 2. consumer: MQTT -> TimescaleDB (batched)
python consumers/db-writer/writer.py

# 3. load generator: 6 slopes x 4 sensors, physical model
python loadgen/fleet.py

# 4. dashboard API (serves the built frontend at http://127.0.0.1:8000)
python consumers/api/main.py
```

## The frontend

- **Dev (hot reload):** `cd frontend && npm run dev` → http://127.0.0.1:5173
  (Vite proxies `/api` to the API on :8000).
- **Production (single service):** `cd frontend && npm run build`, then the API
  serves `frontend/dist/` at **http://127.0.0.1:8000**.

## Endpoints

- `GET /api/overview` — per-slope status/action/key reading, health, counts
- `GET /api/sites/{site_id}?hours=24` — combined series, cross-section, quality
- `GET /api/quantities` — distinct quantities (registry)
- `GET /api/stream` — single SSE stream (all devices, routed client-side)

## Notes

- Status thresholds live in `consumers/api/config.py` (mechanism, not tuning —
  context.md §10.7). Everything else in the UI derives from the data at runtime.
- The map uses Leaflet + CARTO `dark_matter` tiles (needs internet).
- To refresh data to zero: `docker exec magris-variant-a-timescaledb-1 psql -U magris -d magris -c "TRUNCATE measurements; DELETE FROM devices;"`
  or full reset with `docker compose ... down -v && up -d`.
