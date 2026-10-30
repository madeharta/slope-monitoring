"""F-02: canonicalization must not emit displacement after PPK persistence fails.

Uses a mocked repository boundary; PostgreSQL retry/concurrency are covered by
separate integration acceptance tests.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.monitoring_service.canonicalization_service import CanonicalizationService


def _setup():
    ts = datetime(2026, 10, 20, 8, 30, tzinfo=timezone.utc)
    solution = SimpleNamespace(
        timestamp_utc=ts, rtklib_quality=1, h_acc_m=0.02,
        latitude=-6.8671, longitude=107.5787, ellipsoidal_height_m=880.0,
        satellites=12, age_s=0.5, ratio=5.0,
        sdn_m=0.002, sde_m=0.003, sdu_m=0.004,
    )
    result = SimpleNamespace(solutions=[solution])
    service = CanonicalizationService.__new__(CanonicalizationService)
    service._reference = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(vertical_datum="ELLIPSOIDAL_WGS84")))
    service._rover_baselines = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
        vertical_datum="ELLIPSOIDAL_WGS84", max_h_acc_m=0.10,
        latitude=-6.8671, longitude=107.5787, altitude_m=880.0,
    )))
    service._raw = SimpleNamespace(get_gnss_window=AsyncMock(return_value=[(ts, b"x")] * 4))
    service._ppk_engine_factory = Mock(return_value=SimpleNamespace(solve_window=Mock(return_value=result)))
    service._ppk_solutions = SimpleNamespace(write_accepted=AsyncMock())
    service._measurements = SimpleNamespace(write_displacement=AsyncMock())
    service._ppk_min_epochs = 4
    service._ppk_max_h_acc_m = 0.10
    service._ppk_accepted_quality = {1}
    return service, ts


async def _run(service, ts):
    await service._process_ppk_window(
        site_id="ITB-STAGING-01", base_id="BASE-01", rover_id="ROVER-B1-02",
        window_start=ts - timedelta(minutes=1),
        window_end=ts + timedelta(minutes=1),
    )


def test_persist_failure_prevents_displacement(monkeypatch):
    from services.monitoring_service import canonicalization_service as module
    monkeypatch.setattr(module, "_dedupe_and_join", lambda rows: b"rawx")
    monkeypatch.setattr(module, "compute_displacement_mm", lambda *args: SimpleNamespace(
        de_mm=1.0, dn_mm=2.0, du_mm=3.0, total_mm=3.741657))
    service, ts = _setup()
    service._ppk_solutions.write_accepted.side_effect = ValueError("PPK epoch conflict: provenance differs")
    with pytest.raises(ValueError, match="provenance differs"):
        asyncio.run(_run(service, ts))
    service._ppk_solutions.write_accepted.assert_awaited_once()
    service._measurements.write_displacement.assert_not_awaited()


def test_idempotent_persist_success_allows_downstream_measurement(monkeypatch):
    from services.monitoring_service import canonicalization_service as module
    monkeypatch.setattr(module, "_dedupe_and_join", lambda rows: b"rawx")
    monkeypatch.setattr(module, "compute_displacement_mm", lambda *args: SimpleNamespace(
        de_mm=1.0, dn_mm=2.0, du_mm=3.0, total_mm=3.741657))
    service, ts = _setup()
    asyncio.run(_run(service, ts))
    service._ppk_solutions.write_accepted.assert_awaited_once()
    service._measurements.write_displacement.assert_awaited_once()
