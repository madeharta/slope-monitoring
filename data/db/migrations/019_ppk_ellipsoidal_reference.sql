ALTER TABLE device_reference_position
    ADD COLUMN IF NOT EXISTS vertical_datum TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'device_reference_position_vertical_datum_check'
          AND conrelid = 'device_reference_position'::regclass
    ) THEN
        ALTER TABLE device_reference_position
            ADD CONSTRAINT device_reference_position_vertical_datum_check
            CHECK (vertical_datum IS NULL OR vertical_datum = 'ELLIPSOIDAL_WGS84');
    END IF;
END $$;

COMMENT ON COLUMN device_reference_position.vertical_datum IS
    'Explicit vertical datum for surveyed base coordinates. NULL means legacy/unconfirmed and blocks PPK; current accepted value is ELLIPSOIDAL_WGS84.';

COMMENT ON COLUMN device_reference_position.altitude_m IS
    'Surveyed base ellipsoidal height in meters only when vertical_datum=ELLIPSOIDAL_WGS84.';

ALTER TABLE rover_displacement_baselines
    DROP CONSTRAINT IF EXISTS rover_displacement_baselines_vertical_datum_check;

ALTER TABLE rover_displacement_baselines
    ADD CONSTRAINT rover_displacement_baselines_vertical_datum_check
    CHECK (vertical_datum = 'ELLIPSOIDAL_WGS84') NOT VALID;

COMMENT ON COLUMN rover_displacement_baselines.vertical_datum IS
    'Current contract requires ELLIPSOIDAL_WGS84. Legacy MSL_CONFIRMED rows may remain historical but are rejected by processing and new writes.';
