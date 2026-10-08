ALTER TABLE devices ADD COLUMN IF NOT EXISTS label TEXT;
COMMENT ON COLUMN devices.label IS
  'Nama tampilan opsional, terpisah dari device_id (yang immutable/dipakai FK). NULL berarti UI fallback ke device_id apa adanya.';
