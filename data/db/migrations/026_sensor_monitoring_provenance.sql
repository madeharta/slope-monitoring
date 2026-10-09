ALTER TABLE device_position_records
    ADD COLUMN IF NOT EXISTS source_file TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'device_position_records_source_file_fkey'
    ) THEN
        ALTER TABLE device_position_records
            ADD CONSTRAINT device_position_records_source_file_fkey
            FOREIGN KEY (source_file) REFERENCES file_uploads(file_name);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS device_position_source_file_idx
    ON device_position_records (source_file)
    WHERE source_file IS NOT NULL;

COMMENT ON COLUMN device_position_records.source_file IS
    'Original accepted upload file. NULL on historical rows where provenance was not persisted; never backfilled by inference.';

DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version)
        VALUES (26) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
