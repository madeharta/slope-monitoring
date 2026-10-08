from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ml.pipeline.preprocessing.ppk_engine import PPK_OUTPUT_SCHEMA_VERSION, RTKLibPPKEngine
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
        description="Engine-only RTKLIB acceptance. This does NOT validate production displacement accuracy."
    )
    parser.add_argument("--rover-input", required=True, type=Path)
    parser.add_argument("--base-input", type=Path)
    parser.add_argument(
        "--self-baseline-smoke",
        action="store_true",
        help="Use rover fixture as both base and rover only to exercise convbin/NAV/rnx2rtkp/parser. Never production-valid.",
    )
    parser.add_argument("--nav", type=Path, help="Optional RINEX NAV. If omitted, use cache-first public acquisition.")
    parser.add_argument("--cache-dir", default="/data/rinex-cache")
    parser.add_argument("--base-lat", required=True, type=float)
    parser.add_argument("--base-lon", required=True, type=float)
    parser.add_argument("--base-alt-ellipsoid-m", required=True, type=float)
    parser.add_argument("--observed-at", required=True, type=_utc)
    parser.add_argument("--config", default="config/rtklib_ppk.conf")
    parser.add_argument("--convbin", default="convbin")
    parser.add_argument("--rnx2rtkp", default="rnx2rtkp")
    parser.add_argument("--min-solutions", type=int, default=1)
    args = parser.parse_args()

    if args.self_baseline_smoke and args.base_input is not None:
        parser.error("choose either --base-input or --self-baseline-smoke, not both")
    if not args.self_baseline_smoke and args.base_input is None:
        parser.error("--base-input is required unless --self-baseline-smoke is explicitly set")
    if args.nav is not None and (not args.nav.is_file() or args.nav.stat().st_size == 0):
        parser.error("--nav must be a non-empty RINEX navigation file")

    rover_id, rover_rawx, rover_info = read_rawx(args.rover_input)
    if args.self_baseline_smoke:
        base_id, base_rawx, base_info = f"SELF:{rover_id}", rover_rawx, rover_info
        scope = "ENGINE_ONLY_SELF_BASELINE_SMOKE"
    else:
        base_id, base_rawx, base_info = read_rawx(args.base_input)
        if base_id == rover_id:
            parser.error("base and rover device IDs must be distinct for paired engine acceptance")
        scope = "ENGINE_ONLY_PAIRED_STREAMS"

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
        "scope": scope,
        "production_valid": False,
        "schema_version": PPK_OUTPUT_SCHEMA_VERSION,
        "base_id": base_id,
        "rover_id": rover_id,
        "base_rawx_frames": base_info.get("rawx_frames"),
        "rover_rawx_frames": rover_info.get("rawx_frames"),
        "solution_epochs": len(result.solutions),
        "first_solution": result.solutions[0].to_contract(),
        "navigation_sha256": result.navigation_sha256,
        "navigation_provider": result.navigation_provider,
        "navigation_cache_hit": result.navigation_cache_hit,
        "rtklib_config_sha256": result.rtklib_config_sha256,
        "warning": "Engine acceptance only. Do not use as ground truth or operational displacement acceptance.",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
