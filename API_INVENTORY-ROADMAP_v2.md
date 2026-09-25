# Full API Inventory Matrix — External

This document summarizes the API surface intended for integration, deployment, and partner coordination. It is maintained together with the deployed API implementation.

## Live API Specification

For exact request parameters, headers, response schemas, and interactive API testing, use the Swagger UI exposed by the deployed backend:

```text
https://<backend-host>/docs
```

For staging/local verification:

```text
http://localhost:8000/docs
```

Machine-readable OpenAPI schema:

```text
https://<backend-host>/openapi.json
```

Alternative ReDoc view:

```text
https://<backend-host>/redoc
```

The Swagger/OpenAPI page is the preferred reference for the **actual routes and structured request/response schemas implemented by the running backend**.

This inventory remains complementary to Swagger for integration rules that are not fully represented by OpenAPI alone, including CSV content rules, 4G/LoRa routing behavior, filename conventions, field-data acceptance status, and agreed integration clarifications.

---

# 1. API Inventory

| Method | Endpoint | Access | Purpose | Status |
|---|---|---|---|---|
| POST | `/api/upload/{file_name}` | device integration headers | Universal CSV upload for 4G/LoRa GNSS and accel data | Ready |
| GET | `/api/config` | `X-Device-Id` | Device boot/config retrieval | Ready |
| GET | `/api/v1/device/config` | `X-Device-Id` | Compatibility config route | Ready |
| PUT | `/api/v1/device/config/{device_id}` | operator/admin | Update device configuration and battery calibration | Ready |
| POST | `/api/v1/blast/trigger` | operator/admin + MFA | Start trigger window through `TriggerStart` and optional timeout | Ready |
| POST | `/api/v1/blast/reset` | operator/admin + MFA | Reset `TriggerStart` after completion/cancellation | Ready |
| POST | `/api/v1/auth/login` | user credentials | Login | Ready |
| POST | `/api/v1/auth/refresh` | refresh token | Refresh session | Ready |
| POST | `/api/v1/auth/mfa/enroll` | authenticated user | Enroll MFA | Ready |
| POST | `/api/v1/auth/mfa/verify` | authenticated user | Verify MFA | Ready |
| GET | `/api/overview` | deployment access policy | Dashboard overview | Ready |
| GET | `/api/sites/{site_id}` | deployment access policy | Site detail/time series | Ready |
| GET | `/api/stream` | deployment access policy | Dashboard event stream | Ready |
| GET | `/api/v1/devices` | viewer+ | List devices | Ready |
| POST | `/api/v1/devices` | admin | Register device | Ready |
| PUT | `/api/v1/devices/{device_id}` | admin | Update device | Ready |
| DELETE | `/api/v1/devices/{device_id}` | admin | Remove device | Ready |
| POST | `/api/v1/sites` | admin | Create site | Ready |
| GET | `/api/v1/sites/nearby` | admin | Site proximity validation | Ready |
| PUT | `/api/v1/sites/{site_id}` | admin | Update site | Ready |
| DELETE | `/api/v1/sites/{site_id}` | admin | Delete site | Ready |
| GET | `/api/v1/measurements` | viewer+ | Query measurements | Ready |
| GET | `/api/v1/audit-log` | viewer+ | Query audit records | Ready |
| GET | `/api/v1/users` | admin | List users | Ready |
| POST | `/api/v1/users` | admin | Create user | Ready |
| PUT | `/api/v1/users/{user_id}/role` | admin | Change role | Ready |
| DELETE | `/api/v1/users/{user_id}` | admin | Disable user | Ready |
| POST | `/api/v1/users/{user_id}/enable` | admin | Enable user | Ready |
| POST | `/api/v1/weather/fetch/{site_id}` | operator/admin | Fetch external weather measurements | Ready |
| GET | `/openapi.json` | deployment/tooling policy | OpenAPI schema and process health probe | Ready |
| GET | `/docs` | deployment/tooling policy | Interactive Swagger API specification | Ready when enabled in deployment |
| GET | `/redoc` | deployment/tooling policy | ReDoc API specification | Ready when enabled in deployment |

