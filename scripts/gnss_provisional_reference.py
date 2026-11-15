"""Fail-closed provisional GNSS reference manager.

Consumes RTKLIB LLH .pos outputs, never GNSS raw payloads directly. Does not
alter surveyed references, displacement baselines, or production tables.
Requires an upstream NAV/convbin/rnx2rtkp job. Stdlib only, Python >=3.11.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

MIN_SOLUTIONS = 10
MIN_SATELLITES = 7
MAX_SPREAD_METERS = 10.0
RELOCATION_METERS = 100.0


def distance_m(a: dict, b: dict) -> float:
    lat = (a['latitude'] + b['latitude']) / 2
    return math.hypot(
        (a['latitude'] - b['latitude']) * 111_320,
        (a['longitude'] - b['longitude']) * 111_320 * math.cos(math.radians(lat)),
    )


def parse_rtklib_llh(path: Path) -> list[dict]:
    """RTKLIB LLH: date time lat lon ellipsoidal_height Q ns ..."""
    fixes = []
    for line in path.read_text(errors='replace').splitlines():
        if not line.strip() or line.lstrip().startswith('%'):
            continue
        fields = line.split()
        if len(fields) < 7:
            continue
        try:
            timestamp = datetime.fromisoformat(fields[0].replace('/', '-') + 'T' + fields[1])
            lat, lon, height = map(float, fields[2:5])
            quality, satellites = int(fields[5]), int(fields[6])
        except ValueError:
            continue
        if not all(math.isfinite(n) for n in (lat, lon, height)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        fixes.append({'time': timestamp.replace(tzinfo=timezone.utc).isoformat(),
                      'latitude': lat, 'longitude': lon, 'ellipsoidal_height_m': height,
                      'quality': quality, 'satellites': satellites})
    return fixes


def candidate(path: Path, device_id: str) -> dict:
    raw = parse_rtklib_llh(path)
    # RTKLIB Q=5 means single point solution; reject non-SPP for this path.
    fixes = [r for r in raw if r['quality'] == 5 and r['satellites'] >= MIN_SATELLITES]
    if len(fixes) < MIN_SOLUTIONS:
        return {'device_id': device_id, 'status': 'HOLD_INSUFFICIENT_SPP',
                'accepted_solutions': len(fixes), 'total_solutions': len(raw)}
    lat = median(r['latitude'] for r in fixes)
    lon = median(r['longitude'] for r in fixes)
    height = median(r['ellipsoidal_height_m'] for r in fixes)
    result = {'device_id': device_id, 'latitude': round(lat, 8),
              'longitude': round(lon, 8), 'ellipsoidal_height_m': round(height, 3),
              'vertical_datum': 'ELLIPSOIDAL_WGS84', 'source': 'RTKLIB_SPP',
              'validation_status': 'provisional', 'accepted_solutions': len(fixes),
              'total_solutions': len(raw), 'min_satellites': min(x['satellites'] for x in fixes),
              'observed_from_utc': min(x['time'] for x in fixes),
              'observed_to_utc': max(x['time'] for x in fixes)}
    result['max_spread_m'] = round(max(distance_m(result, fix) for fix in fixes), 3)
    result['status'] = ('CANDIDATE' if result['max_spread_m'] <= MAX_SPREAD_METERS
                        else 'HOLD_UNSTABLE_SPP')
    return result


def _utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('GNSS_TIMEZONE_REQUIRED')
    return result.astimezone(timezone.utc)


def evaluate(state: dict, result: dict, *, base_id: str = 'BASE-01') -> tuple[dict, dict]:
    """Update current marker on each newer stable window, preserve fixed epochs.

    BASE relocation requires three distinct, time-separated quality-gated SPP
    windows with mutually consistent positions. It never resets rover baselines.
    """
    updated = json.loads(json.dumps(state))
    device_id = result['device_id']
    if result['status'] != 'CANDIDATE':
        return updated, result
    marker = {k: v for k, v in result.items() if k != 'status'}
    stamp = _utc(marker['observed_to_utc'])
    locations = updated.setdefault('provisional_device_locations', {})
    previous = locations.get(device_id)
    if previous is not None and stamp <= _utc(previous['observed_to_utc']):
        return updated, {**result, 'status': 'STALE_OBSERVATION_IGNORED'}
    locations[device_id] = marker
    if device_id != base_id:
        return updated, {**result, 'status': 'MARKER_READY'}
    active = updated.get('provisional_base_reference')
    if active is None:
        updated['provisional_base_reference'] = marker
        updated['reference_epoch'] = 1
        updated['reference_history'] = [{'epoch': 1, 'reference': marker}]
        return updated, {**result, 'status': 'REFERENCE_INITIALIZED_PROVISIONAL', 'epoch': 1}
    # A newer marker is ALWAYS retained even when it differs from fixed reference.
    shift = distance_m(active, result)
    if shift <= RELOCATION_METERS:
        updated.pop('pending_base_relocation', None)
        return updated, {**result, 'status': 'REFERENCE_UNCHANGED',
                         'distance_from_active_m': round(shift, 2)}
    pending = updated.get('pending_base_relocation', {})
    samples = pending.get('observations', [])
    if not samples or distance_m(samples[-1], marker) > 25:
        samples = []
    # Require at least 30 min between distinct confirmation windows.
    if not samples or (stamp - _utc(samples[-1]['observed_to_utc'])).total_seconds() >= 1800:
        samples.append(marker)
    samples = samples[-3:]
    if len(samples) == 3:
        new_epoch = int(updated.get('reference_epoch', 1)) + 1
        updated['reference_epoch'] = new_epoch
        updated['reference_history'] = updated.get('reference_history', [{'epoch': 1, 'reference': active}]) + [
            {'epoch': new_epoch, 'reference': marker}]
        updated['provisional_base_reference'] = marker
        updated.pop('pending_base_relocation', None)
        # A new reference does NOT imply a new displacement baseline.
        updated['displacement_baseline_status'] = 'REQUIRES_NEW_EPOCH_BASELINE_QA'
        return updated, {**result, 'status': 'REFERENCE_RELOCATED_AUTOMATICALLY',
                         'epoch': new_epoch, 'displacement_baseline_status': updated['displacement_baseline_status']}
    updated['pending_base_relocation'] = {'observations': samples,
                                         'distance_from_active_m': round(shift, 2)}
    return updated, {**result, 'status': 'RELOCATION_CONFIRMING',
                     'confirmation_windows': len(samples),
                     'distance_from_active_m': round(shift, 2)}


def save_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.gnss-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solutions', type=Path, required=True)
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--apply-local', action='store_true',
                        help='Write local provisional JSON, never application DB')
    args = parser.parse_args()
    result = candidate(args.solutions, args.device_id)
    existing = json.loads(args.state.read_text()) if args.state.exists() else {}
    state, output = evaluate(existing, result)
    if args.apply_local and result['status'] == 'CANDIDATE':
        save_json_atomic(args.state, state)
    print(json.dumps(output, sort_keys=True))
    return 0 if output['status'] not in ('HOLD_INSUFFICIENT_SPP', 'HOLD_UNSTABLE_SPP',
                                        'HOLD_RELOCATION_REVIEW') else 2


if __name__ == '__main__':
    raise SystemExit(main())
