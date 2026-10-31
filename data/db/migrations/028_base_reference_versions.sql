CREATE UNIQUE INDEX IF NOT EXISTS idx_base_ref_ver_device_id_site ON public.devices(device_id,site_id);
CREATE TABLE IF NOT EXISTS public.base_reference_versions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES public.sites(site_id),
  base_device_id TEXT NOT NULL REFERENCES public.devices(device_id),
  version_no INTEGER NOT NULL CHECK (version_no > 0),
  latitude_deg DOUBLE PRECISION NOT NULL CHECK (latitude_deg BETWEEN -90 AND 90),
  longitude_deg DOUBLE PRECISION NOT NULL CHECK (longitude_deg BETWEEN -180 AND 180),
  ellipsoidal_height_m DOUBLE PRECISION NOT NULL CHECK (ellipsoidal_height_m > '-Infinity'::double precision AND ellipsoidal_height_m < 'Infinity'::double precision),
  vertical_datum TEXT NOT NULL DEFAULT 'ELLIPSOIDAL_WGS84' CHECK (vertical_datum = 'ELLIPSOIDAL_WGS84'),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('PROVISIONAL_SPP','SURVEYED')),
  validation_state TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (validation_state IN ('UNVERIFIED','VALIDATED','REJECTED')),
  effective_from TIMESTAMPTZ NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (site_id, base_device_id, version_no),
  FOREIGN KEY (base_device_id,site_id) REFERENCES public.devices(device_id,site_id)
);
CREATE INDEX IF NOT EXISTS idx_base_ref_ver_timeline ON public.base_reference_versions(site_id,base_device_id,effective_from DESC,id DESC);
COMMENT ON TABLE public.base_reference_versions IS 'Append-only operator/admin submissions. No automatic updates to device_reference_position or operational PPK.';
