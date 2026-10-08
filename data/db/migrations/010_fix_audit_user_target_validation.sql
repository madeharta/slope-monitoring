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
