#!/usr/bin/env python3
"""GNSS BASE SPP initializer for QA scheduler. No writes to application DB.

Input is verified UBX-RXM-RAWX from PostgreSQL source (read-only) or a local CSV
fixture. Uses scheduler's date-validated NAV and existing RTKLIB binaries.
"""
from __future__ import annotations
import argparse
import asyncio
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from scripts.ppk_qa_worker import join_rawx, rawx_measurement_count
from scripts.gnss_provisional_reference import candidate, evaluate, save_json_atomic
from scripts.ppk_qa_scheduler import nav_for

UTC = dt.timezone.utc
MAX_ROWS = 5000


def validate_rows(rows: list[dict], device_id: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    if not 0 < len(rows) <= MAX_ROWS:
        raise ValueError('RAWX_ROW_COUNT_INVALID')
    valid = []
    prev = None
    for row in rows:
        if row['device_id'] != device_id:
            raise ValueError('RAWX_WRONG_DEVICE')
        time = row['time']
        if isinstance(time, str):
            time = dt.datetime.fromisoformat(time.replace('Z', '+00:00'))
        if time.tzinfo is None or not start <= time.astimezone(UTC) < end:
            raise ValueError('RAWX_TIMESTAMP_OUT_OF_WINDOW')
        if prev is not None and time < prev:
            raise ValueError('RAWX_NOT_ORDERED')
        prev = time
        valid.append({'raw_payload_base64': row['raw_payload_base64']})
    join_rawx(valid)  # UBX boundary, class/id, checksum and base64 verification
    return [r for r in valid if rawx_measurement_count(r) > 0]


def load_fixture(path: Path) -> list[dict]:
    with path.open(newline='') as stream:
        return [
            {'device_id': row['device_id'], 'time': row['timestamp_utc'].replace(' ', 'T') + '+00:00',
             'raw_payload_base64': row['gnss_raw_payload_base64']}
            for row in csv.DictReader(stream)
        ]


async def load_database(dsn: str, device_id: str, start: dt.datetime, end: dt.datetime,
                        expected_db: str, expected_role: str) -> list[dict]:
    import asyncpg
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        await conn.execute('SET default_transaction_read_only = on')
        who = await conn.fetchrow('SELECT current_database() AS db, current_user AS role')
        if who['db'] != expected_db or who['role'] != expected_role:
            raise RuntimeError('SOURCE_DATABASE_IDENTITY_MISMATCH')
        ok = await conn.fetchval("SELECT has_table_privilege(current_user,'public.gnss_raw_samples','SELECT')")
        writes = await conn.fetchval("SELECT has_table_privilege(current_user,'public.gnss_raw_samples','INSERT,UPDATE,DELETE')")
        if not ok or writes:
            raise RuntimeError('SOURCE_ROLE_MUST_BE_READ_ONLY')
        rows = await conn.fetch("""SELECT time,device_id,raw_payload_base64
             FROM public.gnss_raw_samples
             WHERE device_id=$1 AND time >= $2 AND time < $3
             ORDER BY time LIMIT $4""", device_id, start, end, MAX_ROWS + 1)
        return [dict(x) for x in rows]
    finally:
        await conn.close()


def run_cmd(cmd: list[str], timeout: int = 120) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('RTKLIB_FAILED_' + Path(cmd[0]).name)


def solve(ubx: bytes, nav: Path, convbin: str, rnx2rtkp: str, directory: Path) -> Path:
    raw = directory / 'base.ubx'
    obs = directory / 'base.obs'
    pos = directory / 'base.pos'
    raw.write_bytes(ubx)
    # -r ubx prevents guessing the receiver format; SPP is explicitly -p 0.
    run_cmd([convbin, '-r', 'ubx', '-o', str(obs), str(raw)])
    if not obs.exists() or obs.stat().st_size == 0:
        raise RuntimeError('SPP_RINEX_OBS_MISSING')
    run_cmd([rnx2rtkp, '-p', '0', '-t', '-u', '-o', str(pos), str(obs), str(nav)])
    if not pos.exists() or pos.stat().st_size == 0:
        raise RuntimeError('SPP_POS_MISSING')
    return pos


def parse_time(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return result.astimezone(UTC)


def ensure_solution_window(pos: Path, start: dt.datetime, end: dt.datetime) -> None:
    from scripts.gnss_provisional_reference import parse_rtklib_llh
    fixes = parse_rtklib_llh(pos)
    if not fixes:
        raise ValueError('SPP_NO_SOLUTIONS')
    for fix in fixes:
        t = parse_time(fix['time'])
        if not start <= t < end:
            raise ValueError('SPP_SOLUTIONS_OUTSIDE_RAWX_WINDOW')


def run(args) -> dict:
    if not args.csv and (not args.dsn or not args.expected_db or not args.expected_role):
        raise ValueError('SOURCE_DB_CREDENTIALS_REQUIRED')
    start, end = parse_time(args.since), parse_time(args.until)
    if end <= start or end - start > dt.timedelta(hours=2):
        raise ValueError('SPP_WINDOW_INVALID')
    rows = load_fixture(args.csv) if args.csv else asyncio.run(load_database(
        args.dsn, args.base, start, end, args.expected_db, args.expected_role))
    rows = validate_rows(rows, args.base, start, end)
    if len(rows) < 10:
        raise ValueError('SPP_INSUFFICIENT_RAWX')
    binary_conv = shutil.which(args.convbin)
    binary_spp = shutil.which(args.rnx2rtkp)
    if not binary_conv or not binary_spp:
        raise RuntimeError('RTKLIB_BINARIES_MISSING')
    nav, _, digest = nav_for(start, end, args.nav_cache, not args.no_download)
    with tempfile.TemporaryDirectory(prefix='magris-spp-init-') as tmp:
        pos = solve(join_rawx(rows), nav, binary_conv, binary_spp, Path(tmp))
        ensure_solution_window(pos, start, end)
        result = candidate(pos, args.base)
    state = json.loads(args.state.read_text()) if args.state.is_file() else {}
    new_state, output = evaluate(state, result, base_id=getattr(args, 'reference_base', 'BASE-01'))
    if args.apply_local and result['status'] == 'CANDIDATE':
        save_json_atomic(args.state, new_state)
    return {'status': output['status'], 'device_id': args.base,
            'accepted_solutions': output.get('accepted_solutions', 0),
            'nav_sha256': digest, 'state_written': bool(args.apply_local and result['status'] == 'CANDIDATE'),
            'reference_epoch': new_state.get('reference_epoch'),
            'max_spread_m': output.get('max_spread_m')}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default='BASE-01', help='GNSS device to solve')
    p.add_argument('--reference-base', default='BASE-01', help='BASE whose reference must remain fixed')
    p.add_argument('--since', required=True)
    p.add_argument('--until', required=True)
    p.add_argument('--state', required=True, type=Path)
    p.add_argument('--nav-cache', required=True, type=Path)
    p.add_argument('--csv', type=Path)
    p.add_argument('--dsn', default=os.getenv('PPK_QA_SOURCE_DATABASE_URL'))
    p.add_argument('--expected-db', default=os.getenv('PPK_QA_SOURCE_DB_NAME'))
    p.add_argument('--expected-role', default=os.getenv('PPK_QA_SOURCE_DB_ROLE'))
    p.add_argument('--convbin', default=os.getenv('RTKLIB_CONVBIN_PATH', 'convbin'))
    p.add_argument('--rnx2rtkp', default=os.getenv('RTKLIB_RNX2RTKP_PATH', 'rnx2rtkp'))
    p.add_argument('--no-download', action='store_true')
    p.add_argument('--apply-local', action='store_true')
    args = p.parse_args()
    try:
        output = run(args)
        print(json.dumps(output, sort_keys=True))
        return 0 if output['status'] in ('REFERENCE_INITIALIZED_PROVISIONAL', 'REFERENCE_UNCHANGED', 'MARKER_READY', 'STALE_OBSERVATION_IGNORED', 'RELOCATION_CONFIRMING', 'REFERENCE_RELOCATED_AUTOMATICALLY') else 2
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        print(json.dumps({'status':'HOLD', 'reason':str(e).split(':')[0][:120]}), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
