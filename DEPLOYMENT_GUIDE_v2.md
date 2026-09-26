# Deployment Guide — Slope Landslide Monitoring

Two supported deployment patterns are documented:

1. Docker Compose — recommended.
2. Native Python venv + systemd + Nginx.

Commands assume Linux and execution from repository root.

# 1. Deployment Preconditions

Recommended baseline:

```text
Linux
Git
HTTPS reverse proxy/load balancer
PostgreSQL 16
TimescaleDB 2.15.3
Python 3.11 (use this version to support RTKLIB)
Node.js for native frontend build
RTKLIB for native deployment
```

# 2. Docker Compose Deployment

## 2.1 Prepare Repository

```bash
git clone <repository-url> slope-stag-v2
cd <repository-folder>
```

Ensure secrets are not tracked:

```bash
git ls-files | grep -E '(^|/)\.env$' && echo 'ERROR: .env must not be tracked' || true
```

## 2.2 Create `.env`

Generate secrets:

```bash
openssl rand -base64 32
openssl rand -hex 32
```

Example:

```dotenv
DB_NAME=slope_iot
DB_USER=slope
DB_PASSWORD=<strong-random-password>
JWT_SECRET_KEY=<random-64-hex-secret>
ALLOWED_ORIGINS=https://monitoring.example.com
DB_HOST_PORT=5433
API_HOST_PORT=8000
FRONTEND_HOST_PORT=5173
RTKLIB_NAV_FILE=
MEASUREMENTS_RETENTION_DAYS=730
MFA_ENFORCEMENT_ENABLED=true
WEATHER_POLLING_ENABLED=false
DEVICE_DEFAULT_PERIODIC_UPLOAD_S=300
DEVICE_DEFAULT_FIRMWARE_VERSION=
DEVICE_DEFAULT_THRESHOLD_G=0.5
DEVICE_DEFAULT_TIME_RECORD_MS=2000
DEVICE_DEFAULT_TRIGGER_START=0
DEVICE_DEFAULT_TIMEOUT_TRIGGER=300
```

Protect the file:

```bash
chmod 600 .env
```

## 2.3 Fresh Database

For a new empty Docker volume, `docker/initdb/001_full_schema.sql` automatically initializes the database through revision 18.

Start DB:

```bash
docker compose up -d db
docker compose ps
```

Wait for `db` to become healthy.

## 2.4 Build and Start

```bash
docker compose config >/dev/null
docker compose build api frontend
docker compose up -d api frontend
docker compose ps
```

Expected services:

```text
db        healthy
api       healthy
frontend  healthy
```

## 2.5 Smoke Tests

API:

```bash
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```
or
```bash
curl -fsS http://127.0.0.1:8000/docs >/dev/null
```

Frontend:

```bash
curl -I http://127.0.0.1:5173/
```

Logs:

```bash
docker compose logs --tail=200 api
docker compose logs --tail=100 frontend
docker compose logs --tail=100 db
```

## 2.6 Reverse Proxy/TLS

The Compose ports are bound to loopback. Publish HTTPS through a reverse proxy/load balancer and proxy public traffic to the frontend.

Recommended topology:

```text
Internet
  |
HTTPS :443
  |
Reverse proxy/load balancer
  |
127.0.0.1:5173
  |
Docker network -> api:8000 -> db:5432
```

Do not expose PostgreSQL publicly.

Set the browser-visible HTTPS origin exactly in `ALLOWED_ORIGINS`.

# 3. Native venv + systemd Deployment

## 3.1 Database

Provision PostgreSQL 16 with TimescaleDB 2.15.3.

For a fresh database:

```bash
psql -v ON_ERROR_STOP=1 \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -f docker/initdb/001_full_schema.sql
```

Current bootstrap already includes revision 17.

For an existing staging database previously migrated through 016:

```bash
psql -v ON_ERROR_STOP=1 \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -f data/db/migrations/017_device_config_contract.sql
```

## 3.2 RTKLIB

Build/install:

```bash
git clone --depth 1 https://github.com/tomojitakasu/RTKLIB.git /tmp/RTKLIB
make -C /tmp/RTKLIB/app/convbin/gcc
make -C /tmp/RTKLIB/app/rnx2rtkp/gcc
sudo install -m 0755 /tmp/RTKLIB/app/convbin/gcc/convbin /usr/local/bin/convbin
sudo install -m 0755 /tmp/RTKLIB/app/rnx2rtkp/gcc/rnx2rtkp /usr/local/bin/rnx2rtkp
```

