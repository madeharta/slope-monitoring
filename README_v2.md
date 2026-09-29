# Slope Landslide Monitoring
## Current QA Baseline

Validated against the synchronized source package dated 27 September 2026:

```text
213 passed, 1 skipped
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
services/rinex_service/    RINEX parser, NAV resolver, SRGI guard, and content-addressed cache
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

Fresh database bootstrap in `docker/initdb/001_full_schema.sql` is synchronized through revision 19.

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
RTKLIB_NAV_FILE=
RINEX_CACHE_DIR=/data/rinex-cache
RINEX_DOWNLOAD_TIMEOUT_S=60
RINEX_DOWNLOAD_MAX_BYTES=262144000
RINEX_DECOMPRESS_MAX_BYTES=536870912
RINEX_DECOMPRESS_MAX_RATIO=100
RINEX_DECOMPRESS_TIMEOUT_S=30
DEVICE_DEFAULT_PERIODIC_UPLOAD_S=300
DEVICE_DEFAULT_FIRMWARE_VERSION=
DEVICE_DEFAULT_THRESHOLD_G=0.5
DEVICE_DEFAULT_TIME_RECORD_MS=2000
DEVICE_DEFAULT_TRIGGER_START=0
DEVICE_DEFAULT_TIMEOUT_TRIGGER=300
RTKLIB_CONFIG_FILE=config/rtklib_ppk.conf
PPK_WINDOW_SECONDS=300
PPK_WINDOW_PAD_SECONDS=30
PPK_MIN_EPOCHS=4
PPK_MAX_H_ACC_M=0.10
PPK_ACCEPTED_RTKLIB_QUALITY=1
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

Expected baseline dated 27 September 2026:

```text
213 passed, 1 skipped
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

## Automatic Public Broadcast Ephemeris Acquisition

The server can now ensure a broadcast-navigation file for an observation UTC timestamp without changing the device payload. The acquisition layer checks the existing content-addressed cache first, then tries public merged RINEX navigation products in deterministic order: BKG WRD, the IGS merged product mirrored by BKG, and the IGS product at CDDIS. Downloaded content is accepted only after HTTPS host validation, bounded transfer, HTML rejection, RINEX parsing, navigation-type validation, and UTC-date validation. Successful artifacts enter the same RINEX cache and NAV resolver used for manually imported SRGI data.

Public BRDC products are treated as global navigation data, not station-specific NAV. An exact station-specific candidate still outranks a global candidate when both are present. This preserves strict rejection of a wrong station when the cache contains only station-specific navigation while allowing merged public BRDC navigation to serve observations from any station.

Manual SRGI import remains supported as a fallback. Device-side ephemeris/SFRBX is not required by this patch and can remain a later contingency. The acquisition service remains separate from the solver internals and is now invoked by the multi-epoch/window PPK job before rnx2rtkp.

CLI example:
```bash
python -m scripts.fetch_rinex_nav --timestamp '2026-09-25T12:00:00Z' --station CLBG
```

A cache hit performs no network request. On a cache miss, the command attempts the configured public providers and stores the validated NAV artifact persistently under RINEX_CACHE_DIR.

## Multi-Epoch RTKLIB PPK Pipeline

The 4G periodic GNSS pipeline now processes overlapping base/rover RAWX observations as a window instead of solving one isolated epoch at a time. Each device stream is ordered and exact duplicate epoch/payload pairs are removed, convbin is run once per stream/window, broadcast navigation is resolved through the cache-first automatic acquisition layer, and rnx2rtkp is run once for the window.

All RTKLIB solution epochs are parsed and retained. RTKLIB quality (Q) remains an RTKLIB-specific field and is not mapped to the u-blox gnss_fix_type. Derived monitoring output can include rtklib_quality, satellite count, age, ambiguity ratio, and standard-deviation components alongside horizontal accuracy.

The base surveyed position and rover displacement baseline must both explicitly use ELLIPSOIDAL_WGS84. Legacy or unconfirmed vertical datums are not silently relabeled and block PPK-derived displacement. Monitoring displacement is computed from the rover solution relative to its approved rover baseline using WGS84 geodetic → ECEF → ENU conversion; the base station is the PPK reference, not the monitoring zero point.

A base upload also attempts reconciliation for rover windows at the same site. This allows rover observations that arrived before the base upload to become processable after the matching base observations arrive. Insufficient windows remain pending instead of being interpolated.
The version-controlled RTKLIB configuration is config/rtklib_ppk.conf. Public .rnx.gz navigation artifacts are safely materialized to plain RINEX in the temporary RTKLIB work directory before solver execution.

Relevant runtime controls;
```text
RTKLIB_CONFIG_FILE=config/rtklib_ppk.conf
PPK_WINDOW_SECONDS=300
PPK_WINDOW_PAD_SECONDS=30
PPK_MIN_EPOCHS=4
PPK_MAX_H_ACC_M=0.10
PPK_ACCEPTED_RTKLIB_QUALITY=1
```