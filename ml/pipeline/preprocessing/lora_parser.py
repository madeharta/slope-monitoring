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
    """Parse ITB LoRa/RTK v1.7 coordinate-only GNSS CSV."""
    reader = csv.DictReader(StringIO(raw_csv))
    required = {
        "device_id", "timestamp_utc", "latitude", "longitude",
        "altitude_m", "rtk_status", "h_acc_m", "batt",
    }

    fields = set(reader.fieldnames or [])
    missing = required - fields
    if missing:
        raise InvalidCsvError(
            f"LoRa v1.7 GNSS CSV missing required columns: {sorted(missing)}"
        )

    positions: list[CanonicalPositionSample] = []

    for line_no, row in enumerate(reader, start=2):
        try:
            if None in row or any(value is None for value in row.values()):
                raise InvalidCsvError(
                    f"LoRa GNSS line {line_no}: malformed CSV row"
                )

            device_id = row["device_id"].strip()
            if not device_id:
                raise InvalidCsvError(
                    f"LoRa GNSS line {line_no}: empty device_id"
                )

            role = (
                DeviceRole.BASE
                if device_id == base_device_id
                else DeviceRole.ROVER
            )

            status = int(row["rtk_status"])
            if status not in {0, 1, 2}:
                raise InvalidCsvError(
                    f"LoRa GNSS line {line_no}: unsupported rtk_status={status}"
                )

            import math
            battery = float(row["batt"])
            if not math.isfinite(battery):
                raise InvalidCsvError(
                    f"LoRa GNSS line {line_no}: batt must be finite"
                )

            sample = CanonicalPositionSample(
                device_id=device_id,
                role=role,
                timestamp_utc=_parse_utc(row["timestamp_utc"]),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                altitude_m=float(row["altitude_m"]),
                gnss_fix_type=status,
                h_acc_m=float(row["h_acc_m"]),
                source=PositionSource.RTK_DIRECT,
                battery_voltage_v=battery,
            )
            positions.append(sample)

        except InvalidCsvError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCsvError(
                f"LoRa GNSS line {line_no}: {exc}"
            ) from exc

    if not positions:
        raise InvalidCsvError(
            "LoRa GNSS CSV contained a header but zero data rows"
        )

    return LoRaCombinedGnss(
        rawx_rows=[],
        position_rows=positions,
    )


def _read_lora_accel_rows(raw_csv: str) -> list[dict]:
    reader = csv.DictReader(StringIO(raw_csv))
    fields = set(reader.fieldnames or [])

    required = {
        "device_id", "sample_index", "timestamp_utc",
        "adxl355_x_mps2", "adxl355_y_mps2", "adxl355_z_mps2",
        "mpu9250_x_mps2", "mpu9250_y_mps2", "mpu9250_z_mps2",
        "latitude", "longitude", "altitude_m",
        "rtk_status", "h_acc_m",
    }

    missing = required - fields
    if missing:
        raise InvalidCsvError(
            f"LoRa v1.7 accel CSV missing columns: {sorted(missing)}"
        )

    rows = list(reader)
    if not rows:
        raise InvalidCsvError("LoRa accel CSV has zero data rows")

    for line_no, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise InvalidCsvError(
                f"LoRa accel line {line_no}: malformed CSV row"
            )

    return rows


def _is_lora_accel_terminal(row: dict) -> bool:
    """Identify GNSS-only terminal metadata, including no-fix status."""
    values = (
        "adxl355_x_mps2", "adxl355_y_mps2", "adxl355_z_mps2",
        "mpu9250_x_mps2", "mpu9250_y_mps2", "mpu9250_z_mps2",
    )
    return (
        int(row["sample_index"]) == 0
        and all(float(row[name]) == 0.0 for name in values)
    )


def parse_accel_csv(raw_csv: str) -> list[CanonicalAccelSample]:
    rows = _read_lora_accel_rows(raw_csv)

    if len(rows) < 2 or not _is_lora_accel_terminal(rows[-1]):
        raise InvalidCsvError(
            "LoRa v1.7 accel requires a final GNSS metadata row"
        )

    samples = []

    for line_no, row in enumerate(rows[:-1], start=2):
        try:
            ts = datetime.strptime(
                row["timestamp_utc"], "%Y-%m-%d %H:%M:%S.%f"
            ).replace(tzinfo=timezone.utc)

            samples.append(
                CanonicalAccelSample(
                    device_id=row["device_id"].strip(),
                    sample_index=int(row["sample_index"]),
                    timestamp_utc=ts,
                    adxl355_xyz_mps2=tuple(
                        float(row[name]) for name in (
                            "adxl355_x_mps2",
                            "adxl355_y_mps2",
                            "adxl355_z_mps2",
                        )
                    ),
                    mpu9250_xyz_mps2=tuple(
                        float(row[name]) for name in (
                            "mpu9250_x_mps2",
                            "mpu9250_y_mps2",
                            "mpu9250_z_mps2",
                        )
                    ),
                    colocated_position=None,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCsvError(
                f"LoRa accel line {line_no}: {exc}"
            ) from exc

    if not samples:
        raise InvalidCsvError(
            "LoRa accel CSV contains no acceleration samples"
        )

    return samples


def parse_accel_latest_position(raw_csv: str) -> list[CanonicalPositionSample]:
    rows = _read_lora_accel_rows(raw_csv)
    row = rows[-1]

    try:
        if not _is_lora_accel_terminal(row):
            raise InvalidCsvError(
                "LoRa v1.7 accel final GNSS metadata row missing"
            )

        status = int(row["rtk_status"])
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])

        if status <= 0:
            return []

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return []

        if latitude == 0.0 and longitude == 0.0:
            return []

        ts = datetime.strptime(
            row["timestamp_utc"], "%Y-%m-%d %H:%M:%S.%f"
        ).replace(tzinfo=timezone.utc)

        return [
            CanonicalPositionSample(
                device_id=row["device_id"].strip(),
                role=DeviceRole.ROVER,
                timestamp_utc=ts,
                latitude=latitude,
                longitude=longitude,
                altitude_m=float(row["altitude_m"]),
                gnss_fix_type=status,
                h_acc_m=float(row["h_acc_m"]),
                source=PositionSource.RTK_DIRECT,
            )
        ]

    except InvalidCsvError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCsvError(
            f"LoRa accel terminal GNSS row: {exc}"
        ) from exc



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
