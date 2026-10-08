ALTER TABLE accel_raw_samples
    ADD COLUMN IF NOT EXISTS file_name TEXT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'accel_raw_samples_file_name_fkey') THEN
        ALTER TABLE accel_raw_samples
            ADD CONSTRAINT accel_raw_samples_file_name_fkey
            FOREIGN KEY (file_name) REFERENCES file_uploads(file_name);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS accel_raw_file_name_idx
    ON accel_raw_samples (file_name) WHERE file_name IS NOT NULL;

CREATE TABLE IF NOT EXISTS blast_event_records (
    event_id                 BIGSERIAL PRIMARY KEY,
    site_id                  TEXT NOT NULL REFERENCES sites(site_id),
    device_id                TEXT NOT NULL REFERENCES devices(device_id),
    blast_command_id         BIGINT REFERENCES blast_trigger_commands(command_id),
    source_file              TEXT NOT NULL UNIQUE REFERENCES file_uploads(file_name),
    communication_mode       TEXT NOT NULL CHECK (communication_mode IN ('4g','lora')),
    schema_version           TEXT NOT NULL DEFAULT 'blast.event.v1'
                             CHECK (schema_version = 'blast.event.v1'),
    event_start              TIMESTAMPTZ NOT NULL,
    event_end                TIMESTAMPTZ NOT NULL,
    sample_count             INTEGER NOT NULL CHECK (sample_count >= 0),
    duration_ms              DOUBLE PRECISION NOT NULL CHECK (duration_ms >= 0),
    observed_sample_rate_hz  DOUBLE PRECISION,
    median_gap_ms            DOUBLE PRECISION,
    max_gap_ms               DOUBLE PRECISION,
    quality_gate_status      TEXT NOT NULL CHECK (quality_gate_status IN ('accepted','degraded','rejected')),
    quality_reasons          JSONB NOT NULL DEFAULT '[]'::jsonb,
    adxl355_ppa_g            DOUBLE PRECISION,
    adxl355_ppv_mm_s         DOUBLE PRECISION,
    mpu9250_ppa_g            DOUBLE PRECISION,
    mpu9250_ppv_mm_s         DOUBLE PRECISION,
    validation_status        TEXT NOT NULL DEFAULT 'unvalidated'
                             CHECK (validation_status IN ('unvalidated','validated')),
    processed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (event_end >= event_start)
);
CREATE INDEX IF NOT EXISTS blast_event_site_time_idx ON blast_event_records (site_id, event_start DESC);
CREATE INDEX IF NOT EXISTS blast_event_device_time_idx ON blast_event_records (device_id, event_start DESC);

COMMENT ON TABLE blast_event_records IS
    'Technical accelerometer/blast event features with source-file provenance. PPA/PPV remain unvalidated engineering metrics, not field-safety compliance values.';

DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version) VALUES (23) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
