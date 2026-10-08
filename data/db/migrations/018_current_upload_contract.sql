ALTER TABLE file_uploads
    DROP CONSTRAINT IF EXISTS file_uploads_data_type_check;
ALTER TABLE file_uploads
    ADD CONSTRAINT file_uploads_data_type_check
    CHECK (data_type IN ('gnss', 'accel')) NOT VALID;
DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version) VALUES (18) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
