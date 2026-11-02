-- Restore the minimum sequence privilege required by the API role.
-- Incident: GNSS uploads returned HTTP 500 (InsufficientPrivilegeError).
--
-- Execute with the database migration owner / privileged role.
-- Does not modify existing records or sequence values.

DO $$
BEGIN
    IF to_regclass('public.blast_trigger_timeout_events_id_seq') IS NULL THEN
        RAISE EXCEPTION
            'Missing sequence public.blast_trigger_timeout_events_id_seq; apply migration 031 first';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'landslidemon_api'
    ) THEN
        RAISE EXCEPTION
            'Required database role landslidemon_api does not exist';
    END IF;

    GRANT USAGE ON SEQUENCE
        public.blast_trigger_timeout_events_id_seq
    TO landslidemon_api;
END
$$;
