CREATE TABLE IF NOT EXISTS device_position_records (
    time                TIMESTAMPTZ NOT NULL,
    device_id           TEXT NOT NULL REFERENCES devices(device_id),
    site_id             TEXT NOT NULL REFERENCES sites(site_id),
    latitude            DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude           DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    altitude_m          DOUBLE PRECISION,
    gnss_fix_type       INTEGER NOT NULL CHECK (gnss_fix_type > 0),
    h_acc_m             DOUBLE PRECISION CHECK (h_acc_m IS NULL OR h_acc_m >= 0),
    source_kind         TEXT NOT NULL CHECK (source_kind IN ('rtk_direct')),
    validation_status   TEXT NOT NULL DEFAULT 'unvalidated'
        CHECK (validation_status IN ('unvalidated', 'validated')),
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, time, source_kind)
);

CREATE INDEX IF NOT EXISTS device_position_site_time_idx
    ON device_position_records (site_id, time DESC);
CREATE INDEX IF NOT EXISTS device_position_device_time_idx
    ON device_position_records (device_id, time DESC);

COMMENT ON TABLE device_position_records IS
    'GNSS-derived device positions used for device-map display. These records are positioning telemetry, not displacement ground truth.';
COMMENT ON COLUMN device_position_records.validation_status IS
    'Independent geodetic validation state. Map availability must not imply production displacement validation.';

DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version) VALUES (24) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
