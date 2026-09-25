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
