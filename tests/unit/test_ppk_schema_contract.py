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


def test_ppk_solution_records_migration_locks_unvalidated_v1_contract():
    sql = Path("data/db/migrations/022_ppk_solution_records.sql").read_text()
    assert "schema_version = 'ppk.solution.v1'" in sql
    assert "ellipsoidal_height_m" in sql
    assert "navigation_sha256" in sql
    assert "rtklib_config_sha256" in sql
    assert "validation_status IN ('unvalidated', 'validated')" in sql
    assert "DEFAULT 'unvalidated'" in sql


def test_fresh_schema_contains_ppk_solution_records():
    sql = Path("docker/initdb/001_full_schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ppk_solution_records" in sql
    assert "PRIMARY KEY (rover_device_id, time, schema_version)" in sql
