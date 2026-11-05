-- MAGRIS LOCAL-DEV battery 4G backfill PREVIEW (READ ONLY).
-- Execute through docker exec -i slope-landslide-db-1 psql -U slope -d slope_iot ...
-- Raw values are retained, including 0 V. Non-numeric header values are not fabricated.
WITH eligible AS (
 SELECT f.device_id, f.file_name, f.received_at, d.site_id,
        NULLIF(BTRIM(p.request_headers->>'X-Battery-Voltage'), '') AS raw_voltage
 FROM public.file_uploads f
 JOIN public.file_upload_payloads p ON p.file_name=f.file_name
 JOIN public.devices d ON d.device_id=f.device_id
 WHERE f.communication_mode='4g'
), numeric_source AS (
 SELECT * FROM eligible
 WHERE raw_voltage ~ '^[+]?[0-9]+([.][0-9]+)?$'
), deduped AS (
 SELECT DISTINCT ON (device_id, received_at)
   device_id, site_id, file_name, received_at, raw_voltage::double precision AS voltage
 FROM numeric_source ORDER BY device_id, received_at, file_name
)
SELECT device_id, COUNT(*) AS valid_source_rows,
 COUNT(*) FILTER (WHERE voltage=0) AS zero_voltage_rows,
 COUNT(*) FILTER (WHERE NOT EXISTS (
   SELECT 1 FROM public.measurements m
   WHERE m.device_id=deduped.device_id AND m.quantity='battery_voltage' AND m.time=deduped.received_at
 )) AS not_yet_persisted,
 MIN(received_at) AS first_source_at, MAX(received_at) AS last_source_at
FROM deduped GROUP BY device_id ORDER BY device_id;
