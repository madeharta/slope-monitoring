from ml.pipeline.preprocessing.lora_parser import (
    parse_accel_csv,
    parse_accel_latest_position,
)

HEADER = (
    "device_id,sample_index,timestamp_utc,"
    "adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
    "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,"
    "latitude,longitude,altitude_m,rtk_status,h_acc_m\n"
)

SAMPLES = (
    "ROVER-01,0,2026-10-27 00:00:00.000,"
    "0.1,0.2,9.8,0.1,0.2,9.8,0,0,0,0,0\n"
    "ROVER-01,1,2026-10-27 00:00:00.001,"
    "0,0,0,0,0,0,0,0,0,0,0\n"
)

TERMINAL = (
    "ROVER-01,0,2026-10-27 00:00:00.000,"
    "0,0,0,0,0,0,"
    "-6.86720110,107.57881055,880.6420,2,0.0184\n"
)


def test_v17_terminal_row_not_acceleration():
    samples = parse_accel_csv(HEADER + SAMPLES + TERMINAL)
    assert [s.sample_index for s in samples] == [0, 1]


def test_v17_terminal_position_available():
    positions = parse_accel_latest_position(
        HEADER + SAMPLES + TERMINAL
    )
    assert len(positions) == 1
    assert positions[0].gnss_fix_type == 2


def test_v17_no_fix_terminal_not_map_position():
    terminal = (
        "ROVER-01,0,2026-10-27 00:00:00.000,"
        "0,0,0,0,0,0,0,0,0,0,9999.0000\n"
    )
    positions = parse_accel_latest_position(
        HEADER + SAMPLES + terminal
    )
    assert positions == []
