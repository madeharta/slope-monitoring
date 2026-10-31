import base64
import struct

import pytest

from scripts.ppk_qa_worker import rawx_measurement_count


def make_rawx(num_meas: int) -> dict:
    # RXM-RAWX header: rcvTow, week, leapS, numMeas, recStat, version, reserved
    payload = struct.pack(
        "<dHbBBBH",
        100000.0, 2400, 18, num_meas, 1, 1, 0,
    ) + bytes(32 * num_meas)

    frame = bytearray(
        b"\xb5\x62\x02\x15"
        + struct.pack("<H", len(payload))
        + payload
    )

    a = b = 0
    for value in frame[2:]:
        a = (a + value) & 255
        b = (b + a) & 255

    frame.extend((a, b))

    return {
        "raw_payload_base64": base64.b64encode(frame).decode()
    }


@pytest.mark.parametrize(
    ("num_meas", "expected"),
    [(0, 0), (1, 1), (8, 8)],
)
def test_rawx_measurement_count(num_meas, expected):
    assert rawx_measurement_count(make_rawx(num_meas)) == expected


def test_invalid_checksum_is_rejected():
    row = make_rawx(4)
    frame = bytearray(base64.b64decode(row["raw_payload_base64"]))
    frame[-1] ^= 0xFF

    row["raw_payload_base64"] = base64.b64encode(frame).decode()

    with pytest.raises(ValueError, match="checksum"):
        rawx_measurement_count(row)


def test_invalid_measurement_length_is_rejected():
    row = make_rawx(1)
    frame = bytearray(base64.b64decode(row["raw_payload_base64"]))

    # Change numMeas to 2, then recompute checksum so that the
    # measurement-length validation is exercised independently.
    frame[17] = 2

    a = b = 0
    for value in frame[2:-2]:
        a = (a + value) & 255
        b = (b + a) & 255

    frame[-2:] = bytes((a, b))
    row["raw_payload_base64"] = base64.b64encode(frame).decode()

    with pytest.raises(ValueError, match="measurement payload length"):
        rawx_measurement_count(row)
