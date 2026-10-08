from pathlib import Path

from services.ingestion_service.csv_validator import retained_upload_headers


def test_migration_020_retains_exact_original_payload_separately():
    sql = Path("data/db/migrations/020_upload_payload_retention.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS file_upload_payloads" in sql
    assert "payload         BYTEA NOT NULL" in sql
    assert "sha256          CHAR(64)" in sql
    assert "request_headers JSONB" in sql
    assert "REFERENCES file_uploads(file_name) ON DELETE CASCADE" in sql


def test_fresh_bootstrap_contains_upload_payload_retention_schema():
    sql = Path("docker/initdb/001_full_schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS file_upload_payloads" in sql
    assert "VALUES (20) ON CONFLICT (version) DO NOTHING" in sql


def test_retained_upload_headers_are_allowlisted_and_do_not_capture_credentials():
    headers = {
        "X-Communication-Mode": "4g",
        "X-Device-Id": "ROVER-B1-01",
        "X-Device-Role": "rover",
        "X-Data-Type": "gnss",
        "X-File-Name": "gnss_ROVER-B1-01_20260925_0900.csv",
        "X-Record-Count": "20",
        "X-Battery-Voltage": "12.4",
        "Authorization": "Bearer secret-token",
        "X-Api-Key": "secret-device-key",
        "Cookie": "session=secret",
    }
    retained = retained_upload_headers(headers)
    assert retained["X-Device-Id"] == "ROVER-B1-01"
    assert retained["X-Battery-Voltage"] == "12.4"
    assert "Authorization" not in retained
    assert "X-Api-Key" not in retained
    assert "Cookie" not in retained


def test_upload_download_is_operator_gated_and_audited():
    source = Path("apps/api/routers/v1/uploads.py").read_text()
    assert 'Depends(require_role("operator"))' in source
    assert 'action="upload.download_original"' in source
    assert '"Cache-Control": "private, no-store"' in source


def test_migration_021_allows_file_upload_audit_targets():
    sql = Path("data/db/migrations/021_audit_file_upload_target.sql").read_text()
    assert "ELSIF NEW.target_type = 'file_upload'" in sql
    assert "SELECT 1 FROM file_uploads WHERE file_name = NEW.target_id" in sql
    assert "VALUES (21)" in sql


def test_fresh_bootstrap_allows_file_upload_audit_targets():
    sql = Path("docker/initdb/001_full_schema.sql").read_text()
    assert "ELSIF NEW.target_type = 'file_upload'" in sql
    assert "SELECT 1 FROM file_uploads WHERE file_name = NEW.target_id" in sql
    assert "VALUES (21) ON CONFLICT (version) DO NOTHING" in sql
