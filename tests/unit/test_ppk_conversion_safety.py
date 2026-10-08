import base64
import csv
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from common.errors import NotFoundError
from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv
from ml.pipeline.preprocessing.ppk_engine import PPKSolveError, RTKLibPPKEngine
from scripts.convert_rawx_ppk import ConversionError, execute, read_rawx
from services.monitoring_service.canonicalization_service import CanonicalizationService
FIXTURE = Path(__file__).parents[1] / 'fixtures/itb_real_data/4g_ppk_only.csv'
def test_preserve_all_itb_rawx_frames_and_duplicate_timestamps():
    device, binary, meta = read_rawx(FIXTURE)
    assert device == 'lsm-unconfigured'
    assert meta['rows'] == 578
    assert meta['duplicate_timestamp_rows_preserved'] == 6
    assert binary.startswith(b'\xb5\x62')
def test_unpaired_data_can_export_raw_but_not_claim_ppk(tmp_path):
    m = execute(FIXTURE, tmp_path / 'output', convbin='/absent/convbin')
    assert m['mode'] == 'RAWX_ONLY' and m['ppk_validated'] is False
    assert not list((tmp_path / 'output').glob('*.pos'))
    assert (tmp_path / 'output' / 'rover.ubx').stat().st_size > 0
def test_same_stream_as_base_is_rejected_before_output(tmp_path):
    with pytest.raises(ConversionError, match='distinct'):
        execute(FIXTURE, tmp_path / 'output', base_input=FIXTURE,
                base_coords=(-6, 107, 100), nav=FIXTURE)
    assert not (tmp_path / 'output').exists()
def test_corrupt_ubx_is_rejected(tmp_path):
    source = tmp_path / 'bad.csv'
    with source.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['device_id','timestamp_utc','gnss_raw_payload_base64'])
        writer.writerow(['ROVER-01','2026-09-18 12:25:27',base64.b64encode(b'\xb5\x62\x02\x15\x00\x00\x00\x00').decode()])
    with pytest.raises(ConversionError, match='Invalid UBX'):
        read_rawx(source)
def test_ppk_engine_requires_nav_before_solver(tmp_path):
    from datetime import datetime, timezone
    engine = RTKLibPPKEngine(-6, 107, 100)
    with pytest.raises(PPKSolveError, match='RINEX navigation'):
        engine._prepare_navigation(datetime(2026, 9, 15, tzinfo=timezone.utc), tmp_path, station=None)

def test_ppk_command_uses_l_not_b_and_has_plain_nav(monkeypatch, tmp_path):
    nav = tmp_path / 'nav.rnx'
    nav.write_text('test NAV fixture, not real ephemeris')
    engine = RTKLibPPKEngine(-6, 107, 100, nav_file=str(nav))
    command = []
    def fake_run(args, timeout, step):
        command.extend(args)
        (tmp_path/'result.pos').write_text('mocked only')
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(engine, '_run_subprocess', fake_run)
    engine._run_rnx2rtkp(tmp_path/'rover.obs', tmp_path/'base.obs', nav, tmp_path/'result.pos')
    assert '-l' in command and '-b' not in command
    assert command[command.index('-l')+1:command.index('-l')+4] == ['-6','107','100']
    assert command[-1] == str(nav)

@pytest.mark.asyncio
async def test_no_rover_baseline_suppresses_unsafe_displacement():
    rows = parse_combined_gnss_csv(
        'device_id,timestamp_utc,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m,gnss_raw_payload_base64\n'
        'BASE-01,2026-09-15 09:24:00,0,0,0,0,0,tWIB\n'
        'ROVER-01,2026-09-15 09:24:00,-6.2,106.8,500,3,0.02,0\n',
        base_device_id='BASE-01',
    ).position_rows
    service = CanonicalizationService(None, lambda _: None)
    service._devices.get_site_id = AsyncMock(return_value='SITE-A')
    service._rover_baselines.get = AsyncMock(side_effect=NotFoundError('baseline','ROVER-01'))
    service._measurements.write_displacement = AsyncMock()
    await service.handle_position_rows('BASE-01', rows)
    service._measurements.write_displacement.assert_not_awaited()
