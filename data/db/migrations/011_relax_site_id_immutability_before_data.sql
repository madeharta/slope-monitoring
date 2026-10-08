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
