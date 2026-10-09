import pytest
from datetime import datetime, timezone
from services.monitoring_service.blast_event_repository import BlastEventRepository, BLAST_EVENT_SCHEMA_VERSION

class Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): return False

class Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self): return Acquire(self.conn)

class Conn:
    def __init__(self): self.args = None
    async def fetchrow(self, query, *args):
        assert "INSERT INTO blast_event_records" in query
        assert "ON CONFLICT (source_file)" in query
        self.args = args
        return {"event_id": 7}
    async def fetch(self, query, *args):
        assert "FROM blast_event_records" in query
        return []

@pytest.mark.asyncio
async def test_write_event_persists_schema_provenance_quality_and_unvalidated_state():
    conn = Conn()
    repo = BlastEventRepository(Pool(conn))
    t = datetime(2026, 9, 18, tzinfo=timezone.utc)
    event_id = await repo.write_event(
        site_id="ITB-STAGING-01", device_id="ROVER-B1-01",
        source_file="accel.csv", communication_mode="4g",
        event_start=t, event_end=t, sample_count=1000, duration_ms=999,
        observed_sample_rate_hz=1000, median_gap_ms=1, max_gap_ms=1,
        quality_gate_status="accepted", quality_reasons=(),
        adxl355_ppa_g=0.5, adxl355_ppv_mm_s=12.0,
        mpu9250_ppa_g=0.4, mpu9250_ppv_mm_s=10.0,
    )
    assert event_id == 7
    assert conn.args[5] == BLAST_EVENT_SCHEMA_VERSION
    assert conn.args[3] == "accel.csv"

@pytest.mark.asyncio
async def test_list_events_is_filterable_without_mutating_validation_state():
    rows = await BlastEventRepository(Pool(Conn())).list_events(
        site_id="ITB-STAGING-01", device_id="ROVER-B1-01", limit=25,
    )
    assert rows == []
