ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'device',
    ADD COLUMN IF NOT EXISTS source_file TEXT,
    ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'unverified';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'measurements_source_kind_check'
          AND conrelid = 'measurements'::regclass
    ) THEN
        ALTER TABLE measurements
            ADD CONSTRAINT measurements_source_kind_check
            CHECK (source_kind IN ('device', 'external', 'derived'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'measurements_validation_status_check'
          AND conrelid = 'measurements'::regclass
    ) THEN
        ALTER TABLE measurements
            ADD CONSTRAINT measurements_validation_status_check
            CHECK (validation_status IN ('unverified', 'provisional', 'validated', 'not_applicable'));
    END IF;
END $$;
UPDATE measurements
SET source_kind = 'external',
    validation_status = 'not_applicable'
WHERE device_id = 'WEATHER-API';
UPDATE measurements
SET source_kind = 'derived'
WHERE quantity IN (
    'displacement', 'disp_e', 'disp_n', 'disp_u',
    'ppa', 'ppv', 'tilt_x', 'tilt_y'
)
AND device_id <> 'WEATHER-API';
CREATE INDEX IF NOT EXISTS measurements_source_kind_time
    ON measurements (source_kind, time DESC);
COMMENT ON COLUMN measurements.source_kind IS
    'Provenance class: device=direct physical-device reading, external=third-party/API source, derived=calculated pipeline output.';
COMMENT ON COLUMN measurements.source_file IS
    'Original file name when measurement came from a file import; NULL for live/API-generated rows.';
COMMENT ON COLUMN measurements.validation_status IS
    'Validation lifecycle independent from quality_flag: unverified/provisional/validated/not_applicable.';
