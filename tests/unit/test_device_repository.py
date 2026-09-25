from __future__ import annotations
import asyncio
import pytest
from common.errors import NotFoundError
from services.device_service.device_repository import DeviceRepository, NewDevice
class _FakeConn:
    def __init__(self, sink: list, fetchval_result=None) -> None:
        self._sink = sink
        self._fetchval_result = fetchval_result
    async def execute(self, query, *args):
        self._sink.append((query, args))
        if "does-not-exist" in args:
            verb = "UPDATE" if query.strip().startswith("UPDATE") else "DELETE"
            return f"{verb} 0"
        verb = "UPDATE" if query.strip().startswith("UPDATE") else ("DELETE" if query.strip().startswith("DELETE") else "INSERT")
        return f"{verb} 1"
    async def fetchval(self, query, *args):
        return self._fetchval_result
class _FakeAcquireCtx:
    def __init__(self, conn) -> None:
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        return False
class _FakePool:
    def __init__(self, sink: list, fetchval_result=None) -> None:
        self._sink = sink
        self._fetchval_result = fetchval_result
    def acquire(self):
        return _FakeAcquireCtx(_FakeConn(self._sink, self._fetchval_result))
def test_create_inserts_with_correct_fields():
    sink: list = []
    repo = DeviceRepository(_FakePool(sink))
    asyncio.run(repo.create(NewDevice(device_id="ROVER-03", device_type="gnss_rover", site_id="SITE-A")))
    assert len(sink) == 1
    query, args = sink[0]
    assert "INSERT INTO devices" in query
    assert args == ("ROVER-03", "gnss_rover", "SITE-A", None)
def test_create_inserts_with_explicit_label():
    sink: list = []
    repo = DeviceRepository(_FakePool(sink))
    asyncio.run(repo.create(NewDevice(device_id="ROVER-03", device_type="gnss_rover", site_id="SITE-A", label="Rover Uji A")))
    _query, args = sink[0]
    assert args == ("ROVER-03", "gnss_rover", "SITE-A", "Rover Uji A")
def test_delete_raises_not_found_when_zero_rows_affected():
    repo = DeviceRepository(_FakePool([]))
    with pytest.raises(NotFoundError):
        asyncio.run(repo.delete("does-not-exist"))
def test_delete_succeeds_for_existing_device():
    sink: list = []
    repo = DeviceRepository(_FakePool(sink))
    asyncio.run(repo.delete("ROVER-01"))
    assert len(sink) == 1
    assert "DELETE FROM devices" in sink[0][0]
def test_has_measurement_history_true_when_row_exists():
    repo = DeviceRepository(_FakePool([], fetchval_result=1))
    assert asyncio.run(repo.has_measurement_history("ROVER-01")) is True
def test_has_measurement_history_false_when_no_row():
    repo = DeviceRepository(_FakePool([], fetchval_result=None))
    assert asyncio.run(repo.has_measurement_history("ROVER-01")) is False
def test_update_builds_only_the_fields_provided():
    fields, args = DeviceRepository._build_update_clause(device_type="gnss_base_v2", site_id=None)
    assert fields == ["device_type = $1"]
    assert args == ["gnss_base_v2"]
def test_update_clause_includes_both_fields_when_both_given():
    fields, args = DeviceRepository._build_update_clause(device_type="gnss_rover", site_id="SITE-B")
    assert fields == ["device_type = $1", "site_id = $2"]
    assert args == ["gnss_rover", "SITE-B"]
def test_update_clause_empty_when_nothing_given():
    fields, args = DeviceRepository._build_update_clause(device_type=None, site_id=None)
    assert fields == [] and args == []
def test_update_clause_includes_label_when_label_given_true():
    fields, args = DeviceRepository._build_update_clause(
        device_type=None, site_id=None, label="Rover 4G (ID belum dikonfigurasi ITB)", label_given=True,
    )
    assert fields == ["label = $1"]
    assert args == ["Rover 4G (ID belum dikonfigurasi ITB)"]
def test_update_clause_empty_label_string_becomes_null():
    fields, args = DeviceRepository._build_update_clause(device_type=None, site_id=None, label="", label_given=True)
    assert fields == ["label = $1"]
    assert args == [None]
def test_update_clause_label_not_touched_when_label_given_false():
    fields, args = DeviceRepository._build_update_clause(device_type="gnss_rover", site_id=None, label="diabaikan")
    assert fields == ["device_type = $1"]
    assert args == ["gnss_rover"]
