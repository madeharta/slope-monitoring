-- GNSS operational marker locations, distinct from surveyed references and displacement baselines.
-- Apply after checking migration number 027 is unused in target repository/database.
BEGIN;
CREATE TABLE IF NOT EXISTS public.gnss_device_operational_locations (
  device_id text PRIMARY KEY REFERENCES public.devices(device_id) ON DELETE CASCADE,
  latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  ellipsoidal_height_m double precision,
  observed_at timestamptz NOT NULL,
  calculated_at timestamptz NOT NULL DEFAULT now(),
  position_source text NOT NULL CHECK (position_source IN ('RTKLIB_SPP','RTKLIB_PPK')),
  quality_code integer,
  quality_status text NOT NULL CHECK (quality_status IN ('ACCEPTED_SPP','ACCEPTED_PPK_FIX','ACCEPTED_PPK_FLOAT')),
  accepted_solutions integer NOT NULL CHECK (accepted_solutions > 0),
  max_spread_m double precision CHECK (max_spread_m IS NULL OR max_spread_m >= 0),
  reference_epoch integer CHECK (reference_epoch IS NULL OR reference_epoch > 0),
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  CHECK (NOT (latitude = 0 AND longitude = 0))
);
CREATE INDEX IF NOT EXISTS idx_gnss_operational_location_observed_at
  ON public.gnss_device_operational_locations (observed_at DESC);
COMMIT;
