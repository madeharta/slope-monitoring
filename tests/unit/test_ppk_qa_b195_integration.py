import asyncio
import base64
import json
import struct
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts.ppk_qa_worker import run_once


def rawx_row(device_id, when, num_meas):
    payload = struct.pack(
        "<dHbBBBH", 100000.0, 2400, 18, num_meas, 1, 1, 0
    ) + bytes(32 * num_meas)

    frame = bytearray(
        b"\xb5\x62\x02\x15"
        + struct.pack("<H", len(payload))
        + payload
    )

    a = b = 0
    for x in frame[2:]:
        a = (a + x) & 255
        b = (b + a) & 255
    frame.extend((a, b))

    return {
        "time": when,
        "device_id": device_id,
        "raw_payload_base64": base64.b64encode(frame).decode(),
    }


def test_zero_measurement_base_skips_qa_job(
    monkeypatch, tmp_path, capsys
):
    when = datetime(2026, 10, 8, 11, 5, tzinfo=timezone.utc)

    rows = (
        [rawx_row("BASE-01", when, 0)]
        + [rawx_row("ROVER-B1-02", when, 4)]
    )

    class SourceDB:
        async def fetchrow(self, query, *args):
            return {"db": "slope_iot", "role": "ppk_qa_source_reader"}

        async def fetchval(self, query, *args):
            if "has_table_privilege" in query:
                if any(
                    privilege in query
                    for privilege in ("INSERT,UPDATE,DELETE",)
                ):
                    return False

                if "'SELECT'" in query:
                    return True

            raise AssertionError(
                "Unexpected source database privilege query"
            )

        async def execute(self, query, *args):
            return "OK"

        async def fetch(self, query, *args):
            return rows

        async def close(self):
            pass

    class WriterDB:
        async def fetchrow(self, query, *args):
            return {"db": "ppk_qa_biznet", "role": "ppk_qa_writer"}

        async def fetchval(self, query, *args):
            return True

        async def fetch(self, query, *args):
            return [
                {"column_name": column}
                for column in (
                    "source_pos_sha256 site_id base_device_id "
                    "rover_device_id gps_week gps_tow_s latitude_deg "
                    "longitude_deg ellipsoidal_height_m rtklib_quality "
                    "satellite_count sdn_m sde_m sdu_m age_s ratio "
                    "reference_type validation_status schema_version"
                ).split()
            ]

        async def execute(self, query, *args):
            if "INSERT INTO public.ppk_qa_jobs" in query:
                raise AssertionError("QA job must not be created")
            return "OK"

        async def close(self):
            pass

    source = SourceDB()
    writer = WriterDB()
    calls = iter([source, writer])

    async def connect(*args, **kwargs):
        return next(calls)

    monkeypatch.setitem(
        sys.modules,
        "asyncpg",
        types.SimpleNamespace(connect=connect),
    )

    monkeypatch.setenv("PPK_QA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv(
        "PPK_QA_SOURCE_DATABASE_URL", "postgresql://source@test/source"
    )
    monkeypatch.setenv(
        "PPK_QA_WRITER_DATABASE_URL", "postgresql://writer@test/qa"
    )
    monkeypatch.setenv("PPK_QA_SOURCE_DB_NAME", "slope_iot")
    monkeypatch.setenv("PPK_QA_WRITER_DB_NAME", "ppk_qa_biznet")
    monkeypatch.setenv("PPK_QA_SOURCE_DB_ROLE", "ppk_qa_source_reader")
    monkeypatch.setenv("PPK_QA_WRITER_DB_ROLE", "ppk_qa_writer")

    import ml.pipeline.preprocessing.ppk_engine as engine_module

    def forbidden_engine(*args, **kwargs):
        raise AssertionError("PPK engine must not be constructed")

    monkeypatch.setattr(
        engine_module, "RTKLibPPKEngine", forbidden_engine
    )

    nav = tmp_path / "navigation.rnx"
    config = tmp_path / "rtklib.conf"
    nav.write_text("test nav")
    config.write_text("test config")

    # Isolate only the support-file checks, not RAWX eligibility.
    monkeypatch.setattr(
        "scripts.ppk_qa_worker.verify_forward_qa_config",
        lambda *_: None,
    )
    monkeypatch.setattr(
        "scripts.ppk_qa_worker.verify_base_coordinates_in_config",
        lambda *_: None,
    )

    args = SimpleNamespace(
        site="ITB-STAGING-01",
        base="BASE-01",
        rover="ROVER-B1-02",
        base_lat=-6.0,
        base_lon=107.0,
        base_alt=100.0,
        nav=str(nav),
        config=str(config),
        since="2026-10-08T11:00:00+00:00",
        until="2026-10-08T11:05:00+00:00",
        window_minutes=5,
        min_matched=4,
        apply=True,
    )

    asyncio.run(run_once(args))

    output = capsys.readouterr().out
    records = [
        json.loads(line)
        for line in output.splitlines()
        if line.startswith("{")
    ]

    assert any(
        r.get("status") == "WAITING_PAIR"
        and r.get("reason_code") == "BASE_RAWX_ZERO_MEASUREMENTS"
        for r in records
    )
