import pytest

from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv


HEADER = (
    "device_id,timestamp_utc,latitude,longitude,"
    "altitude_m,rtk_status,h_acc_m,batt\n"
)

CSV = (
    HEADER
    + "BASE-01,2026-10-27 00:00:00,-6.86710000,107.57870000,895.9561,2,0.0200,12.50\n"
    + "ROVER-01,2026-10-27 00:00:00,-6.86720000,107.57880000,896.1234,2,0.0300,12.40\n"
)


def test_lora_v17_accepts_coordinates_without_rawx():
    result = parse_combined_gnss_csv(CSV, base_device_id="BASE-01")

    assert len(result.rawx_rows) == 0
    assert len(result.position_rows) == 2


def test_lora_v17_preserves_base_and_rover_identity():
    result = parse_combined_gnss_csv(CSV, base_device_id="BASE-01")

    positions = {row.device_id: row for row in result.position_rows}

    assert set(positions) == {"BASE-01", "ROVER-01"}
    assert positions["BASE-01"].role.value == "base"
    assert positions["ROVER-01"].role.value == "rover"


def test_lora_v17_requires_rtk_status_and_battery_columns():
    invalid = CSV.replace(",rtk_status,h_acc_m,batt", ",gnss_fix_type,h_acc_m")

    with pytest.raises(Exception):
        parse_combined_gnss_csv(invalid, base_device_id="BASE-01")
