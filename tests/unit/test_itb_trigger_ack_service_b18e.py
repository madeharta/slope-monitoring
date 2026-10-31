from datetime import datetime, timezone

import pytest

from services.device_config_service.trigger_ack_service import (
    acknowledge_trigger_start,
)


class FakeConnection:
    def __init__(self, *, active, latest, fail_insert=False):
        self.active = active
        self.latest = latest
        self.fail_insert = fail_insert
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rolled_back = True
            self.executed.clear()
        else:
            self.committed = True
        return False

    async def fetchrow(self, query, *args):
        if "FROM device_config_pending" in query:
            return self.latest
        if "FROM device_config" in query:
            return self.active
        raise AssertionError("Unexpected SELECT")

    async def execute(self, query, *args):
        if "INSERT INTO blast_trigger_acks" in query and self.fail_insert:
            raise RuntimeError("Simulated INSERT failure")
        self.executed.append((query, args))
        return "UPDATE 1"


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return self.connection


def make_connection(value=1, acked_at=None, fail_insert=False):
    return FakeConnection(
        active={"config_value": value},
        latest={
            "id": 17,
            "config_value": value,
            "acked_at": acked_at,
        },
        fail_insert=fail_insert,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, 1])
async def test_arm_disarm_updates_pending_and_inserts_history(value):
    conn = make_connection(value)
    device_time = datetime(2026, 10, 27, 18, 0, 0)

    accepted = await acknowledge_trigger_start(
        FakePool(conn),
        device_id="BASE-01",
        trigger_start=value,
        device_role="base",
        iccid="-1",
        device_version="1.0.0",
        device_timestamp_utc=device_time,
    )

    assert accepted is True
    assert conn.committed
    assert len(conn.executed) == 2

    update_sql, update_args = conn.executed[0]
    insert_sql, insert_args = conn.executed[1]

    assert "UPDATE device_config_pending" in update_sql
    assert update_args[0] == 17
    assert isinstance(update_args[1], datetime)

    assert "INSERT INTO blast_trigger_acks" in insert_sql
    assert insert_args[0] == "BASE-01"
    assert insert_args[1] == 17
    assert insert_args[2] == value
    assert insert_args[3] == device_time
    assert insert_args[5:] == ("base", "-1", "1.0.0")


@pytest.mark.asyncio
async def test_retry_preserves_acked_at_and_adds_history():
    original = datetime(2026, 10, 27, tzinfo=timezone.utc)
    conn = make_connection(1, acked_at=original)

    accepted = await acknowledge_trigger_start(
        FakePool(conn),
        device_id="BASE-01",
        trigger_start=1,
    )

    assert accepted is True
    assert len(conn.executed) == 1
    assert "INSERT INTO blast_trigger_acks" in conn.executed[0][0]
    assert conn.latest["acked_at"] == original


@pytest.mark.asyncio
async def test_stale_ack_rejected_without_history():
    conn = make_connection(1)

    accepted = await acknowledge_trigger_start(
        FakePool(conn),
        device_id="BASE-01",
        trigger_start=0,
    )

    assert accepted is False
    assert conn.executed == []


@pytest.mark.asyncio
async def test_latest_pending_mismatch_rejected():
    conn = make_connection(1)
    conn.latest["config_value"] = 0

    accepted = await acknowledge_trigger_start(
        FakePool(conn),
        device_id="BASE-01",
        trigger_start=1,
    )

    assert accepted is False
    assert conn.executed == []


@pytest.mark.asyncio
async def test_no_active_config_rejected():
    conn = make_connection()
    conn.active = None

    accepted = await acknowledge_trigger_start(
        FakePool(conn),
        device_id="BASE-01",
        trigger_start=1,
    )

    assert accepted is False
    assert conn.executed == []


@pytest.mark.asyncio
async def test_history_insert_failure_rolls_back():
    conn = make_connection(1, fail_insert=True)

    with pytest.raises(RuntimeError, match="Simulated INSERT failure"):
        await acknowledge_trigger_start(
            FakePool(conn),
            device_id="BASE-01",
            trigger_start=1,
        )

    assert conn.rolled_back is True
    assert conn.committed is False
    assert conn.executed == []


@pytest.mark.asyncio
async def test_empty_device_timestamp_is_null():
    conn = make_connection(0)

    accepted = await acknowledge_trigger_start(
        FakePool(conn),
        device_id="BASE-01",
        trigger_start=0,
        device_timestamp_utc=None,
    )

    assert accepted is True
    insert_args = conn.executed[-1][1]
    assert insert_args[3] is None
