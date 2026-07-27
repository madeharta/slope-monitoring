"""Run manifest — the full config + seed written alongside every run's
results so any run is reproducible (context.md §12).

A results file without its manifest is not a valid benchmark record.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any


def build_manifest(
    *,
    seed: int,
    scenario: str,
    config: dict[str, Any],
    started_at: str,
    finished_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "seed": seed,
        "config": config,
        "started_at": started_at,
        "finished_at": finished_at,
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        **(extra or {}),
    }


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
