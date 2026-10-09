ALTER TABLE ppk_solution_records
    ADD COLUMN IF NOT EXISTS vertical_datum TEXT NOT NULL DEFAULT 'ELLIPSOIDAL_WGS84',
    ADD COLUMN IF NOT EXISTS processing_engine TEXT NOT NULL DEFAULT 'RTKLIB',
    ADD COLUMN IF NOT EXISTS base_rawx_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS rover_rawx_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS base_obs_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS rover_obs_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS normalized_navigation_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS convbin_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS rnx2rtkp_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS solution_pos_sha256 TEXT;

DO $do$
DECLARE
    constraint_name TEXT;
    constraint_expr TEXT;
BEGIN
    FOR constraint_name, constraint_expr IN
        VALUES
            ('ppk_solution_vertical_datum_check', $expr$vertical_datum = 'ELLIPSOIDAL_WGS84'$expr$),
            ('ppk_solution_processing_engine_check', $expr$processing_engine = 'RTKLIB'$expr$),
            ('ppk_solution_base_rawx_sha256_check', $$base_rawx_sha256 IS NULL OR base_rawx_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_rover_rawx_sha256_check', $$rover_rawx_sha256 IS NULL OR rover_rawx_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_base_obs_sha256_check', $$base_obs_sha256 IS NULL OR base_obs_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_rover_obs_sha256_check', $$rover_obs_sha256 IS NULL OR rover_obs_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_normalized_navigation_sha256_check', $$normalized_navigation_sha256 IS NULL OR normalized_navigation_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_convbin_sha256_check', $$convbin_sha256 IS NULL OR convbin_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_rnx2rtkp_sha256_check', $$rnx2rtkp_sha256 IS NULL OR rnx2rtkp_sha256 ~ '^[0-9a-f]{64}$'$$),
            ('ppk_solution_solution_pos_sha256_check', $$solution_pos_sha256 IS NULL OR solution_pos_sha256 ~ '^[0-9a-f]{64}$'$$)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = constraint_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE ppk_solution_records ADD CONSTRAINT %I CHECK (%s)',
                constraint_name,
                constraint_expr
            );
        END IF;
    END LOOP;
END $do$;

COMMENT ON TABLE ppk_solution_records IS
    'Technical PPK solution epochs using ppk.solution.v1. Ellipsoidal coordinates and reproducibility provenance are retained; validation remains unvalidated until production geodetic acceptance.';

DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version) VALUES (25) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
