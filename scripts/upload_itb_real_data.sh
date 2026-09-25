#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'STOP: legacy bulk upload has been disabled for safety.' \
  'Use: python -m scripts.prepare_itb_uploads --source INPUT_DIR --output EMPTY_DIR' \
  'Review manifest.json and docs/ops/RUNBOOK_staging_and_release.md; obtain ITB confirmation before any manual upload.' >&2
exit 2
