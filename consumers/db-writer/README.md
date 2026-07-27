# consumers/db-writer

Consumes from MQTT (variant A) or Kafka (variants B/C/D) and writes to TimescaleDB.

- Async via `aiokafka` / `asyncio-mqtt`; do NOT mix blocking DB calls into async paths.
- Writes **narrow/long**: one row per measurement — `(time, device_id, site_id, quantity, value, unit, depth_cm, quality_flag)`.
- Device/sensor metadata in small `devices` / `sensors` tables (replaces the prior work's hardcoded `data_store` dict).

Not yet implemented.
