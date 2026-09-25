from __future__ import annotations
import base64
import binascii
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from common.errors import InvalidBase64Error, InvalidCsvError
from ml.domain.canonical_schema import (
    CanonicalAccelSample,
    CanonicalPositionSample,
    DeviceRole,
    PositionSource,
)
_UBX_SYNC = b"\xb5\x62"
_COMBINED_GNSS_COLUMNS = {
    "device_id", "timestamp_utc", "latitude", "longitude", "altitude_m",
    "gnss_fix_type", "h_acc_m", "gnss_raw_payload_base64",
}
_ACCEL_COLUMNS = {
    "device_id", "sample_index", "timestamp_utc",
    "adxl355_x_mps2", "adxl355_y_mps2", "adxl355_z_mps2",
    "mpu9250_x_mps2", "mpu9250_y_mps2", "mpu9250_z_mps2",
    "latitude", "longitude", "altitude_m", "gnss_fix_type", "h_acc_m",
}
@dataclass(frozen=True)
class LoRaCombinedGnss:
    rawx_rows: list[tuple[str, datetime, bytes]]
    position_rows: list[CanonicalPositionSample]
def parse_combined_gnss_csv(raw_csv: str, base_device_id: str) -> LoRaCombinedGnss:
    reader = csv.DictReader(StringIO(raw_csv))
    fields = set(reader.fieldnames or [])
    if not _COMBINED_GNSS_COLUMNS.issubset(fields):
        raise InvalidCsvError(
            f"LoRa gnss CSV missing required column(s): {sorted(_COMBINED_GNSS_COLUMNS - fields)}"
        )
    rawx_rows: list[tuple[str, datetime, bytes]] = []
    positions: list[CanonicalPositionSample] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            ts = _parse_utc(row["timestamp_utc"])
            device_id = row["device_id"].strip()
            payload = row["gnss_raw_payload_base64"].strip()
            if device_id == base_device_id:
                if payload in {"", "0"}:
                    raise InvalidCsvError(f"LoRa gnss line {line_no}: BASE row missing RAWX payload")
                raw = _decode_ubx(payload, f"LoRa gnss line {line_no}")
                rawx_rows.append((device_id, ts, raw))
            else:
                if payload not in {"", "0"}:
                    raise InvalidCsvError(
                        f"LoRa gnss line {line_no}: rover row must not contain RAWX payload"
                    )
                positions.append(
                    CanonicalPositionSample(
                        device_id=device_id,
                        role=DeviceRole.ROVER,
                        timestamp_utc=ts,
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        altitude_m=float(row["altitude_m"]),
                        gnss_fix_type=int(row["gnss_fix_type"]),
                        h_acc_m=float(row["h_acc_m"]),
                        source=PositionSource.RTK_DIRECT,
                    )
                )
        except InvalidCsvError:
            raise
        except (KeyError, ValueError) as exc:
            raise InvalidCsvError(f"LoRa gnss line {line_no}: {exc}") from exc
    if not rawx_rows and not positions:
        raise InvalidCsvError("LoRa gnss CSV contained a header but zero data rows")
    if not rawx_rows:
        raise InvalidCsvError("LoRa gnss CSV contains no BASE RAWX row")
    return LoRaCombinedGnss(rawx_rows=rawx_rows, position_rows=positions)
def parse_accel_csv(raw_csv: str) -> list[CanonicalAccelSample]:
    reader = csv.DictReader(StringIO(raw_csv))
    fields = set(reader.fieldnames or [])
    if not _ACCEL_COLUMNS.issubset(fields):
        raise InvalidCsvError(
            f"LoRa accel CSV missing required column(s): {sorted(_ACCEL_COLUMNS - fields)}"
        )
    samples: list[CanonicalAccelSample] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            ts = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S.%f").replace(
                tzinfo=timezone.utc
            )
            position = CanonicalPositionSample(
                device_id=row["device_id"],
                role=DeviceRole.ROVER,
                timestamp_utc=ts,
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                altitude_m=float(row["altitude_m"]),
                gnss_fix_type=int(row["gnss_fix_type"]),
                h_acc_m=float(row["h_acc_m"]),
                source=PositionSource.RTK_DIRECT,
            )
            samples.append(
                CanonicalAccelSample(
                    device_id=row["device_id"],
                    sample_index=int(row["sample_index"]),
                    timestamp_utc=ts,
                    adxl355_xyz_mps2=(
                        float(row["adxl355_x_mps2"]),
                        float(row["adxl355_y_mps2"]),
                        float(row["adxl355_z_mps2"]),
                    ),
                    mpu9250_xyz_mps2=(
                        float(row["mpu9250_x_mps2"]),
                        float(row["mpu9250_y_mps2"]),
                        float(row["mpu9250_z_mps2"]),
                    ),
                    colocated_position=position,
                )
            )
        except (KeyError, ValueError) as exc:
            raise InvalidCsvError(f"LoRa accel line {line_no}: {exc}") from exc
    if not samples:
        raise InvalidCsvError("LoRa accel CSV contained a header but zero data rows")
    return samples
def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
def _decode_ubx(payload: str, context: str) -> bytes:
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidBase64Error(f"{context}: {exc}") from exc
    if not raw.startswith(_UBX_SYNC):
        raise InvalidBase64Error(f"{context}: decoded payload is not a UBX frame")
    return raw
