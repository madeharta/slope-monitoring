from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from services.rinex_service import RINEXCache, RINEXCacheError, RINEXDownloadError, SRGIRINEXProvider
def _result_payload(artifact) -> dict:
    return {
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "path": str(artifact.path),
        "manifest_path": str(artifact.manifest_path),
        "original_name": artifact.original_name,
        "source_url": artifact.source_url,
    }
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache an authorized SRGI BIG RINEX download or manually downloaded RINEX artifact."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="explicit authorized HTTPS URL on srgi.big.go.id")
    source.add_argument("--file", type=Path, help="RINEX artifact already downloaded through the SRGI portal")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.getenv("RINEX_CACHE_DIR", "data/rinex-cache")),
    )
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    cache = RINEXCache(args.cache_dir)
    try:
        if args.url:
            artifact = SRGIRINEXProvider(cache).fetch(
                args.url,
                expected_sha256=args.expected_sha256,
            )
        else:
            if not args.file.is_file():
                parser.error(f"file does not exist: {args.file}")
            artifact = cache.store_bytes(
                args.file.read_bytes(),
                original_name=args.file.name,
                expected_sha256=args.expected_sha256,
                metadata={"provider": "manual_import"},
            )
    except (RINEXCacheError, RINEXDownloadError) as exc:
        parser.exit(2, f"BLOCKED: {exc}\n")
    print(json.dumps(_result_payload(artifact), indent=2))
if __name__ == "__main__":
    main()
