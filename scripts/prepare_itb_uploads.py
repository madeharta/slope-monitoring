from __future__ import annotations
import argparse
import base64
import binascii
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
SOURCES = {
    "lora_position": "[LoRa] RTK ONLY.csv",
    "lora_accel": "[LoRa] accel + RTK.csv",
    "g4_gnss": "[4g] PPK ONLY.csv",
    "g4_accel": "[4g] accel + PPK.csv",
}
COLUMNS = {
    "lora_position": ("device_id", "timestamp_utc", "latitude", "longitude", "altitude_m", "gnss_fix_type", "h_acc_m"),
    "lora_accel": ("device_id", "sample_index", "timestamp_utc", "adxl355_x_mps2", "adxl355_y_mps2", "adxl355_z_mps2", "mpu9250_x_mps2", "mpu9250_y_mps2", "mpu9250_z_mps2", "latitude", "longitude", "altitude_m", "gnss_fix_type", "h_acc_m"),
    "g4_gnss": ("device_id", "timestamp_utc", "gnss_raw_payload_base64"),
    "g4_accel": ("device_id", "sample_index", "timestamp_utc", "adxl355_x_mps2", "adxl355_y_mps2", "adxl355_z_mps2", "mpu9250_x_mps2", "mpu9250_y_mps2", "mpu9250_z_mps2", "gnss_raw_payload_base64"),
}
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
def ubx_valid(value: str) -> bool:
    try:
        frame = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return False
    if len(frame) < 8 or frame[:2] != b"\xb5\x62" or len(frame) != 8 + int.from_bytes(frame[4:6], "little"):
        return False
    a = b = 0
    for x in frame[2:-2]:
        a = (a + x) % 256
        b = (b + a) % 256
    return frame[-2:] == bytes((a, b))
def load(source: Path, kind: str):
    with source.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS[kind]:
            raise ValueError(f"Schema mismatch: {source.name}: {reader.fieldnames!r}")
        rows = list(reader)
    if not rows or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError(f"Missing/malformed rows: {source.name}")
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "accel" in kind else "%Y-%m-%d %H:%M:%S"
    for i, r in enumerate(rows, 2):
        try:
            datetime.strptime(r["timestamp_utc"], fmt)
        except ValueError as e:
            raise ValueError(f"{source.name}:{i} bad timestamp: {e}") from e
    return rows
def emit(output: Path, name: str, kind: str, rows: list[dict], original: str, status: str, reasons: list[str], uploader: str | None, role: str | None):
    dest = output / "staging" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"Refusing to overwrite generated file: {dest}")
    with dest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS[kind], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with dest.open(encoding="utf-8", newline="") as f:
        reread = list(csv.DictReader(f))
    if reread != rows:
        raise AssertionError(f"Non-lossless CSV rewrite: {name}")
    return {
        "file": f"staging/{name}", "source": original, "type": kind,
        "record_count": len(rows), "sha256": sha256(dest), "status": status,
        "upload_device_id_provisional": uploader, "upload_device_role_provisional": role,
        "x_data_type": {"lora_position": "position", "lora_accel": "accel", "g4_gnss": "gnss", "g4_accel": "accel"}[kind],
        "reasons": reasons,
    }
