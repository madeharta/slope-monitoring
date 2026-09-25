CREATE TABLE IF NOT EXISTS gnss_raw_samples (
    time                TIMESTAMPTZ NOT NULL,
    device_id           TEXT NOT NULL REFERENCES devices(device_id),
    raw_payload_base64  TEXT NOT NULL,
    file_name           TEXT
);
SELECT create_hypertable('gnss_raw_samples', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
CREATE INDEX IF NOT EXISTS gnss_raw_device_time ON gnss_raw_samples (device_id, time DESC);
CREATE TABLE IF NOT EXISTS accel_raw_samples (
    time                TIMESTAMPTZ NOT NULL,
    device_id           TEXT NOT NULL REFERENCES devices(device_id),
    sample_index        INTEGER NOT NULL,
    adxl355_x_mps2      REAL NOT NULL,
    adxl355_y_mps2      REAL NOT NULL,
    adxl355_z_mps2      REAL NOT NULL,
    mpu9250_x_mps2      REAL NOT NULL,
    mpu9250_y_mps2      REAL NOT NULL,
    mpu9250_z_mps2      REAL NOT NULL,
    blast_command_id    BIGINT
);
SELECT create_hypertable('accel_raw_samples', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 hour');
CREATE INDEX IF NOT EXISTS accel_raw_device_time ON accel_raw_samples (device_id, time DESC);
ALTER TABLE gnss_raw_samples SET (
    timescaledb.enable_columnstore, timescaledb.segmentby = 'device_id', timescaledb.orderby = 'time DESC'
);
CALL add_columnstore_policy('gnss_raw_samples', after => INTERVAL '30 days', if_not_exists => TRUE);
ALTER TABLE accel_raw_samples SET (
    timescaledb.enable_columnstore, timescaledb.segmentby = 'device_id', timescaledb.orderby = 'time DESC'
);
CALL add_columnstore_policy('accel_raw_samples', after => INTERVAL '30 days', if_not_exists => TRUE);
