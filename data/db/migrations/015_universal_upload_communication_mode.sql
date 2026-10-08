ALTER TABLE file_uploads
    ADD COLUMN IF NOT EXISTS communication_mode TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'file_uploads_communication_mode_check'
    ) THEN
        ALTER TABLE file_uploads
            ADD CONSTRAINT file_uploads_communication_mode_check
            CHECK (communication_mode IS NULL OR communication_mode IN ('4g', 'lora'));
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS file_uploads_communication_mode_received_idx
    ON file_uploads (communication_mode, received_at DESC);
COMMENT ON COLUMN file_uploads.communication_mode IS
    '4g|lora from X-Communication-Mode. NULL means legacy upload before 2026-09-24; never infer/backfill silently.';
