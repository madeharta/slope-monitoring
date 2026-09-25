from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from scripts.prepare_itb_uploads import ubx_valid
class ConversionError(ValueError):
    pass
def read_rawx(path: Path) -> tuple[str, bytes, dict]:
    frames = []
    timestamps = []
    ids = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = ["device_id", "timestamp_utc", "gnss_raw_payload_base64"]
        if reader.fieldnames != required:
            raise ConversionError(f"Unsupported CSV columns: {reader.fieldnames!r}")
        import base64
        from datetime import datetime
        for line_number, row in enumerate(reader, 2):
            if None in row or any(row[k] is None for k in required):
                raise ConversionError(f"Malformed CSV line {line_number}")
            try:
                datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                raise ConversionError(f"Invalid UTC timestamp at line {line_number}") from exc
            value = row["gnss_raw_payload_base64"]
            if not ubx_valid(value):
                raise ConversionError(f"Invalid UBX length/checksum/base64 at line {line_number}")
            frame = base64.b64decode(value, validate=True)
            if frame[2:4] != b"\x02\x15":
                raise ConversionError(f"Not UBX RXM-RAWX at line {line_number}: {frame[2:4].hex()}")
            ids.add(row["device_id"])
            frames.append(frame)
            timestamps.append(row["timestamp_utc"])
    if not frames or len(ids) != 1 or not next(iter(ids)):
        raise ConversionError("Require nonempty single-device RAWX file; never guess identity")
    duplicates = sum(n - 1 for n in Counter(timestamps).values() if n > 1)
    return next(iter(ids)), b"".join(frames), {
        "rows": len(frames), "duplicate_timestamp_rows_preserved": duplicates,
        "first_timestamp": min(timestamps), "last_timestamp": max(timestamps),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
def invoke(args: list[str], output: Path, name: str) -> None:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f"{name}: execution failed: {exc}") from exc
    if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        raise ConversionError(f"{name}: no usable output (rc={result.returncode}); stderr={result.stderr[-1500:]}")
def _binary(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which(value)
def execute(input_path: Path, output_dir: Path, base_input: Path | None = None,
            base_coords: tuple[float, float, float] | None = None, nav: Path | None = None,
            convbin: str = "convbin", rnx2rtkp: str = "rnx2rtkp") -> dict:
    if base_input is None and (base_coords is not None or nav is not None):
        raise ConversionError("Base coordinate/NAV supplied without separate base stream")
    if base_input is not None and (base_coords is None or nav is None):
        raise ConversionError("PPK requires separate base CSV, surveyed base coordinates, and RINEX NAV")
    rover_id, rover_bytes, rover_info = read_rawx(input_path)
    base_bytes = None
    base_id = None
    base_info = None
    if base_input is not None:
        base_id, base_bytes, base_info = read_rawx(base_input)
        if input_path.resolve() == base_input.resolve() or base_id == rover_id:
            raise ConversionError("Base and rover must be distinct confirmed physical streams")
        if base_info["last_timestamp"] < rover_info["first_timestamp"] or rover_info["last_timestamp"] < base_info["first_timestamp"]:
            raise ConversionError("Base and rover observation periods do not overlap")
        if not nav.is_file() or nav.stat().st_size == 0:
            raise ConversionError("Nonempty RINEX navigation file is required")
        lat, lon, alt = base_coords
        import math
        if not (all(math.isfinite(n) for n in base_coords) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ConversionError("Invalid surveyed base latitude/longitude/height")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ConversionError("Output directory must be empty; overwrite forbidden")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"mode": "RAWX_ONLY", "ppk_validated": False, "rover_id_as_provided": rover_id,
                "rover": rover_info, "base_id_as_provided": base_id, "base": base_info,
                "warning": "No geodetic accuracy or displacement validated. Device IDs are source labels only."}
    rover_ubx = output_dir / "rover.ubx"
    rover_ubx.write_bytes(rover_bytes)
    manifest["rover_ubx_sha256"] = hashlib.sha256(rover_bytes).hexdigest()
    if base_bytes is not None:
        base_ubx = output_dir / "base.ubx"
        base_ubx.write_bytes(base_bytes)
        manifest["base_ubx_sha256"] = hashlib.sha256(base_bytes).hexdigest()
    convbin_exe = _binary(convbin)
    if convbin_exe is None:
        manifest["conversion"] = "NOT_RUN_CONVBIN_MISSING; UBX exported and verified only"
    else:
        rover_obs = output_dir / "rover.obs"
        invoke([convbin_exe, "-r", "ubx", "-o", str(rover_obs), str(rover_ubx)], rover_obs, "convbin rover")
        manifest["conversion"] = "RINEX_OBS_GENERATED_NOT_GEODETICALLY_VALIDATED"
        if base_bytes is not None:
            base_obs = output_dir / "base.obs"
            invoke([convbin_exe, "-r", "ubx", "-o", str(base_obs), str(base_ubx)], base_obs, "convbin base")
            solver = _binary(rnx2rtkp)
            if solver is None:
                manifest["ppk"] = "NOT_RUN_RNX2RTKP_MISSING"
            else:
                lat, lon, alt = base_coords
                pos = output_dir / "solution.pos"
                invoke([solver, "-p", "2", "-l", str(lat), str(lon), str(alt),
                        "-o", str(pos), str(rover_obs), str(base_obs), str(nav)], pos, "rnx2rtkp")
                solutions = [line for line in pos.read_text().splitlines() if line.strip() and not line.startswith("%")]
                if not solutions:
                    raise ConversionError("RTKLIB emitted no position epochs")
                manifest["mode"] = "PPK_OUTPUT_UNVALIDATED"
                manifest["ppk"] = f"{len(solutions)} position lines; require independent QC and benchmark"
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="single-device rover/unknown RAWX CSV")
    parser.add_argument("--output", required=True, type=Path, help="new/empty output directory")
    parser.add_argument("--base-input", type=Path, help="distinct, simultaneous base RAWX CSV")
    parser.add_argument("--base-lat", type=float)
    parser.add_argument("--base-lon", type=float)
    parser.add_argument("--base-alt-ellipsoid-m", type=float)
    parser.add_argument("--nav", type=Path, help="RINEX navigation/ephemeris from matching period")
    parser.add_argument("--convbin", default=os.getenv("RTKLIB_CONVBIN_PATH", "convbin"))
    parser.add_argument("--rnx2rtkp", default=os.getenv("RTKLIB_RNX2RTKP_PATH", "rnx2rtkp"))
    args = parser.parse_args()
    coords = (args.base_lat, args.base_lon, args.base_alt_ellipsoid_m)
    if any(value is not None for value in coords) and not all(value is not None for value in coords):
        parser.error("Specify all three surveyed base coordinates")
    try:
        result = execute(args.input, args.output, args.base_input,
                         coords if all(value is not None for value in coords) else None,
                         args.nav, args.convbin, args.rnx2rtkp)
    except ConversionError as exc:
        parser.exit(2, f"BLOCKED: {exc}\n")
    print(json.dumps(result, indent=2))
if __name__ == "__main__":
    main()
