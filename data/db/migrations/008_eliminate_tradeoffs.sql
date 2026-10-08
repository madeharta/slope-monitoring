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
