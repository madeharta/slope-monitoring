CREATE TABLE IF NOT EXISTS device_battery_cal (
    device_id TEXT PRIMARY KEY REFERENCES devices(device_id),
    battery_cal_m DOUBLE PRECISION,
    battery_cal_c DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO device_battery_cal (device_id, battery_cal_m, battery_cal_c, updated_at, updated_by)
SELECT d.device_id,
       MAX(CASE WHEN c.config_key = 'battery_cal_m' AND jsonb_typeof(c.config_value) = 'number' THEN (c.config_value #>> '{}')::double precision END),
       MAX(CASE WHEN c.config_key = 'battery_cal_c' AND jsonb_typeof(c.config_value) = 'number' THEN (c.config_value #>> '{}')::double precision END),
       MAX(c.updated_at),
       MAX(c.updated_by)
FROM devices d
JOIN device_config c ON c.device_id = d.device_id AND c.config_key IN ('battery_cal_m', 'battery_cal_c')
GROUP BY d.device_id
ON CONFLICT (device_id) DO UPDATE SET
    battery_cal_m = COALESCE(EXCLUDED.battery_cal_m, device_battery_cal.battery_cal_m),
    battery_cal_c = COALESCE(EXCLUDED.battery_cal_c, device_battery_cal.battery_cal_c),
    updated_at = GREATEST(device_battery_cal.updated_at, EXCLUDED.updated_at),
    updated_by = COALESCE(EXCLUDED.updated_by, device_battery_cal.updated_by);
DELETE FROM device_config WHERE config_key IN ('battery_cal_m', 'battery_cal_c');
