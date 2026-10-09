"""LoRa-mode parsers for API Spec LoRa v1.5 + project overrides."""

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
    """Parse LoRa v1.5 periodic file: BASE RAWX + rover RTK in one CSV."""
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
                # v1.5: BASE row carries RAWX and zeroes in RTK fields.
                if payload in {"", "0"}:
                    raise InvalidCsvError(f"LoRa gnss line {line_no}: BASE row missing RAWX payload")
                raw = _decode_ubx(payload, f"LoRa gnss line {line_no}")
                rawx_rows.append((device_id, ts, raw))
            else:
                # Rover row carries RTK and payload=0. Do not infer/repair a
                # malformed mixed row because provenance must stay explicit.
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
    """LoRa blast: accel 1000 Hz + resolved RTK 10 Hz fill-forward."""
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
            accel_values = (
                float(row["adxl355_x_mps2"]), float(row["adxl355_y_mps2"]), float(row["adxl355_z_mps2"]),
                float(row["mpu9250_x_mps2"]), float(row["mpu9250_y_mps2"]), float(row["mpu9250_z_mps2"]),
            )
            # The ITB LoRa accel+RTK fixture contains a terminal GNSS-only
            # snapshot row: valid fix/coordinates, sample_index reset to 0,
            # all six acceleration values zero. It is transport metadata,
            # not a 0-g acceleration observation; including it corrupts
            # ordering, PPA and PPV.
            if int(row["gnss_fix_type"]) > 0 and all(value == 0.0 for value in accel_values):
                continue
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



def parse_accel_latest_position(raw_csv: str) -> list[CanonicalPositionSample]:
    """Extract the latest valid RTK position from a LoRa accel upload.

    Accel fixtures/firmware may carry GNSS as fill-forward values on every
    accel row or as a GNSS-only terminal row. The accel parser is allowed to
    exclude a terminal GNSS-only sentinel from acceleration samples, but the
    latest valid GNSS fix must still be available to the device-map pipeline.

    Only the latest valid fix is returned because device_position_records is
    used as position history/latest-location provenance, not as a duplicate of
    every fill-forward accel row.
    """
    reader = csv.DictReader(StringIO(raw_csv))
    fields = set(reader.fieldnames or [])
    if not _ACCEL_COLUMNS.issubset(fields):
        raise InvalidCsvError(
            f"LoRa accel CSV missing required column(s): {sorted(_ACCEL_COLUMNS - fields)}"
        )

    latest: CanonicalPositionSample | None = None
    for line_no, row in enumerate(reader, start=2):
        try:
            fix = int(row["gnss_fix_type"])
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
            if fix <= 0:
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            # (0, 0) is the documented no-fix placeholder and must never
            # become a map position even if a malformed row advertises fix > 0.
            if latitude == 0.0 and longitude == 0.0:
                continue

            ts = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S.%f").replace(
                tzinfo=timezone.utc
            )
            latest = CanonicalPositionSample(
                device_id=row["device_id"].strip(),
                role=DeviceRole.ROVER,
                timestamp_utc=ts,
                latitude=latitude,
                longitude=longitude,
                altitude_m=float(row["altitude_m"]),
                gnss_fix_type=fix,
                h_acc_m=float(row["h_acc_m"]),
                source=PositionSource.RTK_DIRECT,
            )
        except (KeyError, ValueError) as exc:
            raise InvalidCsvError(f"LoRa accel line {line_no}: {exc}") from exc

    return [latest] if latest is not None else []


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