@pytest.mark.asyncio
async def test_approved_rover_baseline_zero_at_initial_position():
    rows = parse_combined_gnss_csv(
        'device_id,timestamp_utc,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m,gnss_raw_payload_base64\n'
        'BASE-01,2026-09-15 09:24:00,0,0,0,0,0,tWIB\n'
        'ROVER-01,2026-09-15 09:24:00,-6.2,106.8,500,3,0.02,0\n',
        base_device_id='BASE-01',
    ).position_rows
    service = CanonicalizationService(None, lambda _: None)
    service._devices.get_site_id = AsyncMock(return_value='SITE-A')
    service._rover_baselines.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500, vertical_datum='ELLIPSOIDAL_WGS84', max_h_acc_m=0.1))
    service._measurements.write_displacement = AsyncMock()
    await service.handle_position_rows('BASE-01', rows)
    assert service._measurements.write_displacement.await_args.kwargs['total_mm'] == 0.0


def test_conversion_uses_explicit_convbin_auxiliary_paths(monkeypatch, tmp_path):
    captured = []
    def fake_run(args, text, capture_output, timeout, check):
        captured.append(args)
        Path(args[args.index("-o") + 1]).write_text("rinex")
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr("scripts.convert_rawx_ppk.subprocess.run", fake_run)
    execute(FIXTURE, tmp_path / "output", convbin="/bin/echo")
    args = captured[0]
    for flag in ("-n", "-g", "-h", "-q", "-l", "-s"):
        value = args[args.index(flag) + 1]
        assert value != "/"
        assert Path(value).parent == tmp_path / "output"


def _rawx_b64(*, week: int, tow: float, num_meas: int, leap_s: int = 18, rec_stat: int = 1) -> str:
    payload = struct.pack("<dHbBBBH", tow, week, leap_s, num_meas, rec_stat, 1, 0)
    payload += b"\x00" * (32 * num_meas)
    body = bytes((0x02, 0x15)) + len(payload).to_bytes(2, "little") + payload
    ck_a = 0
    ck_b = 0
    for value in body:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return base64.b64encode(b"\xb5\x62" + body + bytes((ck_a, ck_b))).decode()


def _write_rawx_csv(path: Path, device_id: str, rows: list[tuple[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["device_id", "timestamp_utc", "gnss_raw_payload_base64"])
        for timestamp_utc, payload in rows:
            writer.writerow([device_id, timestamp_utc, payload])


def test_read_rawx_records_receiver_time_and_unusable_zero_measurement_frames(tmp_path):
    source = tmp_path / "rawx.csv"
    _write_rawx_csv(
        source,
        "ROVER-B1-01",
        [
            ("2026-09-18 12:00:00", _rawx_b64(week=0, tow=2.0, num_meas=0)),
            ("2026-09-18 12:00:01", _rawx_b64(week=2436, tow=1000.0, num_meas=1)),
        ],
    )
    _, _, meta = read_rawx(source)
    assert meta["rows"] == 2
    assert meta["usable_gnss_epochs"] == 1
    assert meta["zero_measurement_frames"] == 1
    assert meta["first_gps_seconds"] == meta["last_gps_seconds"]


def test_read_rawx_reports_csv_vs_receiver_clock_delta(tmp_path):
    source = tmp_path / "rawx.csv"
    payload = _rawx_b64(week=2436, tow=1000.0, num_meas=1, leap_s=18, rec_stat=1)
    _write_rawx_csv(
        source,
        "ROVER-B1-01",
        [("2026-09-18 12:00:00", payload)],
    )
    _, _, meta = read_rawx(source)
    assert meta["first_gnss_utc"] is not None
    assert meta["last_gnss_utc"] is not None
    assert meta["csv_gnss_delta_seconds_min"] == meta["csv_gnss_delta_seconds_max"]


def test_base_rover_overlap_gate_uses_rawx_receiver_time_not_csv_clock(tmp_path):
    rover = tmp_path / "rover.csv"
    base = tmp_path / "base.csv"
    nav = tmp_path / "nav.rnx"
    nav.write_text("nonempty nav placeholder")

    _write_rawx_csv(
        rover,
        "ROVER-B1-01",
        [("2026-09-18 12:00:00", _rawx_b64(week=2436, tow=1000.0, num_meas=1))],
    )
    _write_rawx_csv(
        base,
        "BASE-01",
        [("2026-09-18 18:00:00", _rawx_b64(week=2436, tow=1000.0, num_meas=1))],
    )

    manifest = execute(
        rover,
        tmp_path / "output",
        base_input=base,
        base_coords=(-6.0, 107.0, 100.0),
        nav=nav,
        convbin="/absent/convbin",
    )
    assert manifest["base"] is not None
    assert manifest["conversion"].startswith("NOT_RUN_CONVBIN_MISSING")
