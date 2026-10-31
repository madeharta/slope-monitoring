#!/usr/bin/env python3
"""Read-only QA backlog discovery. Does not run RTKLIB or modify databases.

Candidates require >=4 rover samples with a BASE sample within +/-2 seconds
in the same UTC hour. Job ledger and existing solutions are used to avoid
silent reprocessing when upstream NAV or input fingerprints change.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from dataclasses import dataclass

UTC = dt.timezone.utc
ROVERS = ('ROVER-B1-01', 'ROVER-B1-02')

# Restrict the query to an operator-defined historical horizon and to a bounded
# number of rows; never scan unbounded GNSS history on the production server.
CANDIDATE_SQL = """
WITH rover_hours AS (
 SELECT date_trunc('hour', s.time) AS window_utc, s.device_id AS rover
 FROM public.gnss_raw_samples s
 JOIN public.devices d ON d.device_id = s.device_id
 WHERE d.site_id = $1 AND s.device_id = ANY($2::text[])
   AND s.time >= $3 AND s.time < $4
 GROUP BY 1,2
), candidate AS (
 SELECT h.window_utc, h.rover, count(*)::int AS matched
 FROM rover_hours h
 JOIN public.gnss_raw_samples r
   ON r.device_id = h.rover
  AND r.time >= h.window_utc AND r.time < h.window_utc + interval '1 hour'
 WHERE EXISTS (
   SELECT 1 FROM public.gnss_raw_samples b
   JOIN public.devices bd ON bd.device_id=b.device_id
   WHERE bd.site_id=$1 AND b.device_id=$5
     AND b.time >= h.window_utc AND b.time < h.window_utc + interval '1 hour'
     AND b.time BETWEEN r.time - interval '2 seconds'
                    AND r.time + interval '2 seconds'
 )
 GROUP BY 1,2
 HAVING count(*) >= $6
)
SELECT window_utc, rover, matched FROM candidate
ORDER BY window_utc, rover LIMIT $7
"""

LEDGER_SQL = """
SELECT rover_device_id AS rover, window_start_utc AS window_utc,
       bool_or(status IN ('COMPLETED', 'RUNNING')) AS blocked,
       max(attempts) FILTER (WHERE status='FAILED') AS failed_attempts
FROM public.ppk_qa_jobs
WHERE site_id=$1 AND rover_device_id = ANY($2::text[])
  AND window_start_utc >= $3 AND window_start_utc < $4
GROUP BY 1,2
"""

# Solutions are checked independently of the fingerprint-bearing job ledger.
# This legacy solution schema stores GPS week/TOW, not UTC. GPS-UTC offset
# was 18 seconds during the bounded October 2026 acceptance window; update
# the conversion if extending discovery to another leap-second epoch.
# A single existing solution protects the whole hour from implicit reprocessing.
SOLUTION_SQL = """
SELECT rover_device_id AS rover,
       date_trunc('hour', to_timestamp(315964800 + gps_week * 604800 + gps_tow_s - 18)) AS window_utc
