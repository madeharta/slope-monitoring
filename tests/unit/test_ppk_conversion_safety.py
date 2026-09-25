import base64
import csv
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
def test_ppk_engine_requires_nav_even_if_convbin_was_successful(tmp_path):
    engine = RTKLibPPKEngine(-6, 107, 100)
    with pytest.raises(PPKSolveError, match='RINEX navigation'):
        engine._run_rnx2rtkp(tmp_path/'rover.obs', tmp_path/'base.obs', tmp_path/'out.pos')
def test_ppk_command_uses_l_not_b_and_has_nav(monkeypatch, tmp_path):
    nav = tmp_path / 'nav.rnx'
    nav.write_text('test NAV fixture, not real ephemeris')
    engine = RTKLibPPKEngine(-6, 107, 100, nav_file=str(nav))
    command = []
    def fake_run(args, timeout, step):
        command.extend(args)
        (tmp_path/'result.pos').write_text('mocked only')
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(engine, '_run_subprocess', fake_run)
    engine._run_rnx2rtkp(tmp_path/'rover.obs', tmp_path/'base.obs', tmp_path/'result.pos')
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
    service._rover_baselines.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500, vertical_datum='MSL_CONFIRMED', max_h_acc_m=0.1))
    service._measurements.write_displacement = AsyncMock()
    await service.handle_position_rows('BASE-01', rows)
    assert service._measurements.write_displacement.await_args.kwargs['total_mm'] == 0.0
