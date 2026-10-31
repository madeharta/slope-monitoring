-- Batch 13.1 DRAFT — experimental QA-only. DBA review and restorable backup REQUIRED.
-- Never run automatically during container startup. No operational displacement writes.
BEGIN;
CREATE TABLE IF NOT EXISTS public.ppk_qa_jobs (
 site_id text NOT NULL,
 rover_device_id text NOT NULL,
 window_start_utc timestamptz NOT NULL,
 input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^[a-f0-9]{64}$'),
 status text NOT NULL CHECK(status IN ('RUNNING','COMPLETED','FAILED')),
 attempts integer NOT NULL DEFAULT 1 CHECK(attempts >= 1),
 solution_count integer NOT NULL DEFAULT 0 CHECK(solution_count >= 0),
 last_error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(site_id,rover_device_id,window_start_utc,input_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_ppk_qa_jobs_updated ON public.ppk_qa_jobs(status,updated_at);
CREATE TABLE IF NOT EXISTS public.ppk_qa_experimental_solutions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_pos_sha256 text NOT NULL CHECK(source_pos_sha256 ~ '^[a-f0-9]{64}$'),
 site_id text NOT NULL,
 base_device_id text NOT NULL,
 rover_device_id text NOT NULL,
 gps_week integer NOT NULL CHECK(gps_week >= 0),
 gps_tow_s double precision NOT NULL CHECK(gps_tow_s >= 0 AND gps_tow_s < 604800),
 latitude_deg double precision NOT NULL CHECK(latitude_deg BETWEEN -90 AND 90),
 longitude_deg double precision NOT NULL CHECK(longitude_deg BETWEEN -180 AND 180),
 ellipsoidal_height_m double precision NOT NULL,
 rtklib_quality integer NOT NULL,
 satellite_count integer NOT NULL CHECK(satellite_count >= 0),
 sdn_m double precision,
 sde_m double precision,
 sdu_m double precision,
 sdne_m double precision,
 sdeu_m double precision,
 sdun_m double precision,
 age_s double precision,
 ratio double precision,
 reference_type text NOT NULL DEFAULT 'PROVISIONAL_SPP' CHECK(reference_type='PROVISIONAL_SPP'),
 validation_status text NOT NULL DEFAULT 'unvalidated' CHECK(validation_status='unvalidated'),
 schema_version text NOT NULL DEFAULT 'ppk.qa.solution.v1' CHECK(schema_version='ppk.qa.solution.v1'),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(site_id,rover_device_id,gps_week,gps_tow_s)
);
CREATE INDEX IF NOT EXISTS idx_ppk_qa_solutions_site_rover_epoch ON public.ppk_qa_experimental_solutions(site_id,rover_device_id,gps_week,gps_tow_s);
-- Privileges are deliberately NOT granted to application/API users here; DBA must
-- approve dedicated QA writer and read-only API grants separately.
COMMIT;
