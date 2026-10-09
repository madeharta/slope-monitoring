from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.pipeline.preprocessing.ppk_engine import (
    PPK_ACCEPTANCE_SCHEMA_VERSION,
    PPK_ENGINE_NAME,
    PPK_OUTPUT_SCHEMA_VERSION,
    PPKSolveError,
    build_convbin_command,
    parse_pos_file,
)
from scripts.prepare_itb_uploads import ubx_valid
from services.rinex_service.normalizer import normalize_rinex_transport
from ml.pipeline.preprocessing.ppk_time_integrity import (
    assess_clock_deltas,
    assess_receiver_epochs,
    assess_receiver_overlap,
)

GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
GPS_WEEK_SECONDS = 604800.0


class ConversionError(ValueError):
    pass


def rawx_time_info(frame: bytes) -> dict:
    if len(frame) < 16 or frame[2:4] != b"\x02\x15":
        raise ConversionError("Frame is not UBX RXM-RAWX")

    rcv_tow, week, leap_s, num_meas, rec_stat, version, _reserved = (
        struct.unpack_from("<dHbBBBH", frame, 6)
    )
    usable = week > 0 and num_meas > 0
    gps_seconds = week * GPS_WEEK_SECONDS + rcv_tow if usable else None
    utc = None

    if gps_seconds is not None and rec_stat & 0x01:
        utc = GPS_EPOCH + timedelta(seconds=gps_seconds - leap_s)

    return {
        "rcv_tow": rcv_tow,
        "week": week,
        "leap_s": leap_s,
        "num_meas": num_meas,
        "rec_stat": rec_stat,
        "version": version,
        "usable": usable,
        "gps_seconds": gps_seconds,
        "utc": utc,
    }


