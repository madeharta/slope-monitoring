from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ml.pipeline.preprocessing.ppk_engine import PPK_OUTPUT_SCHEMA_VERSION, RTKLibPPKEngine
from ml.pipeline.preprocessing.ppk_time_integrity import assess_receiver_overlap
from scripts.convert_rawx_ppk import read_rawx
from services.rinex_service.acquisition import RINEXNavigationAcquisition
from services.rinex_service.cache import RINEXCache


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("observed-at must include timezone, e.g. 2026-09-18T12:25:00Z")
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Paired-stream RTKLIB engine acceptance. Requires distinct Base and Rover RAWX. "
            "This does NOT validate production displacement accuracy."
        )
    )
    parser.add_argument("--rover-input", required=True, type=Path)
    parser.add_argument("--base-input", required=True, type=Path)
    parser.add_argument("--nav", type=Path, help="Optional RINEX NAV. If omitted, use cache-first public acquisition.")
    parser.add_argument("--cache-dir", default="/data/rinex-cache")
    parser.add_argument("--base-lat", required=True, type=float)
    parser.add_argument("--base-lon", required=True, type=float)
    parser.add_argument("--base-alt-ellipsoid-m", required=True, type=float)
    parser.add_argument(
        "--base-reference-type",
        required=True,
        choices=("ENGINE_TEST_SPP_APPROXIMATE", "SURVEYED_PRODUCTION"),
    )
    parser.add_argument("--observed-at", required=True, type=_utc)
    parser.add_argument("--config", default="config/rtklib_ppk.conf")
    parser.add_argument("--convbin", default="convbin")
    parser.add_argument("--rnx2rtkp", default="rnx2rtkp")
    parser.add_argument("--min-solutions", type=int, default=1)
    args = parser.parse_args()

    if args.nav is not None and (not args.nav.is_file() or args.nav.stat().st_size == 0):
        parser.error("--nav must be a non-empty RINEX navigation file")

    rover_id, rover_rawx, rover_info = read_rawx(args.rover_input)
    base_id, base_rawx, base_info = read_rawx(args.base_input)
    if base_id == rover_id or base_rawx == rover_rawx:
        parser.error("base and rover must be distinct physical RAWX streams")
    for label, info in (("base", base_info), ("rover", rover_info)):
        if info["receiver_time_integrity"]["acceptance_blocking"]:
            parser.error(f"{label} RXM-RAWX receiver time is non-monotonic")
    pairing = assess_receiver_overlap(base_info, rover_info)
    if pairing["status"] != "OVERLAP":
        parser.error("Base/Rover internal GNSS receiver epochs do not overlap")

    acquisition = None if args.nav is not None else RINEXNavigationAcquisition(RINEXCache(args.cache_dir))
    engine = RTKLibPPKEngine(
        args.base_lat,
        args.base_lon,
        args.base_alt_ellipsoid_m,
        convbin_path=args.convbin,
        rnx2rtkp_path=args.rnx2rtkp,
        nav_file=str(args.nav) if args.nav is not None else None,
        navigation_acquisition=acquisition,
        rtklib_config_file=args.config,
    )
    result = engine.solve_window(base_rawx, rover_rawx, observed_at=args.observed_at)
    if len(result.solutions) < args.min_solutions:
        raise SystemExit(f"FAIL: only {len(result.solutions)} solution epochs; minimum={args.min_solutions}")

    report = {
        "pass": True,
        "scope": "ENGINE_ONLY_PAIRED_STREAMS",
        "production_valid": False,
        "schema_version": PPK_OUTPUT_SCHEMA_VERSION,
        "base_id": base_id,
        "base_reference": {
            "type": args.base_reference_type,
            "latitude": args.base_lat,
            "longitude": args.base_lon,
            "ellipsoidal_height_m": args.base_alt_ellipsoid_m,
            "production_geodetic_validation": (
                args.base_reference_type == "SURVEYED_PRODUCTION"
            ),
        },
        "rover_id": rover_id,
        "base_rawx_frames": base_info["rows"],
        "rover_rawx_frames": rover_info["rows"],
        "time_integrity": {
            "base_clock": base_info["clock_integrity"],
            "rover_clock": rover_info["clock_integrity"],
            "base_receiver": base_info["receiver_time_integrity"],
            "rover_receiver": rover_info["receiver_time_integrity"],
            "pairing": pairing,
        },
        "solution_epochs": len(result.solutions),
        "first_solution": result.solutions[0].to_contract(),
        "navigation_sha256": result.navigation_sha256,
        "normalized_navigation_sha256": result.normalized_navigation_sha256,
        "navigation_provider": result.navigation_provider,
        "navigation_cache_hit": result.navigation_cache_hit,
        "rtklib_config_sha256": result.rtklib_config_sha256,
        "provenance": {
            "base_rawx_sha256": result.base_rawx_sha256,
            "rover_rawx_sha256": result.rover_rawx_sha256,
            "base_obs_sha256": result.base_obs_sha256,
            "rover_obs_sha256": result.rover_obs_sha256,
            "convbin_sha256": result.convbin_sha256,
            "rnx2rtkp_sha256": result.rnx2rtkp_sha256,
            "solution_pos_sha256": result.solution_pos_sha256,
        },
        "warning": "Engine acceptance only. Do not use as ground truth or operational displacement acceptance.",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