def convert(source: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Output directory must be empty; refusing to replace prior conversion")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "purpose": "offline staging only; no uploads executed", "sources": {}, "files": [], "release_gate": [
        "Confirm actual base ID and site registrations; BASE-01 is a proposed name, not established provenance.",
        "Establish per-rover surveyed displacement baseline before dashboard monitoring; suppress safety alarms for these fixtures.",
        "Confirm 4G physical device identity/role; lsm-unconfigured cannot be assigned to base or rover from GNSS CSV alone.",
        "Fix ingestion atomicity, device authentication and response semantics before production/device uploads.",
        "Reassess every blocked segment; no upload automation is bundled.",
    ]}
    for kind, filename in SOURCES.items():
        p = source / filename
        rows = load(p, kind)
        timestamps = Counter(r["timestamp_utc"] for r in rows)
        sample_idx = Counter(r.get("sample_index") for r in rows if "sample_index" in r)
        diag = {"original_file": filename, "sha256": sha256(p), "rows": len(rows),
                "device_ids": dict(Counter(r["device_id"] for r in rows)),
                "duplicate_timestamp_groups": sum(v > 1 for v in timestamps.values()),
                "repeated_sample_index_values": sum(v > 1 for v in sample_idx.values()),
                "time_min": min(timestamps), "time_max": max(timestamps)}
        if "accel" in kind:
            diag["sample_indices_zero"] = sample_idx["0"]
        if kind == "g4_gnss" or kind == "g4_accel":
            diag["ubx_complete_checksum_valid"] = sum(ubx_valid(r["gnss_raw_payload_base64"]) for r in rows)
            diag["ubx_invalid"] = len(rows) - diag["ubx_complete_checksum_valid"]
        if kind == "lora_accel":
            diag["no_fix_count"] = sum(r["gnss_fix_type"] == "0" for r in rows)
            diag["no_fix_h_acc_zero"] = sum(r["gnss_fix_type"] == "0" and r["h_acc_m"] == "0" for r in rows)
        manifest["sources"][kind] = diag
        if kind == "lora_position":
            windows = defaultdict(list)
            for row in rows:
                dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S")
                win = dt.replace(minute=(dt.minute // 5) * 5, second=0)
                windows[win].append(row)
            for window, subset in sorted(windows.items()):
                name = f"pos_BASE-01_{window:%Y%m%d_%H%M}.csv"
                manifest["files"].append(emit(output, name, kind, subset, filename, "BLOCKED_PENDING_BASELINE_AND_BASE_ID", [
                    "BASE-01 inferred only from API example; hardware uploader/base ID unconfirmed.",
                    "Existing displacement path lacks surveyed per-rover baseline; do not treat results as terrain movement.",
                ], "BASE-01", "base"))
        elif kind == "g4_gnss":
            windows = defaultdict(list)
            for row in rows:
                dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M:%S")
                windows[dt.replace(second=0)].append(row)
            for window, subset in sorted(windows.items()):
                repeats = sum(v > 1 for v in Counter(r["timestamp_utc"] for r in subset).values())
                reason = ["Physical 4G device role/ID is not established (lsm-unconfigured).",
                          "One GNSS stream is insufficient for base+rover PPK; no geodetic accuracy claim."]
                if repeats:
                    reason.append(f"{repeats} repeated timestamp(s) contain distinct UBX frames: database uniqueness may discard frames; no rows discarded here.")
                manifest["files"].append(emit(output, f"gnss_lsm-unconfigured_{window:%Y%m%d_%H%M}.csv", kind, subset, filename,
                                              "BLOCKED_PENDING_DEVICE_ID_AND_PPK_PAIR", reason, None, None))
        elif kind == "lora_accel":
            manifest["files"].append(emit(output, "accel_ROVER-01_20260918_104553.csv", kind, rows, filename,
                    "QUARANTINE", ["Final row resets sample_index to 0 and duplicates final timestamp; not modified or silently removed.",
                    "505 of 506 positions have gnss_fix_type=0 and h_acc_m=0 (specifies h_acc_m=9999 for no fix); position invalid for displacement.",
                    "Event duration ~5 seconds despite 2000-ms proposed default; configuration unconfirmed."], "ROVER-01", "rover"))
        else:
            manifest["files"].append(emit(output, "accel_lsm-unconfigured_20260918_000000.csv", kind, rows, filename,
                    "QUARANTINE", ["242 of 243 GNSS payload cells are literal '0', invalid base64/UBX, contrary to mandatory RAWX column.",
                    "Final row repeats sample_index=0 and duplicates timestamp; device identity unresolved.",
                    "Do not invent GNSS observations or drop rows to force validation."], None, None))
    for kind in SOURCES:
        if sum(x["record_count"] for x in manifest["files"] if x["type"] == kind) != manifest["sources"][kind]["rows"]:
            raise AssertionError(f"Row conservation failed: {kind}")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = convert(args.source, args.output)
    print(json.dumps({"source_rows": sum(x["rows"] for x in result["sources"].values()), "output_rows": sum(x["record_count"] for x in result["files"]), "files": len(result["files"]), "status": dict(Counter(f["status"] for f in result["files"]))}, indent=2))
if __name__ == "__main__":
    main()
