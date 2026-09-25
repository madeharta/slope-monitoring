import csv
import json
from pathlib import Path
import pytest
from scripts.prepare_itb_uploads import COLUMNS, SOURCES, convert, ubx_valid
def _write(path, columns, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
def _frame():
    import base64
    body = bytes([2, 21, 0, 0])
    a = b = 0
    for x in body:
        a = (a + x) % 256
        b = (b + a) % 256
    return base64.b64encode(b'\xb5\x62' + body + bytes([a, b])).decode()
def test_ubx_checksum_and_invalid_placeholder():
    assert ubx_valid(_frame())
    assert not ubx_valid('0')
    import base64
    raw = bytearray(base64.b64decode(_frame()))
    raw[-1] ^= 1
    assert not ubx_valid(base64.b64encode(raw).decode())
def test_staging_preserves_all_rows_and_blocks_unsafe_data(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    lora_pos = [dict(zip(COLUMNS['lora_position'], ('ROVER-01', t, '-6', '107', '900', '3', '0.4')))
                for t in ('2026-09-18 10:39:59', '2026-09-18 10:40:00')]
    accel_l = [dict(zip(COLUMNS['lora_accel'], ('ROVER-01', i, t, '0','0','9','0','0','9','0','0','0','0','0')))
               for i,t in [('0','2026-09-18 10:45:53.000'),('0','2026-09-18 10:45:53.000')]]
    gnss = [dict(zip(COLUMNS['g4_gnss'], ('lsm-unconfigured',t,_frame())))
            for t in ('2026-09-18 12:25:27','2026-09-18 12:26:00')]
    accel_g = [dict(zip(COLUMNS['g4_accel'], ('lsm-unconfigured','0','2026-09-18 00:00:00.000','0','0','9','0','0','9','0')))]
    for kind, rows in [('lora_position',lora_pos),('lora_accel',accel_l),('g4_gnss',gnss),('g4_accel',accel_g)]:
        _write(source/SOURCES[kind], COLUMNS[kind], rows)
    output = tmp_path / 'out'
    result = convert(source, output)
    assert sum(x['record_count'] for x in result['files']) == 7
    assert len(result['files']) == 6
    assert all(x['status'] != 'READY' for x in result['files'])
    assert {x['file'] for x in result['files'] if x['type']=='lora_position'} == {
        'staging/pos_BASE-01_20260918_1035.csv', 'staging/pos_BASE-01_20260918_1040.csv'}
    assert json.loads((output/'manifest.json').read_text()) == result
    with pytest.raises(FileExistsError):
        convert(source, output)
def test_reject_modified_schema(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    (source/SOURCES['lora_position']).write_text('device_id,not_expected\nA,B\n')
    with pytest.raises(ValueError, match='Schema mismatch'):
        convert(source, tmp_path/'out')
