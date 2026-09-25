import base64
import pytest
from common.errors import InvalidCsvError
from ml.pipeline.preprocessing.g4_parser import parse_accel_csv_single_post_blast_rawx
from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv
from services.ingestion_service.csv_validator import (
    validate_headers,
    validate_path_file_name,
    validate_record_count,
)
def _headers(**overrides):
    h = {
        "X-Communication-Mode": "4g",
        "X-Device-Id": "ROVER-B1-01",
        "X-Device-Role": "rover",
        "X-Data-Type": "gnss",
        "X-File-Name": "gnss_ROVER-B1-01_20260924_2100.csv",
        "X-Record-Count": "1",
    }
    h.update(overrides)
    return h
def _ubx_b64():
    return base64.b64encode(b"\xb5\x62\x02\x15\x00\x00\x00\x00").decode()
def test_valid_4g_gnss_headers():
    parsed = validate_headers(_headers())
    assert parsed.communication_mode == "4g"
    assert parsed.data_type == "gnss"
def test_lora_rover_routine_gnss_rejected():
    with pytest.raises(InvalidCsvError):
        validate_headers(_headers(**{
            "X-Communication-Mode": "lora",
            "X-Device-Role": "rover",
        }))
def test_position_data_type_rejected():
    with pytest.raises(InvalidCsvError):
        validate_headers(_headers(**{"X-Data-Type": "position"}))
def test_path_filename_must_match_header():
    parsed = validate_headers(_headers())
    with pytest.raises(InvalidCsvError):
        validate_path_file_name("gnss_ROVER-B1-01_20260924_2200.csv", parsed)
def test_record_count_is_enforced():
    csv_text = "device_id,timestamp_utc,gnss_raw_payload_base64\nA,2026-09-24 21:00:00,x\n"
    assert validate_record_count(csv_text, 1) == 1
    with pytest.raises(InvalidCsvError):
        validate_record_count(csv_text, 2)
def test_lora_combined_gnss_splits_base_rawx_and_rover_rtk():
    payload = _ubx_b64()
    csv_text = (
        "device_id,timestamp_utc,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m,gnss_raw_payload_base64\n"
        f"BASE-01,2026-09-24 21:00:00,0,0,0,0,0,{payload}\n"
        "ROVER-B1-01,2026-09-24 21:00:00,-6.1,107.5,500.0,3,0.02,0\n"
    )
    parsed = parse_combined_gnss_csv(csv_text, base_device_id="BASE-01")
    assert len(parsed.rawx_rows) == 1
    assert len(parsed.position_rows) == 1
    assert parsed.position_rows[0].device_id == "ROVER-B1-01"
def test_4g_blast_requires_exactly_one_post_blast_rawx():
    payload = _ubx_b64()
    header = (
        "device_id,sample_index,timestamp_utc,adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,gnss_raw_payload_base64\n"
    )
    row0 = "ROVER-B1-01,0,2026-09-24 21:00:00.000,0.1,0.1,9.8,0.1,0.1,9.8,0\n"
    row1 = f"ROVER-B1-01,1,2026-09-24 21:00:00.001,0.2,0.1,9.7,0.2,0.1,9.7,{payload}\n"
    parsed = parse_accel_csv_single_post_blast_rawx(header + row0 + row1)
    assert len(parsed.samples) == 2
    assert parsed.post_blast_rawx[0] == "ROVER-B1-01"
    with pytest.raises(InvalidCsvError):
        parse_accel_csv_single_post_blast_rawx(header + row0)
