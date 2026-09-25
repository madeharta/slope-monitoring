import base64
import pytest
from common.errors import InvalidBase64Error, InvalidCsvError
from ml.pipeline.preprocessing.g4_parser import (
    parse_accel_csv_single_post_blast_rawx,
    parse_gnss_csv,
)
from ml.pipeline.preprocessing.lora_parser import parse_accel_csv, parse_combined_gnss_csv
def _ubx_b64(payload: bytes | None = None) -> str:
    raw = payload or b"\xb5\x62\x02\x15\x00\x00\x00\x00"
    return base64.b64encode(raw).decode()
def test_parse_gnss_csv_rejects_non_ubx_payload():
    bad_payload = base64.b64encode(b"not a ubx frame").decode()
    csv_text = f"device_id,timestamp_utc,gnss_raw_payload_base64\nBASE-01,2026-09-15 09:24:00,{bad_payload}\n"
    with pytest.raises(InvalidBase64Error):
        parse_gnss_csv(csv_text)
def test_parse_gnss_csv_accepts_ubx_sync_bytes():
    csv_text = f"device_id,timestamp_utc,gnss_raw_payload_base64\nBASE-01,2026-09-15 09:24:00,{_ubx_b64()}\n"
    rows = parse_gnss_csv(csv_text)
    assert len(rows) == 1
    assert rows[0][2].startswith(b"\xb5\x62")
def test_parse_lora_combined_gnss():
    csv_text = (
        "device_id,timestamp_utc,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m,gnss_raw_payload_base64\n"
        f"BASE-01,2026-09-15 09:24:00,0,0,0,0,0,{_ubx_b64()}\n"
        "ROVER-B1-01,2026-09-15 09:24:00,-6.123,106.98,510.1,3,0.02,0\n"
    )
    parsed = parse_combined_gnss_csv(csv_text, base_device_id="BASE-01")
    assert len(parsed.rawx_rows) == 1
    assert len(parsed.position_rows) == 1
def test_parse_lora_accel_keeps_colocated_rtk():
    csv_text = (
        "device_id,sample_index,timestamp_utc,adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m\n"
        "ROVER-B1-01,0,2026-09-15 10:30:15.000,0.1,0.1,9.8,0.1,0.1,9.8,-6.123,106.98,510.1,3,0.02\n"
    )
    samples = parse_accel_csv(csv_text)
    assert samples[0].colocated_position is not None
    assert samples[0].colocated_position.h_acc_m == 0.02
def test_parse_4g_accel_requires_one_rawx_only():
    header = (
        "device_id,sample_index,timestamp_utc,adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,gnss_raw_payload_base64\n"
    )
    row0 = "ROVER-B1-01,0,2026-09-15 10:30:15.000,0.1,0.1,9.8,0.1,0.1,9.8,0\n"
    row1 = f"ROVER-B1-01,1,2026-09-15 10:30:15.001,0.1,0.1,9.8,0.1,0.1,9.8,{_ubx_b64()}\n"
    parsed = parse_accel_csv_single_post_blast_rawx(header + row0 + row1)
    assert len(parsed.samples) == 2
    with pytest.raises(InvalidCsvError):
        parse_accel_csv_single_post_blast_rawx(header + row0)
