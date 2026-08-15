#!/usr/bin/env bash
# MAGRIS · capture broker + DB resource usage during a load run.
# This is the SERVER-SIDE measurement — JMeter/emqtt-bench measure the client
# side; only `docker stats` tells you what the broker actually costs.
#
# Usage:  bash bench/capture-stats.sh <label> <seconds>
#   e.g.  bash bench/capture-stats.sh 500dev 180
# Output: bench/results/stats-<label>.csv  (one row per container every 2s)
set -euo pipefail

LABEL="${1:-run}"
SECS="${2:-180}"
DIR="$(cd "$(dirname "$0")" && pwd)/results"
OUT="$DIR/stats-$LABEL.csv"
CONTAINERS="magris-variant-a-mosquitto-1 magris-variant-a-timescaledb-1"

mkdir -p "$DIR"
echo "epoch,cpu_pct,mem_used,mem_pct,net_io,block_io,container" > "$OUT"
echo "capturing $CONTAINERS for ${SECS}s -> $OUT"

END=$(( $(date +%s) + SECS ))
while [ "$(date +%s)" -lt "$END" ]; do
  NOW=$(date +%s)
  # --no-stream = one snapshot; %-signs stripped so the CSV stays numeric-friendly
  docker stats --no-stream --format \
    '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.Name}}' \
    $CONTAINERS 2>/dev/null | while IFS='|' read -r cpu mem mempct net blk name; do
      echo "$NOW,${cpu//%/},$mem,${mempct//%/},$net,$blk,$name" >> "$OUT"
    done
  sleep 2
done
echo "done -> $OUT"
