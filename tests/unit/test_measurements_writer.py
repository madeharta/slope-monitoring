from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from services.monitoring_service.measurements_writer import MeasurementsWriter
class _FakeConn:
    def __init__(self, sink: list) -> None:
        self.sink = sink
    async def executemany(self, query, seq):
        self.sink.extend(seq)
class _FakeAcquireCtx:
    def __init__(self, conn) -> None:
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        return False
class _FakePool:
    def __init__(self, sink: list) -> None:
        self.sink = sink
    def acquire(self):
        return _FakeAcquireCtx(_FakeConn(self.sink))
def test_write_displacement_never_sends_null_unit():
    sink: list = []
    writer = MeasurementsWriter(_FakePool(sink))
    asyncio.run(
        writer.write_displacement(
            device_id="ROVER-01", site_id="SITE-A", timestamp_utc=datetime(2026, 9, 18, tzinfo=timezone.utc),
            de_mm=1.0, dn_mm=2.0, du_mm=3.0, total_mm=4.0, h_acc_m=0.02, gnss_fix_type=4,
        )
    )
    assert len(sink) == 6
    for row in sink:
        _time, _device_id, _site_id, quantity, _value, unit, _source_kind, _source_file, _validation_status = row
        assert unit is not None, f"quantity '{quantity}' has unit=None — violates measurements.unit NOT NULL"
def test_write_vibration_never_sends_null_unit():
    sink: list = []
    writer = MeasurementsWriter(_FakePool(sink))
    asyncio.run(
        writer.write_vibration(
            device_id="ROVER-01", site_id="SITE-A", timestamp_utc=datetime(2026, 9, 18, tzinfo=timezone.utc),
            ppa_g=1.0, ppv_mm_s=2.0,
        )
    )
    assert len(sink) == 2
    for row in sink:
        _time, _device_id, _site_id, quantity, _value, unit, _source_kind, _source_file, _validation_status = row
        assert unit is not None, f"quantity '{quantity}' has unit=None — violates measurements.unit NOT NULL"
def test_write_tilt_never_sends_null_unit():
    sink: list = []
    writer = MeasurementsWriter(_FakePool(sink))
    asyncio.run(
        writer.write_tilt(
            device_id="ROVER-01", site_id="SITE-A", timestamp_utc=datetime(2026, 9, 18, tzinfo=timezone.utc),
            tilt_x_deg=1.2, tilt_y_deg=-0.5,
        )
    )
    assert len(sink) == 2
    quantities = {row[3] for row in sink}
    assert quantities == {"tilt_x", "tilt_y"}
    for row in sink:
        _time, _device_id, _site_id, quantity, _value, unit, _source_kind, _source_file, _validation_status = row
        assert unit == "deg", f"quantity '{quantity}' has unit='{unit}', expected 'deg'"
