from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from services.rinex_service import RINEXAcquisitionError, RINEXCache, RINEXNavigationAcquisition


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--station")
    parser.add_argument("--cache-dir", default=os.getenv("RINEX_CACHE_DIR", "data/rinex-cache"))
    args = parser.parse_args()
    try:
        result = RINEXNavigationAcquisition(RINEXCache(Path(args.cache_dir))).ensure(
            _timestamp(args.timestamp), station=args.station
        )
    except RINEXAcquisitionError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    resolved = result.resolved
    print(json.dumps({
        "cache_hit": result.cache_hit,
        "provider": result.provider,
        "sha256": resolved.artifact.sha256,
        "path": str(resolved.artifact.path),
        "original_name": resolved.artifact.original_name,
        "source_url": resolved.artifact.source_url,
        "station": resolved.metadata.station,
        "nominal_date": resolved.metadata.nominal_date.isoformat() if resolved.metadata.nominal_date else None,
        "version": resolved.metadata.version,
        "constellation": resolved.metadata.constellation,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
