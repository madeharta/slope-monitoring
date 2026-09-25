DELETE FROM gnss_raw_samples
WHERE (tableoid, ctid) IN (
    SELECT tableoid, ctid FROM (
        SELECT tableoid, ctid,
               ROW_NUMBER() OVER (PARTITION BY device_id, time ORDER BY tableoid, ctid) AS rn
        FROM gnss_raw_samples
    ) ranked
    WHERE ranked.rn > 1
);
DELETE FROM accel_raw_samples
WHERE (tableoid, ctid) IN (
    SELECT tableoid, ctid FROM (
        SELECT tableoid, ctid,
               ROW_NUMBER() OVER (PARTITION BY device_id, time, sample_index ORDER BY tableoid, ctid) AS rn
        FROM accel_raw_samples
    ) ranked
    WHERE ranked.rn > 1
);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'gnss_raw_samples_unique_epoch') THEN
        ALTER TABLE gnss_raw_samples
            ADD CONSTRAINT gnss_raw_samples_unique_epoch UNIQUE (device_id, time);
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'accel_raw_samples_unique_sample') THEN
        ALTER TABLE accel_raw_samples
            ADD CONSTRAINT accel_raw_samples_unique_sample UNIQUE (device_id, time, sample_index);
    END IF;
END $$;
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'blast_trigger_commands' AND column_name = 'requested_by') = 'text' THEN
        ALTER TABLE blast_trigger_commands
            ALTER COLUMN requested_by TYPE BIGINT USING NULLIF(requested_by, '')::BIGINT;
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'blast_trigger_commands_requested_by_fkey') THEN
        ALTER TABLE blast_trigger_commands
            ADD CONSTRAINT blast_trigger_commands_requested_by_fkey
            FOREIGN KEY (requested_by) REFERENCES users(user_id);
    END IF;
END $$;
ALTER TABLE measurements SET (
    timescaledb.enable_columnstore, timescaledb.segmentby = 'site_id, quantity', timescaledb.orderby = 'time DESC'
);
CALL add_columnstore_policy('measurements', after => INTERVAL '30 days', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS measurements_site_time
    ON measurements (site_id, time DESC);
