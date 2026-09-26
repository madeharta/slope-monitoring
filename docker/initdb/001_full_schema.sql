BEGIN;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE TABLE IF NOT EXISTS sites (
    site_id text PRIMARY KEY,
    name    text NOT NULL,
    lat     double precision NOT NULL,
    lon     double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    device_id   text PRIMARY KEY,
    device_type text NOT NULL,
    site_id     text NOT NULL REFERENCES sites (site_id),
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz
);
CREATE TABLE IF NOT EXISTS measurements (
    time         timestamptz      NOT NULL,
    device_id    text             NOT NULL,
    site_id      text             NOT NULL,
    quantity     text             NOT NULL,
    value        double precision,
    unit         text             NOT NULL,
    depth_cm     double precision,
    quality_flag text             NOT NULL DEFAULT 'ok',
    received_at  timestamptz      NOT NULL,
    latency_ms   double precision
);
SELECT create_hypertable('measurements', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS measurements_device_time
    ON measurements (device_id, time DESC);
CREATE INDEX IF NOT EXISTS measurements_quantity_time
    ON measurements (quantity, time DESC);
INSERT INTO sites (site_id, name, lat, lon) VALUES
    ('lereng-a', 'Slope A (Depok)', -6.3643, 106.8290),
    ('lereng-b', 'Slope B (Bogor)', -6.5950, 106.8060),
    ('lereng-c', 'Slope C (Puncak)', -6.7000, 106.9800),
    ('lereng-d', 'Slope D (Sukabumi)', -6.9200, 106.9270),
    ('lereng-e', 'Slope E (Megamendung)', -6.6500, 106.8900),
    ('lereng-f', 'Slope F (Cianjur)', -6.8170, 107.1425)
ON CONFLICT (site_id) DO NOTHING;
INSERT INTO sites (site_id, name, lat, lon) VALUES
    ('lereng-load', 'Load-test synthetic site', -6.6000, 106.9000)
ON CONFLICT (site_id) DO NOTHING;
CREATE TABLE IF NOT EXISTS gnss_raw_samples (
    time                TIMESTAMPTZ NOT NULL,
    device_id           TEXT NOT NULL REFERENCES devices(device_id),
    raw_payload_base64  TEXT NOT NULL,
    file_name           TEXT
);
SELECT create_hypertable('gnss_raw_samples', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
CREATE INDEX IF NOT EXISTS gnss_raw_device_time ON gnss_raw_samples (device_id, time DESC);
CREATE TABLE IF NOT EXISTS accel_raw_samples (
    time                TIMESTAMPTZ NOT NULL,
    device_id           TEXT NOT NULL REFERENCES devices(device_id),
    sample_index        INTEGER NOT NULL,
    adxl355_x_mps2      REAL NOT NULL,
    adxl355_y_mps2      REAL NOT NULL,
    adxl355_z_mps2      REAL NOT NULL,
    mpu9250_x_mps2      REAL NOT NULL,
    mpu9250_y_mps2      REAL NOT NULL,
    mpu9250_z_mps2      REAL NOT NULL,
    blast_command_id    BIGINT
);
SELECT create_hypertable('accel_raw_samples', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 hour');
CREATE INDEX IF NOT EXISTS accel_raw_device_time ON accel_raw_samples (device_id, time DESC);
CREATE TABLE IF NOT EXISTS device_config (
    device_id       TEXT REFERENCES devices(device_id),
    config_key      TEXT NOT NULL,
    config_value    JSONB NOT NULL,
    updated_by      TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, config_key)
);
CREATE TABLE IF NOT EXISTS device_battery_cal (
    device_id TEXT PRIMARY KEY REFERENCES devices(device_id),
    battery_cal_m DOUBLE PRECISION,
    battery_cal_c DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
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
    data_type       TEXT NOT NULL CHECK (data_type IN ('gnss', 'accel')),
    upload_origin   TEXT NOT NULL DEFAULT 'device_auto'
                     CHECK (upload_origin IN ('device_auto', 'manual_technician')),
    sequence_number INTEGER,
    record_count    INTEGER,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    communication_mode TEXT CHECK (communication_mode IS NULL OR communication_mode IN ('4g', 'lora')),
    processing_status TEXT NOT NULL DEFAULT 'processed' CHECK (processing_status IN ('received', 'processing', 'processed', 'failed')),
    processing_attempts INTEGER NOT NULL DEFAULT 1 CHECK (processing_attempts >= 1),
    processing_started_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS file_uploads_communication_mode_received_idx ON file_uploads (communication_mode, received_at DESC);
CREATE INDEX IF NOT EXISTS file_uploads_processing_status_received_idx ON file_uploads (processing_status, received_at DESC);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'gnss_raw_samples_file_name_fkey') THEN
        ALTER TABLE gnss_raw_samples
            ADD CONSTRAINT gnss_raw_samples_file_name_fkey
            FOREIGN KEY (file_name) REFERENCES file_uploads(file_name);
    END IF;
END $$;
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
CREATE TABLE IF NOT EXISTS users (
    user_id         BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
    mfa_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_secret      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at     TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor_user_id   BIGINT REFERENCES users(user_id),
    action          TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    old_value       JSONB,
    new_value       JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_target ON audit_log (target_type, target_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_actor ON audit_log (actor_user_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS device_reference_position (
    device_id       TEXT PRIMARY KEY REFERENCES devices(device_id),
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    altitude_m      DOUBLE PRECISION NOT NULL,
    surveyed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    surveyed_by     TEXT
);
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
CREATE INDEX IF NOT EXISTS measurements_site_time
    ON measurements (site_id, time DESC);
CREATE OR REPLACE FUNCTION prevent_device_site_id_change() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.site_id IS DISTINCT FROM OLD.site_id THEN
        RAISE EXCEPTION
            'devices.site_id tidak boleh diubah (device %, site lama=%, site baru=%). '
            'Device pindah lokasi harus didaftarkan sebagai device_id baru, bukan edit site_id — '
            'lihat migrasi 008 untuk alasannya (mencegah measurements.site_id historis jadi stale).',
            OLD.device_id, OLD.site_id, NEW.site_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS devices_site_id_immutable ON devices;
CREATE TRIGGER devices_site_id_immutable
    BEFORE UPDATE ON devices
    FOR EACH ROW EXECUTE FUNCTION prevent_device_site_id_change();
CREATE OR REPLACE FUNCTION validate_audit_log_target() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.target_type = 'device' THEN
        IF NOT EXISTS (SELECT 1 FROM devices WHERE device_id = NEW.target_id) THEN
            RAISE EXCEPTION 'audit_log: target_type=device, tapi device_id % tidak ada di tabel devices', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'model_version' THEN
        IF NOT EXISTS (SELECT 1 FROM model_versions WHERE version_id = NEW.target_id) THEN
            RAISE EXCEPTION 'audit_log: target_type=model_version, tapi version_id % tidak ada di tabel model_versions', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'blast_command' THEN
        IF NOT EXISTS (SELECT 1 FROM blast_trigger_commands WHERE command_id = NEW.target_id::BIGINT) THEN
            RAISE EXCEPTION 'audit_log: target_type=blast_command, tapi command_id % tidak ada', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'user' THEN
        IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = NEW.target_id::BIGINT) THEN
            RAISE EXCEPTION 'audit_log: target_type=user, tapi user_id % tidak ada', NEW.target_id;
        END IF;
    ELSE
        RAISE EXCEPTION
            'audit_log: target_type "%" tidak dikenal validator (migrasi 008) — '
            'tambahkan cabang baru di validate_audit_log_target() sebelum memakai target_type ini',
            NEW.target_type;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_validate_target ON audit_log;
CREATE TRIGGER audit_log_validate_target
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION validate_audit_log_target();
SELECT add_retention_policy('accel_raw_samples', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('gnss_raw_samples', INTERVAL '2 years', if_not_exists => TRUE);
DELETE FROM measurements
WHERE (tableoid, ctid) IN (
    SELECT tableoid, ctid FROM (
        SELECT tableoid, ctid,
               ROW_NUMBER() OVER (PARTITION BY device_id, quantity, time ORDER BY tableoid, ctid) AS rn
        FROM measurements
    ) ranked
    WHERE ranked.rn > 1
);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'measurements_unique_reading') THEN
        ALTER TABLE measurements
            ADD CONSTRAINT measurements_unique_reading UNIQUE (device_id, quantity, time);
    END IF;
END $$;
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT count(*) INTO orphan_count FROM devices
    WHERE site_id IN ('lereng-a','lereng-b','lereng-c','lereng-d','lereng-e','lereng-f','lereng-load');
    IF orphan_count > 0 THEN
        RAISE EXCEPTION
            'Batal hapus: % device masih terdaftar ke site dummy — cek dulu manual sebelum lanjut',
            orphan_count;
    END IF;
END $$;
DELETE FROM sites
WHERE site_id IN ('lereng-a', 'lereng-b', 'lereng-c', 'lereng-d', 'lereng-e', 'lereng-f', 'lereng-load');
CREATE OR REPLACE FUNCTION validate_audit_log_target() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.target_type = 'device' THEN
        IF NOT EXISTS (SELECT 1 FROM devices WHERE device_id = NEW.target_id) THEN
            RAISE EXCEPTION 'audit_log: target_type=device, tapi device_id % tidak ada di tabel devices', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'model_version' THEN
        IF NOT EXISTS (SELECT 1 FROM model_versions WHERE version_id = NEW.target_id) THEN
            RAISE EXCEPTION 'audit_log: target_type=model_version, tapi version_id % tidak ada di tabel model_versions', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'blast_command' THEN
        IF NOT EXISTS (SELECT 1 FROM blast_trigger_commands WHERE command_id = NEW.target_id::BIGINT) THEN
            RAISE EXCEPTION 'audit_log: target_type=blast_command, tapi command_id % tidak ada', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'user' THEN
        IF NEW.target_id !~ '@' THEN
            RAISE EXCEPTION 'audit_log: target_type=user, tapi target_id "%" tidak terlihat seperti email', NEW.target_id;
        END IF;
    ELSIF NEW.target_type = 'site' THEN
        IF NOT EXISTS (SELECT 1 FROM sites WHERE site_id = NEW.target_id) THEN
            RAISE EXCEPTION 'audit_log: target_type=site, tapi site_id % tidak ada di tabel sites', NEW.target_id;
        END IF;
    ELSE
        RAISE EXCEPTION
            'audit_log: target_type "%" tidak dikenal validator (migrasi 008/010) — '
            'tambahkan cabang baru di validate_audit_log_target() sebelum memakai target_type ini',
            NEW.target_type;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION prevent_device_site_id_change() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.site_id IS DISTINCT FROM OLD.site_id THEN
        IF EXISTS (SELECT 1 FROM measurements WHERE device_id = OLD.device_id LIMIT 1) THEN
            RAISE EXCEPTION
                'devices.site_id tidak boleh diubah untuk device % — device ini SUDAH punya riwayat data di site %. '
                'Device pindah lokasi harus didaftarkan sebagai device_id baru, bukan edit site_id di tempat '
                '(lihat migrasi 008/011 untuk alasannya).',
                OLD.device_id, OLD.site_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS label TEXT;
COMMENT ON COLUMN devices.label IS
  'Nama tampilan opsional, terpisah dari device_id (yang immutable/dipakai FK). NULL berarti UI fallback ke device_id apa adanya.';
CREATE TABLE IF NOT EXISTS rover_displacement_baselines (
    device_id TEXT PRIMARY KEY REFERENCES devices(device_id),
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    altitude_m DOUBLE PRECISION NOT NULL,
    horizontal_datum TEXT NOT NULL CHECK (horizontal_datum = 'WGS84'),
    vertical_datum TEXT NOT NULL CHECK (vertical_datum IN ('ELLIPSOIDAL_WGS84', 'MSL_CONFIRMED')),
    max_h_acc_m DOUBLE PRECISION NOT NULL CHECK (max_h_acc_m > 0 AND max_h_acc_m < 'Infinity'::double precision),
    source_document TEXT NOT NULL CHECK (length(trim(source_document)) > 0),
    surveyed_at TIMESTAMPTZ NOT NULL,
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    approved_at TIMESTAMPTZ NOT NULL
);
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
CREATE TABLE IF NOT EXISTS schema_bootstrap_version (
  version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO schema_bootstrap_version(version) VALUES (18) ON CONFLICT (version) DO NOTHING;
COMMIT;
