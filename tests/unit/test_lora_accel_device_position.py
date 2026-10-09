from ml.pipeline.preprocessing.lora_parser import parse_accel_latest_position


def test_lora_accel_terminal_gnss_row_is_available_for_device_map():
    raw_csv = (
        "device_id,sample_index,timestamp_utc,adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,latitude,longitude,altitude_m,"
        "gnss_fix_type,h_acc_m\n"
        "ROVER-01,4984,2026-09-18 10:45:57.984,0.251,-0.063,9.787,0.026,0.127,-10.298,"
        "0,0,0,0,0\n"
        "ROVER-01,0,2026-09-18 10:45:57.984,0,0,0,0,0,0,"
        "-6.86713442,107.57874450,884.29,3,0.46\n"
    )

    positions = parse_accel_latest_position(raw_csv)

    assert len(positions) == 1
    position = positions[0]
    assert position.device_id == "ROVER-01"
    assert position.latitude == -6.86713442
    assert position.longitude == 107.57874450
    assert position.altitude_m == 884.29
    assert position.gnss_fix_type == 3
    assert position.h_acc_m == 0.46
