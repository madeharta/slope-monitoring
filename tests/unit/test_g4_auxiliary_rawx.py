import base64
from datetime import timezone
import pytest
from common.errors import InvalidBase64Error, InvalidCsvError
from ml.pipeline.preprocessing.g4_parser import parse_accel_csv_single_auxiliary_rawx

HEADER = (
    "device_id,sample_index,timestamp_utc,adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
    "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,gnss_raw_payload_base64\n"
)

def _ubx_b64(payload: bytes = b"") -> str:
    body = bytes((0x02, 0x15)) + len(payload).to_bytes(2, "little") + payload
    ck_a = 0
    ck_b = 0
    for value in body:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return base64.b64encode(b"\xb5\x62" + body + bytes((ck_a, ck_b))).decode()

def _sample(index: int, ts: str) -> str:
    return f"ROVER-B1-01,{index},{ts},0.1,0.2,9.8,0.1,0.2,9.7,0\n"

def _aux(ts: str, payload: str | None = None) -> str:
    return f"ROVER-B1-01,0,{ts},0,0,0,0,0,0,{payload or _ubx_b64()}\n"

def test_auxiliary_rawx_is_excluded_from_accel_samples_and_may_precede_window():
    parsed = parse_accel_csv_single_auxiliary_rawx(
        HEADER
        + _sample(0, "2026-09-28 08:31:11.000")
        + _sample(1, "2026-09-28 08:31:11.001")
        + _aux("2026-09-28 08:31:00.000")
    )
    assert [sample.sample_index for sample in parsed.samples] == [0, 1]
    assert parsed.auxiliary_rawx[0] == "ROVER-B1-01"
    assert parsed.auxiliary_rawx[1].tzinfo == timezone.utc
    assert parsed.auxiliary_rawx[1] < parsed.samples[0].timestamp_utc

def test_zero_auxiliary_rawx_is_rejected():
    with pytest.raises(InvalidCsvError, match="exactly one auxiliary"):
        parse_accel_csv_single_auxiliary_rawx(HEADER + _sample(0, "2026-09-28 08:31:11.000"))

def test_multiple_auxiliary_rawx_rows_are_rejected():
    with pytest.raises(InvalidCsvError, match="found 2"):
        parse_accel_csv_single_auxiliary_rawx(
            HEADER
            + _sample(0, "2026-09-28 08:31:11.000")
            + _aux("2026-09-28 08:31:00.000")
            + _aux("2026-09-28 08:31:01.000")
        )

def test_bad_auxiliary_ubx_checksum_is_rejected():
    raw = base64.b64decode(_ubx_b64())
    bad = base64.b64encode(raw[:-1] + bytes((raw[-1] ^ 0xFF,))).decode()
    with pytest.raises(InvalidBase64Error, match="checksum"):
        parse_accel_csv_single_auxiliary_rawx(
            HEADER + _sample(0, "2026-09-28 08:31:11.000") + _aux("2026-09-28 08:31:00.000", bad)
        )