def read_rawx(path: Path) -> tuple[str, bytes, dict]:
    frames: list[bytes] = []
    timestamps: list[str] = []
    ids: set[str] = set()
    gps_seconds_values: list[float] = []
    gnss_utc_values: list[datetime] = []
    clock_deltas: list[float] = []
    zero_measurement_frames = 0

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = ["device_id", "timestamp_utc", "gnss_raw_payload_base64"]
        if reader.fieldnames != required:
            raise ConversionError(f"Unsupported CSV columns: {reader.fieldnames!r}")

        for line_number, row in enumerate(reader, 2):
            if None in row or any(row[k] is None for k in required):
                raise ConversionError(f"Malformed CSV line {line_number}")

            device_id = row["device_id"].strip()
            timestamp_raw = row["timestamp_utc"].strip()
            value = row["gnss_raw_payload_base64"].strip()

            if not device_id:
                raise ConversionError(f"Missing device_id at line {line_number}")

            try:
                source_ts = datetime.strptime(
                    timestamp_raw,
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise ConversionError(
                    f"Invalid UTC timestamp at line {line_number}"
                ) from exc

            if not ubx_valid(value):
                raise ConversionError(
                    f"Invalid UBX length/checksum/base64 at line {line_number}"
                )

            frame = base64.b64decode(value, validate=True)
            if frame[2:4] != b"\x02\x15":
                raise ConversionError(
                    f"Not UBX RXM-RAWX at line {line_number}: {frame[2:4].hex()}"
                )

            time_info = rawx_time_info(frame)
            if time_info["num_meas"] == 0:
                zero_measurement_frames += 1

            if time_info["usable"]:
                gps_seconds_values.append(time_info["gps_seconds"])

                if time_info["utc"] is not None:
                    gnss_utc_values.append(time_info["utc"])
                    clock_deltas.append(
                        (source_ts - time_info["utc"]).total_seconds()
                    )

            ids.add(device_id)
            frames.append(frame)
            timestamps.append(timestamp_raw)

    if not frames or len(ids) != 1 or not next(iter(ids)):
        raise ConversionError(
            "Require nonempty single-device RAWX file; never guess identity"
        )
    if not gps_seconds_values:
        raise ConversionError(
            "RAWX file contains no usable GNSS measurement epochs"
        )

    duplicates = sum(
        count - 1
        for count in Counter(timestamps).values()
        if count > 1
    )

    return next(iter(ids)), b"".join(frames), {
        "rows": len(frames),
        "duplicate_timestamp_rows_preserved": duplicates,
        "first_timestamp": min(timestamps),
        "last_timestamp": max(timestamps),
        "usable_gnss_epochs": len(gps_seconds_values),
        "zero_measurement_frames": zero_measurement_frames,
        "first_gps_seconds": min(gps_seconds_values),
        "last_gps_seconds": max(gps_seconds_values),
        "first_gnss_utc": (
            min(gnss_utc_values).isoformat()
            if gnss_utc_values
            else None
        ),
        "last_gnss_utc": (
            max(gnss_utc_values).isoformat()
            if gnss_utc_values
            else None
        ),
        "csv_gnss_delta_seconds_min": (
            min(clock_deltas)
            if clock_deltas
            else None
        ),
        "csv_gnss_delta_seconds_max": (
            max(clock_deltas)
            if clock_deltas
            else None
        ),
        "clock_integrity": assess_clock_deltas(clock_deltas),
        "receiver_time_integrity": assess_receiver_epochs(gps_seconds_values),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def invoke(args: list[str], output: Path, name: str) -> None:
    try:
        result = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f"{name}: execution failed: {exc}") from exc

    if (
        result.returncode != 0
        or not output.exists()
        or output.stat().st_size == 0
    ):
        raise ConversionError(
            f"{name}: no usable output (rc={result.returncode}); "
            f"stderr={result.stderr[-1500:]}"
        )


def _binary(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which(value)



def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binary_identity(path: str) -> dict:
    resolved = Path(path)
    return {
        "path": str(resolved),
        "sha256": _sha256_path(resolved) if resolved.is_file() else None,
    }


def _engine_acceptance(status: str, **gates) -> dict:
    return {
        "schema_version": PPK_ACCEPTANCE_SCHEMA_VERSION,
        "status": status,
        "production_geodetic_validation": False,
        "gates": gates,
    }


def execute(
    input_path: Path,
    output_dir: Path,
    base_input: Path | None = None,
    base_coords: tuple[float, float, float] | None = None,
    nav: Path | None = None,
    convbin: str = "convbin",
    rnx2rtkp: str = "rnx2rtkp",
    rtklib_config: Path | None = None,
    base_reference_type: str | None = None,
) -> dict:
    if base_input is None and (base_coords is not None or nav is not None):
        raise ConversionError(
            "Base coordinate/NAV supplied without separate base stream"
        )
    if base_input is not None and (base_coords is None or nav is None):
        raise ConversionError(
            "PPK requires separate base CSV, base reference coordinates, "
            "and RINEX NAV"
        )
    if rtklib_config is not None and (not rtklib_config.is_file() or rtklib_config.stat().st_size == 0):
        raise ConversionError(f"RTKLIB config file not found or empty: {rtklib_config}")

    rover_id, rover_bytes, rover_info = read_rawx(input_path)
    base_bytes = None
    base_id = None
    base_info = None

    pairing_info = None
    if base_input is not None:
        base_id, base_bytes, base_info = read_rawx(base_input)

        receiver_time_failures = [
            label
            for label, info in (("base", base_info), ("rover", rover_info))
            if info["receiver_time_integrity"]["acceptance_blocking"]
        ]
        if receiver_time_failures:
            raise ConversionError(
                "Non-monotonic RXM-RAWX receiver time for "
                + ", ".join(receiver_time_failures)
            )
        pairing_info = assess_receiver_overlap(base_info, rover_info)

        if input_path.resolve() == base_input.resolve() or base_id == rover_id:
            raise ConversionError(
                "Base and rover must be distinct confirmed physical streams"
            )

        if pairing_info["status"] != "OVERLAP":
            raise ConversionError(
                "Base and rover RAWX receiver-time observation periods do not overlap"
            )

        if not nav.is_file() or nav.stat().st_size == 0:
            raise ConversionError(
                "Nonempty RINEX navigation file is required"
            )

        lat, lon, _alt = base_coords
        if not (
            all(math.isfinite(value) for value in base_coords)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            raise ConversionError(
                "Invalid base reference latitude/longitude/height"
            )

    if output_dir.exists() and any(output_dir.iterdir()):
        raise ConversionError(
            "Output directory must be empty; overwrite forbidden"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "acceptance_schema_version": PPK_ACCEPTANCE_SCHEMA_VERSION,
        "output_schema_version": PPK_OUTPUT_SCHEMA_VERSION,
        "processing_engine": PPK_ENGINE_NAME,
        "mode": "RAWX_ONLY",
        "ppk_validated": False,
        "rover_id_as_provided": rover_id,
        "rover": rover_info,
        "base_id_as_provided": base_id,
        "base": base_info,
        "time_integrity": {
            "pairing_time_basis": "rxm_rawx_gps_seconds",
            "rover_clock": rover_info["clock_integrity"],
            "base_clock": base_info["clock_integrity"] if base_info is not None else None,
            "pairing": pairing_info,
        },
        "base_reference": (
            {
                "type": base_reference_type or "UNSPECIFIED",
                "latitude": base_coords[0],
                "longitude": base_coords[1],
                "ellipsoidal_height_m": base_coords[2],
                "production_geodetic_validation": (
                    base_reference_type == "SURVEYED_PRODUCTION"
                ),
            }
            if base_coords is not None
            else None
        ),
        "warning": (
            "No geodetic accuracy or displacement validated. "
            "Device IDs are source labels only."
        ),
        "engine_acceptance": _engine_acceptance(
            "PENDING_RUNTIME", rawx_input=True, convbin=False, navigation=False,
            rnx2rtkp=False, parser=False, provenance=False,
        ),
    }

    rover_ubx = output_dir / "rover.ubx"
    rover_ubx.write_bytes(rover_bytes)
    manifest["rover_ubx_sha256"] = hashlib.sha256(rover_bytes).hexdigest()

    if base_bytes is not None:
        base_ubx = output_dir / "base.ubx"
        base_ubx.write_bytes(base_bytes)
        manifest["base_ubx_sha256"] = hashlib.sha256(base_bytes).hexdigest()

    convbin_exe = _binary(convbin)
    if convbin_exe is None:
        manifest["conversion"] = (
            "NOT_RUN_CONVBIN_MISSING; UBX exported and verified only"
        )
        manifest["engine_acceptance"] = _engine_acceptance(
            "BLOCKED_RUNTIME", rawx_input=True, convbin=False, navigation=False,
            rnx2rtkp=False, parser=False, provenance=True,
        )
    else:
        manifest["convbin"] = _binary_identity(convbin_exe)
        rover_command, rover_obs = build_convbin_command(
            convbin_exe,
            rover_ubx,
            output_dir,
            "rover",
        )
        invoke(rover_command, rover_obs, "convbin rover")
        manifest["rover_obs_sha256"] = _sha256_path(rover_obs)
        manifest["conversion"] = (
            "RINEX_OBS_GENERATED_NOT_GEODETICALLY_VALIDATED"
        )
        manifest["engine_acceptance"] = _engine_acceptance(
            "PARTIAL_CONVBIN_ONLY", rawx_input=True, convbin=True, navigation=False,
            rnx2rtkp=False, parser=False, provenance=True,
        )

        if base_bytes is not None:
            base_command, base_obs = build_convbin_command(
                convbin_exe,
                base_ubx,
                output_dir,
                "base",
            )
            invoke(base_command, base_obs, "convbin base")
            manifest["base_obs_sha256"] = _sha256_path(base_obs)

            solver = _binary(rnx2rtkp)
            if solver is None:
                manifest["ppk"] = "NOT_RUN_RNX2RTKP_MISSING"
                manifest["engine_acceptance"] = _engine_acceptance(
                    "BLOCKED_RUNTIME", rawx_input=True, convbin=True, navigation=True,
                    rnx2rtkp=False, parser=False, provenance=True,
                )
            else:
                manifest["rnx2rtkp"] = _binary_identity(solver)
                lat, lon, alt = base_coords
                nav_plain = output_dir / "navigation.rnx"

                try:
                    nav_content = normalize_rinex_transport(
                        nav.read_bytes()
                    ).content
                except Exception as exc:
                    raise ConversionError(
                        f"Unable to materialize RINEX NAV: {exc}"
                    ) from exc

                nav_plain.write_bytes(nav_content)
                manifest["navigation_transport_sha256"] = _sha256_path(nav)
                manifest["navigation_normalized_sha256"] = _sha256_path(nav_plain)
                pos = output_dir / "solution.pos"

                solver_command = [solver]
                if rtklib_config is not None:
                    solver_command.extend(["-k", str(rtklib_config)])
                    manifest["rtklib_config_mode"] = "explicit_file"
                    manifest["rtklib_config_sha256"] = _sha256_path(rtklib_config)
                else:
                    solver_command.extend(["-p", "2"])
                    manifest["rtklib_config_mode"] = "rtklib_default_kinematic"
                    manifest["rtklib_config_sha256"] = None
                solver_command.extend([
                    "-l", str(lat), str(lon), str(alt),
                    "-o", str(pos), str(rover_obs), str(base_obs), str(nav_plain),
                ])

                invoke(solver_command, pos, "rnx2rtkp")

                try:
                    solutions = parse_pos_file(pos)
                except PPKSolveError as exc:
                    raise ConversionError(str(exc)) from exc

                quality_counts = Counter(
                    solution.rtklib_quality
                    for solution in solutions
                )
                manifest["mode"] = "PPK_OUTPUT_UNVALIDATED"
                manifest["engine_acceptance"] = _engine_acceptance(
                    "PASS", rawx_input=True, convbin=True, navigation=True,
                    rnx2rtkp=True, parser=True, provenance=True,
                )
                manifest["ppk"] = {
                    "solution_epochs": len(solutions),
                    "first_solution_utc": (
                        solutions[0].timestamp_utc.isoformat()
                    ),
                    "last_solution_utc": (
                        solutions[-1].timestamp_utc.isoformat()
                    ),
                    "rtklib_quality_counts": {
                        str(key): value
                        for key, value in sorted(quality_counts.items())
                    },
                    "max_h_acc_m": max(
                        solution.h_acc_m
                        for solution in solutions
                    ),
                    "nav_sha256": _sha256_path(nav),
                    "solution_pos_sha256": _sha256_path(pos),
                    "note": (
                        "RTKLIB output parsed; independent field accuracy "
                        "validation still required"
                    ),
                }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="single-device rover/unknown RAWX CSV",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new/empty output directory",
    )
    parser.add_argument(
        "--base-input",
        type=Path,
        help="distinct, simultaneous base RAWX CSV",
    )
    parser.add_argument("--base-lat", type=float)
    parser.add_argument("--base-lon", type=float)
    parser.add_argument("--base-alt-ellipsoid-m", type=float)
    parser.add_argument(
        "--nav",
        type=Path,
        help="RINEX navigation/ephemeris from matching period",
    )
    parser.add_argument(
        "--convbin",
        default=os.getenv("RTKLIB_CONVBIN_PATH", "convbin"),
    )
    parser.add_argument(
        "--rnx2rtkp",
        default=os.getenv("RTKLIB_RNX2RTKP_PATH", "rnx2rtkp"),
    )
    parser.add_argument(
        "--rtklib-config",
        type=Path,
        default=Path(os.getenv(
            "RTKLIB_CONFIG_FILE",
            str(Path(__file__).resolve().parents[1] / "config" / "rtklib_ppk.conf"),
        )),
        help="RTKLIB processing config used for engine acceptance",
    )
    parser.add_argument(
        "--base-reference-type",
        choices=("ENGINE_TEST_SPP_APPROXIMATE", "SURVEYED_PRODUCTION"),
        help="provenance classification for supplied base coordinates",
    )
    parser.add_argument(
        "--require-engine-pass",
        action="store_true",
        help="exit nonzero unless the full convbin+NAV+rnx2rtkp+parser chain passes",
    )
    args = parser.parse_args()

    coords = (
        args.base_lat,
        args.base_lon,
        args.base_alt_ellipsoid_m,
    )
    if (
        any(value is not None for value in coords)
        and not all(value is not None for value in coords)
    ):
        parser.error("Specify all three base reference coordinates")

    try:
        result = execute(
            args.input,
            args.output,
            args.base_input,
            coords if all(value is not None for value in coords) else None,
            args.nav,
            args.convbin,
            args.rnx2rtkp,
            args.rtklib_config,
            args.base_reference_type,
        )
    except ConversionError as exc:
        parser.exit(2, f"BLOCKED: {exc}\n")

    if args.require_engine_pass and result["engine_acceptance"]["status"] != "PASS":
        print(json.dumps(result, indent=2))
        parser.exit(3, "ENGINE ACCEPTANCE NOT PASSED\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
