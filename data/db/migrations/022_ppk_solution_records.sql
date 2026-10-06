CREATE TABLE IF NOT EXISTS ppk_solution_records (
    time                    TIMESTAMPTZ NOT NULL,
    site_id                 TEXT NOT NULL REFERENCES sites(site_id),
    base_device_id          TEXT NOT NULL REFERENCES devices(device_id),
    rover_device_id         TEXT NOT NULL REFERENCES devices(device_id),
    schema_version          TEXT NOT NULL,
    latitude                DOUBLE PRECISION NOT NULL,
    longitude               DOUBLE PRECISION NOT NULL,
    ellipsoidal_height_m    DOUBLE PRECISION NOT NULL,
    displacement_e_mm       DOUBLE PRECISION NOT NULL,
    displacement_n_mm       DOUBLE PRECISION NOT NULL,
    displacement_u_mm       DOUBLE PRECISION NOT NULL,
    displacement_total_mm   DOUBLE PRECISION NOT NULL,
    h_acc_m                 DOUBLE PRECISION NOT NULL,
    rtklib_quality          INTEGER NOT NULL,
    rtklib_ns               INTEGER NOT NULL,
    rtklib_age_s            DOUBLE PRECISION,
    rtklib_ratio            DOUBLE PRECISION,
    rtklib_sdn_m            DOUBLE PRECISION NOT NULL,
    rtklib_sde_m            DOUBLE PRECISION NOT NULL,
    rtklib_sdu_m            DOUBLE PRECISION NOT NULL,
    navigation_sha256       TEXT NOT NULL,
    navigation_source_url   TEXT,
    navigation_provider     TEXT,
    navigation_cache_hit    BOOLEAN NOT NULL DEFAULT FALSE,
    rtklib_config_sha256    TEXT,
    quality_gate_status     TEXT NOT NULL DEFAULT 'accepted',
    validation_status       TEXT NOT NULL DEFAULT 'unvalidated',
    processed_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rover_device_id, time, schema_version),
    CONSTRAINT ppk_solution_schema_version_check
        CHECK (schema_version = 'ppk.solution.v1'),
    CONSTRAINT ppk_solution_quality_check
        CHECK (rtklib_quality BETWEEN 1 AND 6),
    CONSTRAINT ppk_solution_quality_gate_check
        CHECK (quality_gate_status IN ('accepted', 'rejected')),
    CONSTRAINT ppk_solution_validation_check
        CHECK (validation_status IN ('unvalidated', 'validated')),
    CONSTRAINT ppk_solution_navigation_sha256_check
        CHECK (navigation_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ppk_solution_config_sha256_check
        CHECK (rtklib_config_sha256 IS NULL OR rtklib_config_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS ppk_solution_site_time_idx
    ON ppk_solution_records (site_id, time DESC);
CREATE INDEX IF NOT EXISTS ppk_solution_rover_time_idx
    ON ppk_solution_records (rover_device_id, time DESC);

COMMENT ON TABLE ppk_solution_records IS
    'Accepted technical PPK solution epochs with RTKLIB and navigation provenance. Validation remains unvalidated until production geodetic acceptance.';

DO $$
BEGIN
    IF to_regclass('public.schema_bootstrap_version') IS NOT NULL THEN
        INSERT INTO schema_bootstrap_version(version) VALUES (22) ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;
