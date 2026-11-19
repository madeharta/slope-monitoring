#!/usr/bin/env python3
"""MAGRIS v11 NAV acquisition: multi-source, epoch-gated, renewable cache.

No provisional/partial file is ever promoted to an accepted NAV product.
RINEX2 GPS broadcast NAV (NOAA) and RINEX3 mixed broadcast NAV are accepted
only after independent header/epoch validation. RTKLIB remains the final solver.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

UTC = dt.timezone.utc
MAX_COMPRESSED = 30 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024
RETRY_SECONDS = 15 * 60
GPS3 = re.compile(r'^\s*G\d{2,3}\s+(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})(?:\s|\.)')
GPS2 = re.compile(r'^\s*\d{1,2}\s+(\d{2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+([\d.]+)')


def sources(day: dt.date):
    doy = day.timetuple().tm_yday
    prefix = f'https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{day.year}/{doy:03d}/'
    for provider in ('IGS', 'WRD'):
        name = f'BRDC00{provider}_R_{day.year}{doy:03d}0000_01D_MN.rnx.gz'
        yield name, prefix + name
    # NOAA CORS public object; original RINEX2 format is preserved and identified.
    name = f'brdc{doy:03d}0.{day.year % 100:02d}n.gz'
    yield name, f'https://noaa-cors-pds.s3.amazonaws.com/rinex/{day.year}/{doy:03d}/{name}'


def epochs(raw: bytes):
    if not raw or len(raw) > MAX_EXPANDED:
        raise ValueError('NAV_SIZE_INVALID')
    lines = raw.decode('ascii', 'replace').splitlines()
    if not lines or 'RINEX VERSION / TYPE' not in lines[0]:
        raise ValueError('NAV_HEADER_INVALID')
    try:
        version = float(lines[0][:9])
        end_header = next(i for i, line in enumerate(lines[:300]) if 'END OF HEADER' in line)
    except (ValueError, StopIteration) as exc:
        raise ValueError('NAV_HEADER_INCOMPLETE') from exc
    if not (2 <= version < 4) or 'NAVIGATION DATA' not in lines[0].upper():
        raise ValueError('NAV_TYPE_UNSUPPORTED')
    found = []
    for line in lines[end_header + 1:]:
        match = (GPS3 if version >= 3 else GPS2).match(line)
        if not match:
            continue
        try:
            values = list(match.groups())
            if version < 3:
                year = int(values[0]); values[0] = (2000 + year if year < 80 else 1900 + year)
                values[-1] = int(float(values[-1]))
            stamp = dt.datetime(*map(int, values), tzinfo=UTC)
            found.append(stamp)
        except (ValueError, OverflowError):
            continue
    return found


def validate(raw: bytes, start: dt.datetime, end: dt.datetime):
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError('NAV_WINDOW_INVALID')
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    all_epochs = epochs(raw)
    count = sum(start - dt.timedelta(hours=2) <= t <= end + dt.timedelta(hours=2) for t in all_epochs)
    if count == 0:
        raise ValueError('WAITING_NAV_NO_NEARBY_GPS_EPOCHS')
    return count


def gunzip_bounded(compressed: bytes):
    if len(compressed) > MAX_COMPRESSED:
        raise ValueError('NAV_COMPRESSED_TOO_LARGE')
    from scripts.ppk_qa_scheduler import bounded_nav_decompress
    return bounded_nav_decompress(compressed)


def atomic_write(path: Path, data: bytes):
    fd, name = tempfile.mkstemp(prefix='.nav-v11-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def nav_for_v11(start, end, cache: Path, download: bool, *, fetch=None, now=None):
    """Select a validated NAV, refreshing cached partial content after retry delay.

    A known-incomplete cache never blocks fallback. No network in --no-download.
    The source order is deterministic; refresh probes happen after interval.
    """
    from scripts.ppk_qa_scheduler import download_nav
    fetch = fetch or download_nav
    now = time.time() if now is None else now
    cache = Path(cache)
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Serializes concurrent GNSS and PPK jobs without changing QA backlog state.
    lock_path = cache / '.nav-v11.lock'
    with lock_path.open('ab') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        errors = []
        for day in sorted({start.date(), end.date()}):
            for name, url in sources(day):
                compressed_path = cache / name
                plain_path = cache / name[:-3]
                meta_path = cache / (name + '.v11.json')
                if compressed_path.is_file():
                    try:
                        compressed = compressed_path.read_bytes()
                        plain = gunzip_bounded(compressed)
                        count = validate(plain, start, end)
                        digest = hashlib.sha256(plain).hexdigest()
                        if not plain_path.is_file() or hashlib.sha256(plain_path.read_bytes()).hexdigest() != digest:
                            atomic_write(plain_path, plain)
                        print('NAV_SOURCE:', json.dumps({'product': name, 'source_url': url,
                              'sha256': digest, 'gps_ephemeris_count': count, 'cache': 'HIT'}), flush=True)
                        return plain_path, count, digest
                    except (ValueError, OSError) as exc:
                        errors.append(type(exc).__name__)
                if not download:
                    continue
                if meta_path.exists():
                    try:
                        last = json.loads(meta_path.read_text()).get('attempted_at', 0)
                        if now - float(last) < RETRY_SECONDS:
                            continue
                    except (ValueError, TypeError, OSError):
                        pass
                # Persist the throttle timestamp before fetching, to avoid retry storms.
                atomic_write(meta_path, json.dumps({'attempted_at': now}).encode())
                try:
                    compressed = fetch(url)
                    plain = gunzip_bounded(compressed)
                    count = validate(plain, start, end)
                except Exception as exc:
                    # Explicitly retain last cached version for audit; never publish it.
                    errors.append(type(exc).__name__)
                    continue
                digest = hashlib.sha256(plain).hexdigest()
                atomic_write(compressed_path, compressed)
                atomic_write(plain_path, plain)
                print('NAV_SOURCE:', json.dumps({'product': name, 'source_url': url,
                      'sha256': digest, 'gps_ephemeris_count': count, 'cache': 'REFRESHED'}), flush=True)
                return plain_path, count, digest
        raise RuntimeError('WAITING_NAV_VALID_EPOCH_UNAVAILABLE')
