from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from ml.pipeline.preprocessing.ppk_engine import PPKSolutionEpoch, PPKWindowResult
from services.monitoring_service.canonicalization_service import CanonicalizationService, _dedupe_and_join


def _solution(second: int, q: int = 1, h: float = 500.0) -> PPKSolutionEpoch:
    return PPKSolutionEpoch(
        timestamp_utc=datetime(2026, 9, 26, 12, 0, second, tzinfo=timezone.utc),
        latitude=-6.2,
        longitude=106.8,
        ellipsoidal_height_m=h,
        rtklib_quality=q,
        satellites=12,
        sdn_m=0.002,
        sde_m=0.003,
        sdu_m=0.004,
        age_s=0.5,
        ratio=12.0,
    )


def test_dedupe_and_join_sorts_and_deduplicates_exact_epoch_payload_pairs():
    t0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    rows = [
        (t0 + timedelta(seconds=15), b"B", "f2.csv"),
        (t0, b"A", "f1.csv"),
        (t0, b"A", "retry.csv"),
    ]
    assert _dedupe_and_join(rows) == b"AB"


@pytest.mark.asyncio
async def test_ppk_window_emits_all_accepted_solution_epochs(monkeypatch):
    monkeypatch.setenv("PPK_MIN_EPOCHS", "2")
    service = CanonicalizationService(None, lambda _: engine)
    service._reference.get = AsyncMock(return_value=SimpleNamespace(
        latitude=-6.2, longitude=106.8, altitude_m=500.0, vertical_datum="ELLIPSOIDAL_WGS84"
    ))
    service._rover_baselines.get = AsyncMock(return_value=SimpleNamespace(
        latitude=-6.2, longitude=106.8, altitude_m=500.0,
        vertical_datum="ELLIPSOIDAL_WGS84", max_h_acc_m=0.1,
    ))
    t0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    base = [(t0, b"A", "base.csv"), (t0 + timedelta(seconds=15), b"B", "base.csv")]
    rover = [(t0, b"C", "rover.csv"), (t0 + timedelta(seconds=15), b"D", "rover.csv")]
    service._raw.get_gnss_window = AsyncMock(side_effect=[base, rover])
    service._measurements.write_displacement = AsyncMock()
    engine = Mock()
    engine.solve_window.return_value = PPKWindowResult(
        solutions=(_solution(0), _solution(15)),
        navigation_sha256="a" * 64,
        navigation_source_url="https://example.test/nav",
        navigation_provider="BKG_WRD",
        navigation_cache_hit=False,
        rtklib_config_sha256="b" * 64,
    )
    service._ppk_engine_factory = lambda _: engine
    await service._process_ppk_window(
        site_id="SITE-A", base_id="BASE-01", rover_id="ROVER-B1-01",
        window_start=t0, window_end=t0 + timedelta(minutes=5),
    )
    assert service._measurements.write_displacement.await_count == 2
    first = service._measurements.write_displacement.await_args_list[0].kwargs
    assert first["rtklib_quality"] == 1
    assert "gnss_fix_type" not in first
    assert first["rtklib_ns"] == 12
    engine.solve_window.assert_called_once()
    assert engine.solve_window.call_args.kwargs["observed_at"] == t0


@pytest.mark.asyncio
async def test_ppk_quality_gate_rejects_float_without_mislabeling_as_device_fix(monkeypatch):
    monkeypatch.setenv("PPK_MIN_EPOCHS", "2")
    service = CanonicalizationService(None, lambda _: engine)
    service._reference.get = AsyncMock(return_value=SimpleNamespace(
        latitude=-6.2, longitude=106.8, altitude_m=500.0, vertical_datum="ELLIPSOIDAL_WGS84"
    ))
    service._rover_baselines.get = AsyncMock(return_value=SimpleNamespace(
        latitude=-6.2, longitude=106.8, altitude_m=500.0,
        vertical_datum="ELLIPSOIDAL_WGS84", max_h_acc_m=0.1,
    ))
    t0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    rows = [(t0, b"A", "a.csv"), (t0 + timedelta(seconds=15), b"B", "a.csv")]
    service._raw.get_gnss_window = AsyncMock(side_effect=[rows, rows])
    service._measurements.write_displacement = AsyncMock()
    engine = Mock()
    engine.solve_window.return_value = PPKWindowResult(
        solutions=(_solution(0, q=2),),
        navigation_sha256="a" * 64,
        navigation_source_url=None,
        navigation_provider=None,
        navigation_cache_hit=True,
        rtklib_config_sha256=None,
    )
    service._ppk_engine_factory = lambda _: engine
    await service._process_ppk_window(
        site_id="SITE-A", base_id="BASE-01", rover_id="ROVER-B1-01",
        window_start=t0, window_end=t0 + timedelta(minutes=5),
    )
    service._measurements.write_displacement.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_arrival_reconciles_rovers_in_same_site(monkeypatch):
    monkeypatch.setenv("PPK_MIN_EPOCHS", "2")
    service = CanonicalizationService(None, lambda _: None)
    t0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    service._raw.insert_gnss_raw_batch = AsyncMock()
    service._devices.get_site_id = AsyncMock(return_value="SITE-A")
    service._devices.get_base_device_id_for_site = AsyncMock(return_value="BASE-01")
    service._devices.get_rover_device_ids_for_site = AsyncMock(return_value=["ROVER-B1-01", "ROVER-B1-02"])
    service._process_ppk_window = AsyncMock()
    await service.handle_gnss_rows(
        "BASE-01", "base", "base.csv",
        [("BASE-01", t0, b"A"), ("BASE-01", t0 + timedelta(seconds=15), b"B")],
    )
    assert service._process_ppk_window.await_count == 2
    rover_ids = [c.kwargs["rover_id"] for c in service._process_ppk_window.await_args_list]
    assert rover_ids == ["ROVER-B1-01", "ROVER-B1-02"]


@pytest.mark.asyncio
async def test_unconfirmed_base_vertical_datum_blocks_ppk(monkeypatch):
    service = CanonicalizationService(None, lambda _: Mock())
    service._reference.get = AsyncMock(return_value=SimpleNamespace(
        latitude=-6.2, longitude=106.8, altitude_m=500.0, vertical_datum=None
    ))
    service._raw.get_gnss_window = AsyncMock()
    service._measurements.write_displacement = AsyncMock()
    t0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    await service._process_ppk_window(
        site_id="SITE-A", base_id="BASE-01", rover_id="ROVER-B1-01",
        window_start=t0, window_end=t0 + timedelta(minutes=5),
    )
    service._raw.get_gnss_window.assert_not_awaited()
    service._measurements.write_displacement.assert_not_awaited()
