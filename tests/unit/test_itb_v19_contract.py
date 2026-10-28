import base64

import pytest

from common.errors import InvalidCsvError, MissingHeaderError
from ml.pipeline.preprocessing.g4_parser import (
    parse_accel_csv_single_auxiliary_rawx,
)
from services.ingestion_service.csv_validator import (
    retained_upload_headers,
    validate_headers,
)


def valid_headers():
    return {
        "X-Communication-Mode": "4g",
        "X-Device-Id": "ROVER-B1-01",
        "X-Device-Role": "rover",
        "X-Data-Type": "gnss",
        "X-File-Name": "gnss_ROVER-B1-01_20261027_0000.csv",
        "X-Record-Count": "1",
        "X-ICCID": "89860012345678901234",
    }


def ubx_b64():
    body = bytes((0x02, 0x15, 0x00, 0x00))
    a = b = 0
    for byte in body:
        a = (a + byte) & 255
        b = (b + a) & 255
    return base64.b64encode(
        b"\xb5\x62" + body + bytes((a, b))
    ).decode()


def test_iccid_is_required():
    headers = valid_headers()
    del headers["X-ICCID"]

    with pytest.raises(MissingHeaderError):
        validate_headers(headers)


def test_iccid_is_retained():
    retained = retained_upload_headers(valid_headers())
    assert retained["X-ICCID"] == "89860012345678901234"


def test_g4_auxiliary_rawx_must_be_final_row():
    header = (
        "device_id,sample_index,timestamp_utc,"
        "adxl355_x_mps2,adxl355_y_mps2,adxl355_z_mps2,"
        "mpu9250_x_mps2,mpu9250_y_mps2,mpu9250_z_mps2,"
        "gnss_raw_payload_base64\n"
    )

    auxiliary = (
        "ROVER-B1-01,0,2026-10-27 00:00:00.000,"
        f"0,0,0,0,0,0,{ubx_b64()}\n"
    )

    sample = (
        "ROVER-B1-01,1,2026-10-27 00:00:00.001,"
        "0.1,0.2,9.8,0.1,0.2,9.7,0\n"
    )

    with pytest.raises(InvalidCsvError):
        parse_accel_csv_single_auxiliary_rawx(
            header + auxiliary + sample
        )
