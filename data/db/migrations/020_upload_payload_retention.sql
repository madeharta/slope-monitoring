CREATE TABLE IF NOT EXISTS file_upload_payloads (
    file_name       TEXT PRIMARY KEY REFERENCES file_uploads(file_name) ON DELETE CASCADE,
    payload         BYTEA NOT NULL,
    sha256          CHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_length     BIGINT NOT NULL CHECK (byte_length >= 0),
    content_type    TEXT NOT NULL DEFAULT 'text/csv',
    request_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    stored_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE file_upload_payloads IS
    'Exact original upload bytes retained for QA/re-download. Kept separate from file_uploads so history listing never pulls large payloads.';
COMMENT ON COLUMN file_upload_payloads.request_headers IS
    'Allowlisted non-secret X-* upload contract/status headers only; credentials and arbitrary headers must never be stored.';

DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version) VALUES (20) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
