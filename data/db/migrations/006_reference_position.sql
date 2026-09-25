CREATE TABLE IF NOT EXISTS device_reference_position (
    device_id       TEXT PRIMARY KEY REFERENCES devices(device_id),
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    altitude_m      DOUBLE PRECISION NOT NULL,
    surveyed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    surveyed_by     TEXT
);
