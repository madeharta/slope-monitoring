from pathlib import Path
def test_migration_018_enforces_only_current_upload_types_for_new_rows():
    sql = Path("data/db/migrations/018_current_upload_contract.sql").read_text()
    assert "CHECK (data_type IN ('gnss', 'accel')) NOT VALID" in sql
    assert "'position'" not in sql
def test_fresh_bootstrap_uses_current_upload_contract_and_revision_18():
    sql = Path("docker/initdb/001_full_schema.sql").read_text()
    assert "data_type       TEXT NOT NULL CHECK (data_type IN ('gnss', 'accel'))" in sql
    assert "data_type       TEXT NOT NULL CHECK (data_type IN ('gnss', 'position', 'accel'))" not in sql
    assert "VALUES (18) ON CONFLICT (version) DO NOTHING" in sql
