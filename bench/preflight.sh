#!/usr/bin/env bash
# MAGRIS · pre-flight check. Run this BEFORE every load run.
#
# Exists because of a real incident: an `emqtt-bench pub -c 2000 -I 1000`
# container was left running for nine hours and published ~2000 msg/s into the
# same broker throughout an entire benchmark sweep. Every CPU, memory and
# saturation figure from that sweep was contaminated and had to be discarded.
# Nothing in the harness noticed — JMeter only sees its own samples, and
# `docker stats` faithfully recorded the combined load.
#
# Usage:  bash bench/preflight.sh
# Exit 0 = safe to run. Exit 1 = something else is using the broker.
set -uo pipefail

BROKER="magris-variant-a-mosquitto-1"
DB="magris-variant-a-timescaledb-1"
CPU_MAX="${CPU_MAX:-2.0}"     # idle broker should sit near 0%
MEM_MAX_MIB="${MEM_MAX_MIB:-8}"  # ~4.5 MiB with no sessions; sessions add up fast
FAIL=0

say() { printf '%-42s %s\n' "$1" "$2"; }

echo "=== MAGRIS pre-flight ==="

# 1. Required containers up
for c in "$BROKER" "$DB"; do
  if docker ps --format '{{.Names}}' | grep -qx "$c"; then
    say "$c" "up"
  else
    say "$c" "MISSING -- run: docker compose up -d"; FAIL=1
  fi
done

# 2. No other containers touching the stack. The stray was an unnamed
#    `emqx/emqtt-bench`, so flag anything that is not part of variant-a.
STRAY=$(docker ps --format '{{.Names}}|{{.Image}}' | grep -v "^magris-variant-a-" || true)
if [ -n "$STRAY" ]; then
  echo
  echo "!! other containers are running:"
  echo "$STRAY" | sed 's/^/     /'
  echo "   If any of them publishes to this broker, the run is invalid."
  echo "   Stop it with: docker stop <name>"
  FAIL=1
else
  say "no stray containers" "ok"
fi

# 3. Broker actually idle. This is the check that would have caught the
#    incident: a busy "idle" broker means someone else is publishing.
read -r CPU MEM < <(docker stats --no-stream --format '{{.CPUPerc}} {{.MemUsage}}' "$BROKER" 2>/dev/null \
                    | awk '{gsub(/%/,"",$1); gsub(/MiB.*/,"",$2); print $1, $2}')
CPU="${CPU:-999}"; MEM="${MEM:-999}"

if awk "BEGIN{exit !($CPU <= $CPU_MAX)}"; then
  say "broker CPU idle (${CPU}%)" "ok"
else
  say "broker CPU ${CPU}%" "TOO HIGH (>${CPU_MAX}%) -- something is publishing"; FAIL=1
fi

if awk "BEGIN{exit !($MEM <= $MEM_MAX_MIB)}"; then
  say "broker memory (${MEM} MiB)" "ok"
else
  say "broker memory ${MEM} MiB" "HIGH (>${MEM_MAX_MIB} MiB) -- open sessions left over"; FAIL=1
fi

# 4. Warn about the host-side load generator, which is not a container.
if pgrep -f "loadgen/fleet.py" >/dev/null 2>&1; then
  say "loadgen/fleet.py" "RUNNING -- stop it before a load run"; FAIL=1
else
  say "loadgen/fleet.py not running" "ok"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "PASS - broker is clean, safe to start the run."
else
  echo "FAIL - fix the above first. A contaminated run looks completely normal"
  echo "       in the .jtl; you will not notice until the numbers stop making sense."
fi
exit "$FAIL"
