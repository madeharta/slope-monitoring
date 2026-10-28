import pytest

from common.errors import InvalidCsvError
from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv


HEADER = (
    "device_id,timestamp_utc,latitude,longitude,"
    "altitude_m,rtk_status,h_acc_m,batt\n"
)


def parse_row(status, accuracy="0.0200", battery="12.50"):
    raw = (
        HEADER
        + "BASE-01,2026-10-27 00:00:00,"
        + f"-6.86710000,107.57870000,895.9561,{status},{accuracy},{battery}\n"
    )
    return parse_combined_gnss_csv(
        raw,
        base_device_id="BASE-01",
    )


@pytest.mark.parametrize("status", [0, 1, 2])
def test_official_rtk_statuses_accepted(status):
    result = parse_row(status)
    assert len(result.position_rows) == 1
    assert result.position_rows[0].gnss_fix_type == status


@pytest.mark.parametrize("status", [-1, 3, 99])
def test_unsupported_rtk_status_rejected(status):
    with pytest.raises(InvalidCsvError):
        parse_row(status)


def test_no_fix_telemetry_is_accepted():
    result = parse_row(0, accuracy="9999.0000")
    assert len(result.position_rows) == 1
    assert result.position_rows[0].gnss_fix_type == 0


@pytest.mark.parametrize("battery", ["invalid", "NaN", "Infinity"])
def test_invalid_battery_rejected(battery):
    with pytest.raises(InvalidCsvError):
        parse_row(2, battery=battery)


def test_battery_voltage_preserved_per_device():
    raw = (
        HEADER
        + "BASE-01,2026-10-27 00:00:00,"
        "-6.86710000,107.57870000,895.9561,2,0.0200,12.50\n"
        + "ROVER-01,2026-10-27 00:00:00,"
        "-6.86720000,107.57880000,896.1234,1,0.0300,11.80\n"
    )

    result = parse_combined_gnss_csv(raw, base_device_id="BASE-01")
    batteries = {
        sample.device_id: sample.battery_voltage_v
        for sample in result.position_rows
    }

    assert batteries == {
        "BASE-01": 12.50,
        "ROVER-01": 11.80,
    }
