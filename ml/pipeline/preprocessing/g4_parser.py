from __future__ import annotations
import base64
import binascii
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from common.errors import InvalidBase64Error, InvalidCsvError
from ml.domain.canonical_schema import CanonicalAccelSample
_UBX_SYNC = b"\xb5\x62"
@dataclass(frozen=True)
class G4BlastAccel:
    samples: list[CanonicalAccelSample]
    post_blast_rawx: tuple[str, datetime, bytes]
def parse_gnss_csv(raw_csv: str) -> list[tuple[str, datetime, bytes]]:
    reader = csv.DictReader(StringIO(raw_csv))
    required = {"device_id", "timestamp_utc", "gnss_raw_payload_base64"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        missing = required - set(reader.fieldnames or [])
        raise InvalidCsvError(f"4G gnss CSV missing required column(s): {sorted(missing)}")
    out: list[tuple[str, datetime, bytes]] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            ts = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise InvalidCsvError(f"4G gnss line {line_no}: bad timestamp_utc: {exc}") from exc
        raw = _decode_ubx(row["gnss_raw_payload_base64"], f"4G gnss line {line_no}")
        out.append((row["device_id"], ts, raw))
    if not out:
        raise InvalidCsvError("4G gnss CSV contained a header but zero data rows")
    return out
def parse_accel_csv_single_post_blast_rawx(raw_csv: str) -> G4BlastAccel:
    reader = csv.DictReader(StringIO(raw_csv))
    fields = set(reader.fieldnames or [])
    required = {
        "device_id", "sample_index", "timestamp_utc",
        "adxl355_x_mps2", "adxl355_y_mps2", "adxl355_z_mps2",
        "mpu9250_x_mps2", "mpu9250_y_mps2", "mpu9250_z_mps2",
        "gnss_raw_payload_base64",
    }
    if not required.issubset(fields):
        raise InvalidCsvError(f"4G accel CSV missing required column(s): {sorted(required - fields)}")
    samples: list[CanonicalAccelSample] = []
    rawx_entries: list[tuple[str, datetime, bytes]] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            ts = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
            samples.append(
                CanonicalAccelSample(
                    device_id=row["device_id"],
                    sample_index=int(row["sample_index"]),
                    timestamp_utc=ts,
                    adxl355_xyz_mps2=(
                        float(row["adxl355_x_mps2"]), float(row["adxl355_y_mps2"]), float(row["adxl355_z_mps2"]),
                    ),
                    mpu9250_xyz_mps2=(
                        float(row["mpu9250_x_mps2"]), float(row["mpu9250_y_mps2"]), float(row["mpu9250_z_mps2"]),
                    ),
                    colocated_position=None,
                )
            )
        except (KeyError, ValueError) as exc:
            raise InvalidCsvError(f"4G accel line {line_no}: {exc}") from exc
        payload = row["gnss_raw_payload_base64"].strip()
        if payload not in {"", "0"}:
            rawx_entries.append((row["device_id"], ts, _decode_ubx(payload, f"4G accel line {line_no}")))
    if not samples:
        raise InvalidCsvError("4G accel CSV contained a header but zero data rows")
    if len(rawx_entries) != 1:
        raise InvalidCsvError(
            "4G accel override requires exactly one post-blast gnss_raw_payload_base64; "
            f"found {len(rawx_entries)}"
        )
    return G4BlastAccel(samples=samples, post_blast_rawx=rawx_entries[0])
def _decode_ubx(payload: str, context: str) -> bytes:
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidBase64Error(f"{context}: {exc}") from exc
    if not raw.startswith(_UBX_SYNC):
        raise InvalidBase64Error(f"{context}: decoded payload is not a UBX frame (bad sync bytes)")
    return raw