---

# 2. Device Config Response

`GET /api/config` and every successful upload are designed to use the same configuration block:

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
For the exact schema currently exposed by the running backend, refer to Swagger:

```text
https://<backend-host>/docs
```

---

# 3. Upload Behavior

- HTTP `200` means the file is accepted.
- An idempotent duplicate also returns HTTP `200`.
- Normal success and duplicate success return the configuration block.
- Non-`200` means the sender should retain/retry the file according to the integration protocol.
- Production data types are `gnss` and `accel`.
- Communication mode is identified as `4g` or `lora`.
- Exact required headers and endpoint parameters should be checked in Swagger/OpenAPI.

### Current Upload Readiness

| Data Flow | Status | Notes |
|---|---|---|
| 4G periodic GNSS — Base | Verified | Upload, persistence, and duplicate/idempotency path verified in staging |
| 4G periodic GNSS — Rover | Ready for acceptance | Backend contract implemented; real-device smoke test remains |
| LoRa combined periodic GNSS | Ready for acceptance | Backend parser/routing implemented; awaiting updated real ITB file |
| LoRa manual blast accel | Ready for acceptance | Contract implemented; awaiting updated real ITB file |
| 4G blast accel | Ready for acceptance | Uses latest agreed rule: accel plus one post-blast UBX RXM-RAWX; awaiting updated real ITB file |

---
# 4. Current Works

The current integration workstream is focused on:

| Work Item | Current State |
|---|---|
| Config/trigger end-to-end smoke validation | In progress — config endpoint is verified; final parity checks cover normal upload, duplicate upload, and trigger lifecycle |
| 4G Rover GNSS acceptance | Waiting for real-device/sample validation |
| LoRa combined GNSS acceptance | Waiting for updated ITB field file |
| LoRa accel acceptance | Waiting for updated ITB field file |
| 4G blast accel acceptance | Waiting for updated ITB field file matching the latest one-RAWX rule |
| API documentation synchronization | Ongoing — this inventory and Swagger/OpenAPI are maintained with implementation changes |

---

# 5. Pending Items

The following items are not yet considered fully production-qualified:

| Pending Item | Target |
|---|---|
| Real-file acceptance for remaining 4G/LoRa flows | Validate actual field/device files against the implemented upload contract |
| RINEX acquisition for PPK | Integrate server-side navigation/ephemeris retrieval using the agreed RINEX source |
| Production PPK processing | Complete RTKLIB window/multi-epoch processing and quality handling |
| Baseline/displacement operational qualification | Validate approved baseline and displacement processing before operational use |
| Accel-derived PPA/PPV operational validation | Validate processing using accepted blast datasets |
| Prediction/alert pipeline | Downstream work after scientific data pipeline and labels are qualified |

Items move from pending to ready only after implementation plus reproducible acceptance evidence.

---

# 7. Model Operations APIs

These APIs exist for model lifecycle work but remain pre-production:

| Method | Endpoint | Access | Purpose | Status |
|---|---|---|---|---|
| POST | `/api/v1/model/register` | admin | Register model metadata/artifact | Pre-production |
| POST | `/api/v1/model/activate` | admin | Activate registered model | Pre-production |
| POST | `/api/v1/model/switch-architecture` | admin | Switch registered model architecture | Pre-production |
| POST | `/api/v1/model/rollback` | admin | Roll back active model | Pre-production |
| GET | `/api/v1/model/active` | deployment access policy | Read active model summary | Pre-production |

---

# 8. Specification Reference Rule

Use the following precedence when integrating with a deployed environment:

1. **Swagger/OpenAPI of the deployed backend** for actual endpoint paths, methods, parameters, and structured schemas:
   ```text
   https://<backend-host>/docs
   ```
2. **This inventory and roadmap** for readiness, current work, pending items, and integration-level behavior.
3. **Approved device/API integration specification** for CSV field semantics, timing, file naming, and hardware communication behavior.

If an integration team observes a mismatch between Swagger and this document, report the deployed backend version/commit and Swagger output so the inventory can be synchronized with the implementation.
