import base64
import pytest
from common.errors import InvalidBase64Error, InvalidCsvError
from ml.pipeline.preprocessing.g4_parser import (
    parse_accel_csv_single_auxiliary_rawx,
    parse_gnss_csv,
)
from ml.pipeline.preprocessing.lora_parser import parse_accel_csv, parse_combined_gnss_csv
def _ubx_b64(payload: bytes | None = None) -> str:
    body = bytes((0x02, 0x15)) + len(payload or b"").to_bytes(2, "little") + (payload or b"")
    ck_a = 0
    ck_b = 0
    for value in body:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    raw = b"\xb5\x62" + body + bytes((ck_a, ck_b))
    return base64.b64encode(raw).decode()
def test_parse_gnss_csv_rejects_non_ubx_payload():
    bad_payload = base64.b64encode(b"not a ubx frame").decode()
    csv_text = f"device_id,timestamp_utc,gnss_raw_payload_base64\nBASE-01,2026-09-15 09:24:00,{bad_payload}\n"
    with pytest.raises(InvalidBase64Error):
        parse_gnss_csv(csv_text)
def test_parse_gnss_csv_rejects_ubx_without_rawx_time():
    csv_text = f"device_id,timestamp_utc,gnss_raw_payload_base64\nBASE-01,2026-09-15 09:24:00,{_ubx_b64()}\n"
    with pytest.raises(InvalidCsvError, match="GNSS time unverified"):
        parse_gnss_csv(csv_text)
def test_parse_lora_combined_gnss():
    csv_text = (
        "device_id,timestamp_utc,latitude,longitude,altitude_m,rtk_status,h_acc_m,batt\n"
        "BASE-01,2026-09-15 09:24:00,-6.20000000,106.80000000,500.0000,2,0.0200,12.50\n"
        "ROVER-B1-01,2026-09-15 09:24:00,-6.20010000,106.80010000,500.1000,2,0.0300,12.40\n"
    )
    parsed = parse_combined_gnss_csv(csv_text, base_device_id="BASE-01")
    assert parsed.rawx_rows == []
    assert [s.device_id for s in parsed.position_rows] == ["BASE-01", "ROVER-B1-01"]
    assert [s.role.value for s in parsed.position_rows] == ["base", "rover"]

def test_parse_lora_accel_keeps_colocated_rtk():
    from ml.pipeline.preprocessing.lora_parser import parse_accel_latest_position

    header = (
        "device_id,sample_index,timestamp_utc,"
        "adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,"
        "latitude,longitude,altitude_m,rtk_status,h_acc_m\n"
    )
    raw = header + (
        "ROVER-B1-01,0,2026-09-15 10:30:15.000,"
        "0.1,0.1,9.8,0.1,0.1,9.8,0,0,0,0,0\n"
        "ROVER-B1-01,0,2026-09-15 10:30:15.000,"
        "0,0,0,0,0,0,-6.12300000,106.98000000,510.1000,2,0.0200\n"
    )
    samples = parse_accel_csv(raw)
    positions = parse_accel_latest_position(raw)

    assert len(samples) == 1
    assert samples[0].colocated_position is None
    assert len(positions) == 1
    assert positions[0].h_acc_m == 0.02

def test_parse_4g_accel_requires_one_rawx_only():
    header = (
        "device_id,sample_index,timestamp_utc,adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,gnss_raw_payload_base64\n"
    )
    row0 = "ROVER-B1-01,0,2026-09-15 10:30:15.000,0.1,0.1,9.8,0.1,0.1,9.8,0\n"
    row1 = f"ROVER-B1-01,1,2026-09-15 10:30:15.001,0.1,0.1,9.8,0.1,0.1,9.8,{_ubx_b64()}\n"
    parsed = parse_accel_csv_single_auxiliary_rawx(header + row0 + row1)
    assert len(parsed.samples) == 1
    assert parsed.samples[0].sample_index == 0
    with pytest.raises(InvalidCsvError):
        parse_accel_csv_single_auxiliary_rawx(header + row0)


def test_parse_4g_rejects_bad_ubx_checksum():
    valid = base64.b64decode(_ubx_b64())
    bad = valid[:-1] + bytes((valid[-1] ^ 0xFF,))
    encoded = base64.b64encode(bad).decode()
    csv_text = f"device_id,timestamp_utc,gnss_raw_payload_base64\nBASE-01,2026-09-15 09:24:00,{encoded}\n"
    with pytest.raises(InvalidBase64Error, match="checksum"):
        parse_gnss_csv(csv_text)
