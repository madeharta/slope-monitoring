CREATE TABLE IF NOT EXISTS rover_displacement_baselines (
    device_id TEXT PRIMARY KEY REFERENCES devices(device_id),
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    altitude_m DOUBLE PRECISION NOT NULL,
    horizontal_datum TEXT NOT NULL CHECK (horizontal_datum = 'WGS84'),
    vertical_datum TEXT NOT NULL CHECK (vertical_datum IN ('ELLIPSOIDAL_WGS84', 'MSL_CONFIRMED')),
    max_h_acc_m DOUBLE PRECISION NOT NULL CHECK (max_h_acc_m > 0 AND max_h_acc_m < 'Infinity'::double precision),
    source_document TEXT NOT NULL CHECK (length(trim(source_document)) > 0),
    surveyed_at TIMESTAMPTZ NOT NULL,
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    approved_at TIMESTAMPTZ NOT NULL
);
