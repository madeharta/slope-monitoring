SELECT
    has_sequence_privilege(
        'landslidemon_api',
        'public.blast_trigger_timeout_events_id_seq',
        'USAGE'
    ) AS api_has_usage;
