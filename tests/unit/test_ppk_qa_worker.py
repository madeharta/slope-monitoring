import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

module_path = Path(__file__).resolve().parents[2] / 'scripts' / 'ppk_qa_worker.py'
spec = importlib.util.spec_from_file_location('ppk_qa_worker', module_path)
import sys
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


def test_2026_gps_week_roundtrip():
    d = datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc)
    week, tow = worker.gps_epoch_2026(d)
    assert week > 2000 and 0 <= tow < 604800


def test_gps_rejects_naive_and_out_of_scope():
    with pytest.raises(ValueError):
        worker.gps_epoch_2026(datetime(2026,10,17))
    with pytest.raises(ValueError):
        worker.gps_epoch_2026(datetime(2027,1,1,tzinfo=timezone.utc))


def test_fingerprint_deterministic_and_changes_with_inputs():
    args = (b'base', b'rover', b'nav', b'config', (-6.0,107.0,800.0))
    assert worker.fingerprint(*args) == worker.fingerprint(*args)
    assert worker.fingerprint(*args) != worker.fingerprint(b'base2', *args[1:])


def ubx(payload=b''):
    header = b'\xb5\x62\x02\x15' + len(payload).to_bytes(2,'little')
    a = b = 0
    for byte in header[2:]+payload:
        a = (a+byte)&255
        b = (b+a)&255
    return header+payload+bytes((a,b))


def test_rawx_checksum_and_length_gate():
    import base64
    frame = ubx(b'abc')
    assert worker.join_rawx([{'raw_payload_base64':base64.b64encode(frame).decode()}]) == frame
    with pytest.raises(ValueError,match='checksum'):
        worker.join_rawx([{'raw_payload_base64':base64.b64encode(frame[:-1]+b'\x00').decode()}])
    with pytest.raises(ValueError):
        worker.join_rawx([{'raw_payload_base64':'0'}])
