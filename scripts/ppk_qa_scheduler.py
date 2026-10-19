#!/usr/bin/env python3
"""QA-only UTC hourly scheduler. Explicit opt-in; no operational products."""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

UTC = dt.timezone.utc
REF = (-6.867113383, 107.578782477, 880.5476)  # provisional SPP, not surveyed


def windows(now: dt.datetime, grace_minutes: int, backfill_hours: int):
    if now.tzinfo is None or not 10 <= grace_minutes <= 180 or not 1 <= backfill_hours <= 6:
        raise ValueError('invalid timezone/grace/backfill')
    end = (now.astimezone(UTC) - dt.timedelta(minutes=grace_minutes)).replace(minute=0, second=0, microsecond=0)
    return [(end - dt.timedelta(hours=i+1), end - dt.timedelta(hours=i)) for i in reversed(range(backfill_hours))]


def nav_for(start, end, cache: Path, download: bool):
    day = start.date()
    doy = day.timetuple().tm_yday
    name = f'BRDC00WRD_S_{day.year}{doy:03d}0000_01D_MN.rnx.gz'
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    gz_path = cache / name
    if not gz_path.exists():
        if not download:
            raise FileNotFoundError('WAITING_NAV cache missing')
        url = f'https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{day.year}/{doy:03d}/{name}'
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'MAGRIS-QA-NAV/1'}), timeout=35) as response:
                data = response.read(30*1024*1024 + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError('WAITING_NAV unavailable') from exc
        if len(data) > 30*1024*1024:
            raise ValueError('NAV exceeds maximum size')
        plain = gzip.decompress(data)
        validate_nav(plain, start, end)
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
            tmp.write(data)
            candidate = Path(tmp.name)
        candidate.replace(gz_path)
    plain = gzip.decompress(gz_path.read_bytes())
    count = validate_nav(plain, start, end)
    target = cache / name[:-3]
    if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(plain).digest():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
            tmp.write(plain)
            candidate = Path(tmp.name)
        candidate.replace(target)
    return target, count, hashlib.sha256(plain).hexdigest()


def validate_nav(raw: bytes, start, end):
    if len(raw) > 80*1024*1024:
        raise ValueError('NAV expanded size too large')
    lines = raw.decode('ascii', 'replace').splitlines()
    if not lines or 'RINEX VERSION / TYPE' not in lines[0]:
        raise ValueError('NAV invalid header')
    try:
        version = float(lines[0][:9])
        header_end = next(i for i, line in enumerate(lines[:300]) if 'END OF HEADER' in line)
    except (ValueError, StopIteration) as exc:
        raise ValueError('NAV incomplete header') from exc
    if not 3 <= version < 4:
        raise ValueError('NAV unsupported format')
    pat = re.compile(r'^\s*G\d{2,3}\s+(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})(?:\s|\.)')
    found = 0
    for line in lines[header_end+1:]:
        match = pat.match(line)
        if match:
            try:
                epoch = dt.datetime(*map(int, match.groups()), tzinfo=UTC)
                found += start - dt.timedelta(hours=2) <= epoch <= end + dt.timedelta(hours=2)
            except ValueError:
                pass
    if not found:
        raise ValueError('WAITING_NAV no nearby GPS ephemeris records')
    return found  # Preliminary only; RTKLIB must validate TOE/PRN


def run(args):
    enabled = os.getenv('PPK_QA_AUTO_ENABLED', 'false').lower() == 'true'
    if args.apply and not enabled:
        raise RuntimeError('PPK_QA_AUTO_ENABLED must explicitly be true for apply')
    if args.apply and os.getenv('OPERATIONAL_ALARMS_ENABLED', 'false').lower() == 'true':
        raise RuntimeError('operational alarm gate must be OFF')
    root = Path(os.environ.get('PPK_QA_PROJECT_ROOT', Path(__file__).resolve().parents[1])).resolve()
    config = Path(os.environ.get('PPK_QA_FORWARD_CONFIG', '')).expanduser()
    if not config.is_file():
        raise RuntimeError('PPK_QA_FORWARD_CONFIG required (forward, provisional SPP)')
    nav_cache = Path(os.environ.get('PPK_QA_NAV_CACHE', '/var/cache/magris-ppk-qa')).expanduser()
    dsn = os.getenv('PPK_QA_DATABASE_URL')
    if not dsn:
        raise RuntimeError('PPK_QA_DATABASE_URL missing')
    if args.apply and os.getenv('PPK_QA_STAGING_ONLY', 'false').lower() != 'true':
        raise RuntimeError('PPK_QA_STAGING_ONLY explicit true required')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
    env['PPK_QA_AUTOMATION_ENABLED'] = 'true' if args.apply else 'false'
    failures = []
    for start, end in windows(dt.datetime.now(UTC), args.grace_minutes, args.backfill_hours):
        record = {'window':start.isoformat(), 'until':end.isoformat(), 'mode':'APPLY_QA' if args.apply else 'DRY_RUN'}
        try:
            nav, count, digest = nav_for(start, end, nav_cache, not args.no_download)
            record.update(nav_gps_near=count, nav_sha256=digest, nav_validation='PRELIMINARY')
            cmd = [sys.executable, str(root/'scripts/ppk_qa_worker.py'), '--site',args.site,'--base',args.base,
                   '--rover',args.rover,'--base-lat',str(REF[0]),'--base-lon',str(REF[1]),'--base-alt',str(REF[2]),
                   '--nav',str(nav),'--config',str(config),'--since',start.isoformat(),'--until',end.isoformat(),
                   '--window-minutes','60','--min-matched',str(args.min_matched)]
            if args.apply:
                cmd.append('--apply')
            result = subprocess.run(cmd, env=env, cwd=root, capture_output=True, text=True, timeout=args.timeout_seconds)
            record['worker_exit_code'] = result.returncode
            # Do not echo arbitrary database/error strings; record only recognized status tokens.
            statuses = re.findall(r'"status"\s*:\s*"([A-Z_]+)"', result.stdout)
            record['statuses'] = statuses
            if result.returncode or any(s == 'FAILED' for s in statuses):
                raise RuntimeError('worker failed; inspect service logs securely')
            record['result'] = ('PROCESSED_OR_IDEMPOTENT' if any(x in ('COMPLETED', 'SKIPPED_ALREADY_COMPLETED') for x in statuses) else 'WAITING_INPUT' if any(x in ('WAITING_PAIR', 'INSUFFICIENT_OVERLAP') for x in statuses) else 'NO_STATUS')
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, gzip.BadGzipFile) as exc:
            record['result'] = 'WAITING_NAV' if 'NAV' in str(exc) else 'FAILED'
            record['error_type'] = type(exc).__name__
            failures.append(record)
        print(json.dumps(record), flush=True)
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description='MAGRIS QA-only incremental one-shot scheduler; default dry-run')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--no-download', action='store_true')
    ap.add_argument('--grace-minutes', type=int, default=20)
    ap.add_argument('--backfill-hours', type=int, default=3)
    ap.add_argument('--timeout-seconds', type=int, default=600)
    ap.add_argument('--site', default='ITB-STAGING-01')
    ap.add_argument('--base', default='BASE-01')
    ap.add_argument('--rover', default='ROVER-B1-02')
    ap.add_argument('--min-matched', type=int, default=4)
    args = ap.parse_args()
    if not 60 <= args.timeout_seconds <= 900 or not 1 <= args.min_matched <= 100:
        ap.error('invalid timeout/min-matched')
    try:
        return run(args)
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({'result':'STOP', 'reason':str(exc).split(':')[0]}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
