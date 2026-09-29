from pathlib import Path


def test_migration_019_requires_explicit_ellipsoidal_base_reference_without_relabeling_legacy_rows():
    sql = Path("data/db/migrations/019_ppk_ellipsoidal_reference.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS vertical_datum TEXT" in sql
    assert "vertical_datum IS NULL OR vertical_datum = 'ELLIPSOIDAL_WGS84'" in sql
    assert "CHECK (vertical_datum = 'ELLIPSOIDAL_WGS84') NOT VALID" in sql
    assert "UPDATE device_reference_position" not in sql


def test_fresh_schema_accepts_only_ellipsoidal_rover_baselines():
    sql = Path("docker/initdb/001_full_schema.sql").read_text()
    assert "vertical_datum TEXT NOT NULL CHECK (vertical_datum = 'ELLIPSOIDAL_WGS84')" in sql
