from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from services.rinex_service.cache import RINEXCache
from services.rinex_service.resolver import RINEXNavigationResolver
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
    resolved = RINEXNavigationResolver(RINEXCache(Path(args.cache_dir))).resolve(
        _timestamp(args.timestamp), station=args.station
    )
    print(json.dumps({
        "sha256": resolved.artifact.sha256,
        "path": str(resolved.artifact.path),
        "original_name": resolved.artifact.original_name,
        "station": resolved.metadata.station,
        "nominal_date": resolved.metadata.nominal_date.isoformat() if resolved.metadata.nominal_date else None,
        "version": resolved.metadata.version,
        "constellation": resolved.metadata.constellation,
        "record_first_epoch_utc": resolved.metadata.record_first_epoch_utc.isoformat() if resolved.metadata.record_first_epoch_utc else None,
        "record_last_epoch_utc": resolved.metadata.record_last_epoch_utc.isoformat() if resolved.metadata.record_last_epoch_utc else None,
        "navigation_valid_from_utc": resolved.metadata.navigation_valid_from_utc.isoformat() if resolved.metadata.navigation_valid_from_utc else None,
        "navigation_valid_until_utc": resolved.metadata.navigation_valid_until_utc.isoformat() if resolved.metadata.navigation_valid_until_utc else None,
        "container_format": resolved.metadata.container_format,
        "transport_compression": resolved.metadata.transport_compression,
    }, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