## 3.3 Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest -q
```

Expected:

```text
152 passed, 1 skipped
```

## 3.4 API Environment File

Create an OS-owned file, for example `/etc/slope-monitoring/api.env`:

```dotenv
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=slope_iot
DB_USER=slope
DB_PASSWORD=<secret>
JWT_SECRET_KEY=<secret>
ALLOWED_ORIGINS=https://monitoring.example.com
RTKLIB_CONVBIN_PATH=/usr/local/bin/convbin
RTKLIB_RNX2RTKP_PATH=/usr/local/bin/rnx2rtkp
RTKLIB_NAV_FILE=
MEASUREMENTS_RETENTION_DAYS=730
MFA_ENFORCEMENT_ENABLED=true
WEATHER_POLLING_ENABLED=false
DEVICE_DEFAULT_PERIODIC_UPLOAD_S=300
DEVICE_DEFAULT_FIRMWARE_VERSION=
DEVICE_DEFAULT_THRESHOLD_G=0.5
DEVICE_DEFAULT_TIME_RECORD_MS=2000
DEVICE_DEFAULT_TRIGGER_START=0
DEVICE_DEFAULT_TIMEOUT_TRIGGER=300
```

```bash
sudo chown root:root /etc/slope-monitoring/api.env
sudo chmod 600 /etc/slope-monitoring/api.env
```

## 3.5 systemd Unit

```ini
[Unit]
Description=Slope Landslide Monitoring API
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=slope-monitor
Group=slope-monitor
WorkingDirectory=/opt/slope-landslide
EnvironmentFile=/etc/slope-monitoring/api.env
ExecStart=/opt/slope-landslide/.venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now slope-monitoring-api
sudo systemctl status slope-monitoring-api
```

Smoke test:

```bash
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```

## 3.6 Frontend

```bash
cd apps/frontend
npm ci --no-audit --no-fund
npm run build
```

Deploy `apps/frontend/dist/` behind Nginx.

Use `127.0.0.1:8000` as the native API upstream.

# 4. First Admin

There is no hard-coded production admin account. Create the first admin through an approved bootstrap procedure using an Argon2 hash generated by the application security helper, then require normal login/MFA enrollment.

Never store the plaintext initial password in Git or deployment scripts.

# 5. Deployment Acceptance Checklist

```text
[ ] correct Git commit/tag deployed
[ ] no .env tracked
[ ] environment-specific DB/JWT secrets generated
[ ] PostgreSQL private
[ ] TimescaleDB installed
[ ] DB schema current through revision 18
[ ] full Python test suite passes: 152 passed, 1 skipped
[ ] frontend build succeeds
[ ] docker compose config succeeds, if Docker deployment
[ ] API openapi.json responds
[ ] GET /api/config returns the full config contract
[ ] battery_cal response contains only BASE-01, ROVER-B1-01, and ROVER-B1-02; values are intentionally configured or explicitly null
[ ] trigger sets TriggerStart=1
[ ] TimeOutTrigger remains in minutes (example: timeout_minutes=2 -> TimeOutTrigger=2)
[ ] blast_trigger_commands.requested_by stores the numeric user ID
[ ] reset sets TriggerStart=0 without converting/changing TimeOutTrigger
[ ] new `position` upload is rejected and production data types remain only `gnss | accel`
[ ] duplicate upload still returns HTTP 200 plus config
[ ] HTTPS/reverse proxy configured
[ ] ALLOWED_ORIGINS matches public HTTPS origin
[ ] backups and restore procedure defined
[ ] logs/metrics collection enabled
```

# 6. Security Deployment Gate

Current application security posture still requires controlled ingress for cloud deployment. Keep device/API access behind private networking, VPN, zero-trust gateway, mTLS/API gateway, or strict allowlisting according to the organization's deployment design.

Never expose PostgreSQL publicly.

Never commit `.env`, credentials, JWT keys, MFA secrets, certificates, or cloud secrets.

# 7. Upgrade Procedure

Back up the database first.

```bash
git fetch --all --tags
git checkout <approved-tag-or-commit>
```

Apply new migrations in order, then rebuild/restart application services.

Docker example:

```bash
docker compose build api frontend
docker compose up -d api frontend
docker compose ps
docker compose logs --tail=200 api
```

Do not use `docker compose down -v` during normal upgrades because it removes the database volume.
