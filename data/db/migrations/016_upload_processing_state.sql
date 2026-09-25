ALTER TABLE file_uploads
    ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'processed',
    ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'file_uploads_processing_status_check'
    ) THEN
        ALTER TABLE file_uploads
            ADD CONSTRAINT file_uploads_processing_status_check
            CHECK (processing_status IN ('received', 'processing', 'processed', 'failed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'file_uploads_processing_attempts_check'
    ) THEN
        ALTER TABLE file_uploads
            ADD CONSTRAINT file_uploads_processing_attempts_check
            CHECK (processing_attempts >= 1);
    END IF;
END $$;
UPDATE file_uploads
SET processed_at = COALESCE(processed_at, received_at)
WHERE processing_status = 'processed' AND processed_at IS NULL;
CREATE INDEX IF NOT EXISTS file_uploads_processing_status_received_idx
    ON file_uploads (processing_status, received_at DESC);
COMMENT ON COLUMN file_uploads.processing_status IS
    'Retry-safe state: received|processing|processed|failed. Only processed is duplicate-success; failed is retryable.';
COMMENT ON COLUMN file_uploads.processing_attempts IS
    'Number of processing claims for this X-File-Name, including retries after failed.';
COMMENT ON COLUMN file_uploads.last_error IS
    'Last processing exception summary, truncated by application; must not contain raw payloads/secrets.';
