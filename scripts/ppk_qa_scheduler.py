#!/usr/bin/env python3
"""QA-only UTC hourly scheduler. Explicit opt-in; no operational products."""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import io
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

UTC = dt.timezone.utc
MAX_BATCH_WINDOWS = 24
DEFAULT_ROVERS = ("ROVER-B1-01", "ROVER-B1-02")
REF = (-6.867113383, 107.578782477, 880.5476)  # provisional SPP, not surveyed


def windows(now: dt.datetime, grace_minutes: int, backfill_hours: int):
    if now.tzinfo is None or not 10 <= grace_minutes <= 180 or not 1 <= backfill_hours <= 6:
        raise ValueError('invalid timezone/grace/backfill')
    end = (now.astimezone(UTC) - dt.timedelta(minutes=grace_minutes)).replace(minute=0, second=0, microsecond=0)
    return [(end - dt.timedelta(hours=i+1), end - dt.timedelta(hours=i)) for i in reversed(range(backfill_hours))]


def planned_windows(now, grace_minutes, backfill_hours, since=None, until=None, max_windows=MAX_BATCH_WINDOWS):
    """Select closed hourly windows; explicit backlog is bounded and chronological."""
    recent = windows(now, grace_minutes, backfill_hours)
    if since is None and until is None:
        return recent
    if since is None or until is None:
        raise ValueError('backlog requires both --since and --until')
    try:
        beginning = dt.datetime.fromisoformat(since.replace('Z', '+00:00'))
        finish = dt.datetime.fromisoformat(until.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid backlog timestamp') from exc
    if beginning.tzinfo is None or finish.tzinfo is None:
        raise ValueError('backlog timestamps must be timezone-aware')
    beginning, finish = beginning.astimezone(UTC), finish.astimezone(UTC)
    if (beginning.minute, beginning.second, beginning.microsecond) != (0, 0, 0) or \
       (finish.minute, finish.second, finish.microsecond) != (0, 0, 0):
        raise ValueError('backlog bounds must align to whole UTC hours')
    cutoff = recent[-1][1]
    count = int((finish - beginning).total_seconds() / 3600)
    if not 1 <= count <= max_windows or beginning + dt.timedelta(hours=count) != finish:
        raise ValueError('backlog length outside bounded hourly range')
    if finish > cutoff:
        raise ValueError('backlog includes an unclosed window')
    return [(beginning + dt.timedelta(hours=i), beginning + dt.timedelta(hours=i+1))
            for i in range(count)]


def selected_rovers(rover_args):
    rovers = list(dict.fromkeys(rover_args or DEFAULT_ROVERS))
    if not rovers or len(rovers) > 2 or any(r not in DEFAULT_ROVERS for r in rovers):
        raise ValueError('invalid QA rover selection')
    return rovers



MAX_NAV_GZIP_BYTES = 30 * 1024 * 1024
MAX_NAV_EXPANDED_BYTES = 80 * 1024 * 1024
NAV_WALL_TIMEOUT_SECONDS = 75
NAV_SOCKET_TIMEOUT_SECONDS = 15
NAV_CHUNK_BYTES = 64 * 1024


def bounded_nav_decompress(compressed: bytes) -> bytes:
    """Reject overlarge or malformed NAV gzip before or during expansion."""
    if len(compressed) > MAX_NAV_GZIP_BYTES:
        raise ValueError('NAV compressed size too large')
    out = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
            while True:
                remaining = MAX_NAV_EXPANDED_BYTES - len(out)
                block = stream.read(min(1024 * 1024, remaining + 1))
                if not block:
                    break
                if len(block) > remaining:
                    raise ValueError('NAV expanded size too large')
                out.extend(block)
    except (EOFError, OSError) as exc:
        raise ValueError('NAV corrupt or truncated gzip') from exc
    return bytes(out)



class NavDeadlineExceeded(TimeoutError):
    """Overall IGS download deadline, independent of per-socket timeout."""


def download_nav(url: str) -> bytes:
    """Bound total download time AND size. Never retain unvalidated partial data.

    The QA scheduler executes on Linux in the main Python thread. SIGALRM is
    deliberately not installed from other threads (fail closed instead).
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('NAV downloader requires main thread')
    if not hasattr(signal, 'setitimer'):
        raise RuntimeError('NAV deadline unsupported on this platform')
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0] > 0:
        raise RuntimeError('NAV deadline conflict with existing timer')
    old_handler = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    total = 0

    def on_timeout(_signum, _frame):
        raise NavDeadlineExceeded('NAV download exceeded wall-clock deadline')

    signal.signal(signal.SIGALRM, on_timeout)
    try:
        signal.setitimer(signal.ITIMER_REAL, NAV_WALL_TIMEOUT_SECONDS)
        request = urllib.request.Request(url, headers={'User-Agent': 'MAGRIS-QA-NAV/1'})
        with urllib.request.urlopen(request, timeout=NAV_SOCKET_TIMEOUT_SECONDS) as response:
            # Redirects to HTML/login pages must not be interpreted as NAV.
            if response.headers.get('Content-Type', '').lower().startswith('text/html'):
                raise ValueError('NAV source returned HTML')
            chunks = []
            while True:
                chunk = response.read(min(NAV_CHUNK_BYTES, MAX_NAV_GZIP_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_NAV_GZIP_BYTES:
                    raise ValueError('NAV exceeds maximum size')
                chunks.append(chunk)
        print('NAV_DOWNLOAD_OK', total, round(time.monotonic() - started, 2), flush=True)
        return b''.join(chunks)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)



def download_nav_resumable(url: str, cache: Path, name: str) -> bytes:
    """Bounded, persistent HTTP Range transfer. Only callers validate/promote NAV.

    Resume requires a stable ETag or Last-Modified validator. The partial file
    and metadata are staging artifacts, never valid NAV cache entries.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('NAV downloader requires main thread')
    if not hasattr(signal, 'setitimer'):
        raise RuntimeError('NAV deadline unsupported on this platform')
    cache = Path(cache)
    part = cache / (name + '.part')
    metadata_path = cache / (name + '.part.json')
    lock_path = cache / (name + '.part.lock')

    def discard():
        part.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

    # Serialize concurrent scheduler attempts for the same date.
    with lock_path.open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        offset, metadata = 0, None
        if part.exists() and metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text())
                offset = part.stat().st_size
                if (not isinstance(metadata, dict) or metadata.get('url') != url
                        or not isinstance(metadata.get('validator'), str)
                        or not metadata['validator']
                        or not isinstance(metadata.get('total'), int)
                        or not 0 < metadata['total'] <= MAX_NAV_GZIP_BYTES
                        or not 0 < offset <= metadata['total']):
                    raise ValueError('invalid partial metadata')
            except (ValueError, OSError, json.JSONDecodeError):
                discard()
                metadata, offset = None, 0
        else:
            discard()

        if offset and offset == metadata['total']:
            return part.read_bytes()

        if signal.getitimer(signal.ITIMER_REAL)[0] > 0:
            raise RuntimeError('NAV deadline conflict with existing timer')
        old_handler = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()

        def on_timeout(_signum, _frame):
            raise NavDeadlineExceeded('NAV download exceeded wall-clock deadline')

        headers = {'User-Agent': 'MAGRIS-QA-NAV/1'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
            headers['If-Range'] = metadata['validator']

        signal.signal(signal.SIGALRM, on_timeout)
        try:
            signal.setitimer(signal.ITIMER_REAL, NAV_WALL_TIMEOUT_SECONDS)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=NAV_SOCKET_TIMEOUT_SECONDS) as response:
                if response.headers.get('Content-Type', '').lower().startswith('text/html'):
                    discard()
                    raise ValueError('NAV source returned HTML')
                status = response.status if hasattr(response, 'status') else response.getcode()
                if status not in (200, 206):
                    raise ValueError(f'unexpected NAV HTTP status {status}')
                etag = response.headers.get('ETag')
                last_modified = response.headers.get('Last-Modified')
                validator = etag or last_modified
                # Weak ETags cannot ensure byte-for-byte stable resume.
                if etag and etag.strip().startswith('W/'):
                    validator = last_modified
                if status == 206:
                    m = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not m:
                        discard()
                        raise ValueError('NAV missing or invalid Content-Range')
                    first, last, total = map(int, m.groups())
                    if (first != offset or last < first or total <= last
                            or total > MAX_NAV_GZIP_BYTES or not offset
                            or metadata is None or metadata['total'] != total
                            or metadata['validator'] != validator):
                        discard()
                        raise ValueError('NAV resume response mismatch')
                    remaining = last - first + 1
                    mode = 'ab'
                else:
                    # HTTP 200 after Range means server ignored resume or file changed.
                    discard()
                    offset = 0
                    length = response.headers.get('Content-Length')
                    try:
                        total = int(length) if length is not None else None
                    except ValueError:
                        raise ValueError('invalid NAV Content-Length')
                    if total is not None and not 0 < total <= MAX_NAV_GZIP_BYTES:
                        raise ValueError('NAV compressed size too large')
                    remaining = total
                    mode = 'wb'
                    if total is not None and validator:
                        # Metadata written atomically before transfer; the part itself
                        # is never accepted without a validated final gzip.
                        with tempfile.NamedTemporaryFile('w', dir=cache, delete=False) as f:
                            json.dump({'url': url, 'validator': validator, 'total': total}, f)
                            temp_meta = Path(f.name)
                        temp_meta.replace(metadata_path)
                with part.open(mode) as out:
                    transferred = 0
                    while True:
                        cap = MAX_NAV_GZIP_BYTES + 1 - offset - transferred
                        if cap <= 0:
                            raise ValueError('NAV exceeds maximum size')
                        if remaining is not None and transferred == remaining:
                            # Ensure EOF rather than accept an additional chunk.
                            if response.read(1):
                                raise ValueError('NAV response exceeds Content-Length')
                            break
                        size = min(NAV_CHUNK_BYTES, cap)
                        if remaining is not None:
                            size = min(size, remaining - transferred)
                        chunk = response.read1(size) if hasattr(response, 'read1') else response.read(size)
                        if not chunk:
                            break
                        out.write(chunk)
                        out.flush()
                        transferred += len(chunk)
                        if offset + transferred > MAX_NAV_GZIP_BYTES:
                            raise ValueError('NAV exceeds maximum size')
                if remaining is not None and transferred != remaining:
                    raise urllib.error.URLError('NAV truncated transfer')
                print('NAV_TRANSFER', offset + transferred, round(time.monotonic() - started, 2), flush=True)
                return part.read_bytes()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)


