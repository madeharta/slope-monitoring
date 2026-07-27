-- Narrow/long storage (context.md §6): one row per measurement, so adding a
-- sensor type needs no schema migration and no consumer change.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS sites (
    site_id text PRIMARY KEY,
    name    text NOT NULL,
    lat     double precision NOT NULL,
    lon     double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id   text PRIMARY KEY,
    device_type text NOT NULL,
    site_id     text NOT NULL REFERENCES sites (site_id),
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz
);

CREATE TABLE IF NOT EXISTS measurements (
    time         timestamptz      NOT NULL,          -- produce/ingress time
    device_id    text             NOT NULL,
    site_id      text             NOT NULL,          -- always present
    quantity     text             NOT NULL,
    value        double precision,                   -- null == bad reading (see quality_flag)
    unit         text             NOT NULL,
    depth_cm     double precision,                   -- always a column; null only for surface sensors
    quality_flag text             NOT NULL DEFAULT 'ok',
    received_at  timestamptz      NOT NULL,          -- consumer-receipt hop stamp
    latency_ms   double precision                    -- received_at - time, convenience
);

SELECT create_hypertable('measurements', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS measurements_device_time
    ON measurements (device_id, time DESC);
CREATE INDEX IF NOT EXISTS measurements_quantity_time
    ON measurements (quantity, time DESC);

-- Seed the known sites so device upserts satisfy the FK.
INSERT INTO sites (site_id, name, lat, lon) VALUES
    ('lereng-a', 'Lereng A (Depok)', -6.3643, 106.8290),
    ('lereng-b', 'Lereng B (Bogor)', -6.5950, 106.8060)
ON CONFLICT (site_id) DO NOTHING;
