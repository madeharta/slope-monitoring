# Slope Landslide Monitoring
## Current QA Baseline

Validated against the synchronized source package dated 25 September 2026:

```text
148 passed, 1 skipped
Python compile validation: OK
```

## Runtime Stack

- Python 3.11+
- FastAPI / Uvicorn
- PostgreSQL 16
- TimescaleDB 2.15.3
- React / Vite
- Nginx
- RTKLIB `convbin` and `rnx2rtkp`
- Docker Compose recommended

## Repository Layout

```text
apps/api/                  FastAPI API
apps/frontend/             React/Vite dashboard
common/                    shared security/error/audit modules
data/db/migrations/        incremental DB migrations
docker/initdb/             fresh DB bootstrap
ml/                        preprocessing/evaluation/model modules
services/                  application/domain repositories and services
tests/                     automated tests
Dockerfile                 API + RTKLIB image
docker-compose.yml         application stack
requirements.txt           Python runtime dependencies
requirements-ml.txt        optional ML dependencies
```

## Device Integration Contract

Primary upload endpoint:

```http
POST /api/upload/{file_name}
```

Boot/config compatibility endpoint:

```http
GET /api/config
X-Device-Id: <device-id>
```

The legacy internal-compatible path remains available:

```http
GET /api/v1/device/config
X-Device-Id: <device-id>
```

Every successful upload, including an idempotent duplicate, returns the same configuration shape used by `GET /api/config`:

```json
{
  "ok": true,
  "config": {
    "periodic_upload_s": 300,
    "firmware_version": "",
    "battery_cal": {
      "BASE-01": { "m": null, "c": null },
      "ROVER-B1-01": { "m": null, "c": null },
      "ROVER-B1-02": { "m": null, "c": null }
    },
    "threshold_g": 0.5,
    "time_record_ms": 2000,
    "TriggerStart": 0,
    "TimeOutTrigger": 300
  }
}
```

`battery_cal` values remain `null` until field calibration is saved. Do not treat uncalibrated values as measured calibration coefficients.

## Database State

Fresh database bootstrap in `docker/initdb/001_full_schema.sql` is synchronized through revision 17.

## Environment

Do not commit `.env`.

Required/important settings:

```text
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
JWT_SECRET_KEY
ALLOWED_ORIGINS
RTKLIB_CONVBIN_PATH
RTKLIB_RNX2RTKP_PATH
RTKLIB_NAV_FILE
MEASUREMENTS_RETENTION_DAYS
MFA_ENFORCEMENT_ENABLED
WEATHER_POLLING_ENABLED
DEVICE_DEFAULT_PERIODIC_UPLOAD_S
DEVICE_DEFAULT_FIRMWARE_VERSION
DEVICE_DEFAULT_THRESHOLD_G
DEVICE_DEFAULT_TIME_RECORD_MS
DEVICE_DEFAULT_TRIGGER_START
DEVICE_DEFAULT_TIMEOUT_TRIGGER
```

Generate deployment secrets independently for every environment.

## Health Check

Process-level API health is checked using:

```bash
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```
or
```bash
curl -fsS http://127.0.0.1:8000/docs > /dev/null
```

## Test Commands

Backend:

```bash
python -m pytest -q
```

Expected baseline dated 25 September 2026:

```text
144 passed, 1 skipped
```

Frontend:

```bash
cd apps/frontend
npm ci --no-audit --no-fund
npm run build
```

Compose validation:

```bash
docker compose config
```

See `DEPLOYMENT_GUIDE.md` for Docker and native venv/systemd deployment procedures.