def nav_for(start, end, cache: Path, download: bool):
    """Return validated broadcast NAV; prefer IGS, fallback to BKG WRD_R on 404.

    Each product keeps its original filename for auditability. Existing cache is
    validated on every read; no file is promoted before decompression/validation.
    """
    day = start.date()
    doy = day.timetuple().tm_yday
    base = f'https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{day.year}/{doy:03d}/'
    products = (
        f'BRDC00IGS_R_{day.year}{doy:03d}0000_01D_MN.rnx.gz',
        f'BRDC00WRD_R_{day.year}{doy:03d}0000_01D_MN.rnx.gz',
    )
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)

    # Cache-first across both products: a previously validated WRD_R must not
    # be blocked by a network timeout while probing the uncached IGS primary.
    # A corrupt cached file fails closed; never silently treat it as valid.
    for name in products:
        gz_path = cache / name
        if not gz_path.is_file():
            continue
        if gz_path.stat().st_size > MAX_NAV_GZIP_BYTES:
            raise ValueError('NAV cached compressed size too large')
        plain = bounded_nav_decompress(gz_path.read_bytes())
        count = validate_nav(plain, start, end)
        digest = hashlib.sha256(plain).hexdigest()
        target = cache / name[:-3]
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
                tmp.write(plain)
                candidate = Path(tmp.name)
            candidate.replace(target)
        print('NAV_SOURCE:', json.dumps({'product': name, 'source_url': base + name,
                                          'sha256': digest, 'gps_ephemeris_count': count}), flush=True)
        return target, count, digest

    for index, name in enumerate(products):
        gz_path = cache / name
        if not gz_path.is_file():
            if not download:
                continue
            try:
                data = download_nav_resumable(base + name, cache, name)
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and index == 0:
                    # Missing primary product is the only reason to try WRD_R.
                    print('NAV_PRIMARY_MISSING: HTTP_404; trying BRDC00WRD_R', flush=True)
                    continue
                if exc.code in (404, 429, 500, 502, 503, 504):
                    raise RuntimeError(f'WAITING_NAV HTTP_{exc.code}') from exc
                raise RuntimeError(f'NAV_HTTP_ERROR_{exc.code}') from exc
            except NavDeadlineExceeded as exc:
                raise RuntimeError('WAITING_NAV download_deadline_exceeded') from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raise RuntimeError('WAITING_NAV network_unavailable') from exc

            if len(data) > MAX_NAV_GZIP_BYTES:
                raise ValueError('NAV exceeds maximum size')
            try:
                plain = bounded_nav_decompress(data)
                validate_nav(plain, start, end)
            except (ValueError, OSError):
                (cache / (name + '.part')).unlink(missing_ok=True)
                (cache / (name + '.part.json')).unlink(missing_ok=True)
                raise
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
                tmp.write(data)
                candidate = Path(tmp.name)
            candidate.replace(gz_path)
            (cache / (name + '.part')).unlink(missing_ok=True)
            (cache / (name + '.part.json')).unlink(missing_ok=True)

        if gz_path.stat().st_size > MAX_NAV_GZIP_BYTES:
            raise ValueError('NAV cached compressed size too large')
        plain = bounded_nav_decompress(gz_path.read_bytes())
        count = validate_nav(plain, start, end)
        target = cache / name[:-3]
        digest = hashlib.sha256(plain).hexdigest()
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
                tmp.write(plain)
                candidate = Path(tmp.name)
            candidate.replace(target)
        print('NAV_SOURCE:', json.dumps({'product': name, 'source_url': base + name,
                                          'sha256': digest, 'gps_ephemeris_count': count}), flush=True)
        return target, count, digest

    raise FileNotFoundError('WAITING_NAV cache missing')


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
    required_db_config = (
        'PPK_QA_SOURCE_DATABASE_URL',
        'PPK_QA_WRITER_DATABASE_URL',
        'PPK_QA_SOURCE_DB_NAME',
        'PPK_QA_WRITER_DB_NAME',
        'PPK_QA_SOURCE_DB_ROLE',
        'PPK_QA_WRITER_DB_ROLE',
    )
    if any(not os.getenv(key) for key in required_db_config):
        raise RuntimeError('dual-DB scheduler configuration missing')
    if args.apply and os.getenv('PPK_QA_STAGING_ONLY', 'false').lower() != 'true':
        raise RuntimeError('PPK_QA_STAGING_ONLY explicit true required')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
    env['PPK_QA_AUTOMATION_ENABLED'] = 'true' if args.apply else 'false'
    failures = []
    rovers = selected_rovers(args.rover)
    selected = planned_windows(dt.datetime.now(UTC), args.grace_minutes, args.backfill_hours,
                               args.since, args.until)
    for start, end in selected:
        for rover in rovers:
            record = {'window':start.isoformat(), 'until':end.isoformat(), 'rover':rover, 'mode':'APPLY_QA' if args.apply else 'DRY_RUN'}
            try:
                nav, count, digest = nav_for(start, end, nav_cache, not args.no_download)
                record.update(nav_gps_near=count, nav_sha256=digest, nav_validation='PRELIMINARY')
                cmd = [sys.executable, str(root/'scripts/ppk_qa_worker.py'), '--site',args.site,'--base',args.base,
                       '--rover',rover,'--base-lat',str(REF[0]),'--base-lon',str(REF[1]),'--base-alt',str(REF[2]),
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
                record['result'] = 'WAITING_NAV' if str(exc).startswith('WAITING_NAV') else 'FAILED'
                record['error_type'] = type(exc).__name__
                if str(exc).startswith('WAITING_NAV'):
                    record['nav_reason'] = str(exc).split(' ', 1)[-1][:64]
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
    ap.add_argument('--rover', action='append', choices=DEFAULT_ROVERS, help='repeat for both QA rovers; default both')
    ap.add_argument('--since', help='UTC backlog start; whole hour ISO-8601')
    ap.add_argument('--until', help='UTC backlog end; max 24 hours per run')
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
