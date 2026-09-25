CREATE TABLE IF NOT EXISTS blast_trigger_commands (
    command_id      BIGSERIAL PRIMARY KEY,
    base_id         TEXT REFERENCES devices(device_id),
    trigger_source  TEXT NOT NULL CHECK (trigger_source IN ('hardware_lora', 'web_dashboard')),
    requested_by    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS blast_commands_pending
    ON blast_trigger_commands (base_id) WHERE status = 'pending';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'accel_raw_samples_blast_command_fkey') THEN
        ALTER TABLE accel_raw_samples
            ADD CONSTRAINT accel_raw_samples_blast_command_fkey
            FOREIGN KEY (blast_command_id) REFERENCES blast_trigger_commands(command_id);
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS model_versions (
    version_id      TEXT PRIMARY KEY,
    model_type      TEXT NOT NULL,
    artifact_path   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'registered'
                     CHECK (status IN ('registered', 'rejected', 'active', 'retired')),
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at    TIMESTAMPTZ
);