FROM public.ppk_qa_experimental_solutions
WHERE site_id=$1 AND rover_device_id = ANY($2::text[])
GROUP BY 1,2
"""


@dataclass(frozen=True)
class Window:
    rover: str
    start: dt.datetime
    matched: int


def select_windows(candidates, jobs, solutions, cooldowns=None, now=None, limit=3,
                   max_failed_attempts=3, newest_first=False):
    """Pure, deterministic selection. Cooldown keys: 'ROVER|YYYY-MM-DDTHH:MM:SS+00:00'."""
    if not 1 <= limit <= 3:
        raise ValueError('max 3 rover-window combinations per run')
    now = now or dt.datetime.now(UTC)
    cooldowns = cooldowns or {}
    blocked = set(solutions)
    failed = {}
    for key, status, attempts in jobs:
        if status in ('COMPLETED', 'RUNNING'):
            blocked.add(key)
        elif status == 'FAILED':
            failed[key] = max(failed.get(key, 0), attempts or 0)
    eligible = []
    for item in candidates:
        key = (item.rover, item.start)
        if key in blocked or failed.get(key, 0) >= max_failed_attempts:
            continue
        retry_after = cooldowns.get(f'{item.rover}|{item.start.isoformat()}')
        if retry_after:
            try:
                stamp = dt.datetime.fromisoformat(retry_after)
                if stamp.tzinfo is None:
                    raise ValueError('naive cooldown')
                if stamp > now:
                    continue
            except (ValueError, TypeError):
                # Invalid state is treated as a blocker, never as permission
                # to retry aggressively.
                continue
        eligible.append(item)
    eligible.sort(key=lambda row: (row.start, row.rover), reverse=newest_first)
    return eligible[:limit]


def parse_utc(value):
    value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError('UTC time with explicit offset required')
    if (value.minute, value.second, value.microsecond) != (0, 0, 0):
        raise ValueError('whole hour required')
    return value


async def discover(args):
    import asyncpg

    source_dsn = os.environ.get('PPK_QA_SOURCE_DATABASE_URL')
    writer_dsn = os.environ.get('PPK_QA_WRITER_DATABASE_URL')
    if not source_dsn or not writer_dsn:
        raise RuntimeError('dual QA database credentials required')
    since, until = parse_utc(args.since), parse_utc(args.until)
    if not dt.timedelta(hours=1) <= until - since <= dt.timedelta(days=30):
        raise ValueError('discovery range must be between one hour and 30 days')
    if until > dt.datetime.now(UTC) - dt.timedelta(minutes=20):
        raise ValueError('discovery upper bound not closed')
    source = await asyncpg.connect(dsn=source_dsn, timeout=15)
    try:
        rows = await source.fetch(CANDIDATE_SQL, args.site, list(ROVERS),
                                  since, until, args.base, 4, 1000, timeout=120)
    finally:
        await source.close()
    if len(rows) == 1000:
        raise RuntimeError('candidate scan truncated; use a narrower UTC range')
    writer = await asyncpg.connect(dsn=writer_dsn, timeout=15)
    try:
        ledger = await writer.fetch(LEDGER_SQL, args.site, list(ROVERS), since, until, timeout=30)
        solutions = await writer.fetch(SOLUTION_SQL, args.site, list(ROVERS), timeout=30)
    finally:
        await writer.close()
    jobs = []
    for row in ledger:
        key = (row['rover'], row['window_utc'])
        if row['blocked']:
            jobs.append((key, 'COMPLETED', 0))
        elif row['failed_attempts'] is not None:
            jobs.append((key, 'FAILED', row['failed_attempts']))
    candidates = [Window(row['rover'], row['window_utc'], row['matched']) for row in rows]
    # Failure and WAITING_NAV retry state is supplied by the runner when present.
    cooldowns = {}
    if args.cooldowns:
        with open(args.cooldowns, encoding='utf-8') as handle:
            cooldowns = json.load(handle)
        if not isinstance(cooldowns, dict):
            raise ValueError('invalid cooldown document')
    result = select_windows(candidates, jobs, {(r['rover'], r['window_utc']) for r in solutions},
                            cooldowns, limit=args.limit,
                            newest_first=args.newest_first)
    return [{'rover': r.rover, 'since': r.start.isoformat(),
             'until': (r.start + dt.timedelta(hours=1)).isoformat(),
             'matched': r.matched} for r in result]


def main():
    parser = argparse.ArgumentParser(description='Read-only PPK QA backlog discovery')
    parser.add_argument('--site', default='ITB-STAGING-01')
    parser.add_argument('--base', default='BASE-01')
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', required=True)
    parser.add_argument('--limit', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument('--cooldowns', help='optional read-only JSON cooldown map')
    parser.add_argument('--newest-first', action='store_true',
                        help='select latest eligible windows (recent lane only)')
    args = parser.parse_args()
    print(json.dumps({'selected': asyncio.run(discover(args))}))


if __name__ == '__main__':
    main()
