CREATE TABLE IF NOT EXISTS device_config (
    device_id       TEXT REFERENCES devices(device_id),
    config_key      TEXT NOT NULL,
    config_value    JSONB NOT NULL,
    updated_by      TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, config_key)
);
CREATE TABLE IF NOT EXISTS device_config_pending (
    id              BIGSERIAL PRIMARY KEY,
    device_id       TEXT REFERENCES devices(device_id),
    config_key      TEXT NOT NULL,
    config_value    JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    acked_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS device_config_pending_unacked
    ON device_config_pending (device_id, config_key)
    WHERE acked_at IS NULL;
CREATE TABLE IF NOT EXISTS file_uploads (
    file_name       TEXT PRIMARY KEY,
    device_id       TEXT REFERENCES devices(device_id),
    data_type       TEXT NOT NULL CHECK (data_type IN ('gnss', 'position', 'accel')),
    upload_origin   TEXT NOT NULL DEFAULT 'device_auto'
                     CHECK (upload_origin IN ('device_auto', 'manual_technician')),
    sequence_number INTEGER,
    record_count    INTEGER,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'gnss_raw_samples_file_name_fkey') THEN
        ALTER TABLE gnss_raw_samples
            ADD CONSTRAINT gnss_raw_samples_file_name_fkey
            FOREIGN KEY (file_name) REFERENCES file_uploads(file_name);
    END IF;
END $$;
