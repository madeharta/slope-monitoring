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

from scripts.map_quality_v11r5 import POLICY as MAP_POLICY, evaluate_map_quality
RELOCATION_METERS = 100.0  # threshold for fast (two-window) confirmation


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
    """Build a fast map-only candidate from all valid SPP Q5 solutions.

    No seven-satellite hard gate; no implied displacement accuracy.
    """
    raw = parse_rtklib_llh(path)
    metrics=evaluate_map_quality(raw, distance_m)
    result={'device_id':device_id, **metrics}
    result['status']='CANDIDATE' if metrics['quality_gate_passed'] else 'HOLD_MAP_QUALITY'
    return result


def _utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('GNSS_TIMEZONE_REQUIRED')
    return result.astimezone(timezone.utc)


def _epoch_marker(marker: dict, epoch: int) -> dict:
    return {**marker, 'operational_location_epoch': epoch}


def evaluate(state: dict, result: dict, *, base_id: str = 'BASE-01') -> tuple[dict, dict]:
    """Manage audited *operational* location epochs, never displacement baselines.

    Relocation is confirmed with two non-overlapping 5-min quality-gated
    windows for large moves, three for medium moves. Spatial coherence is
    checked. Old marker stays live until confirmation. Distances/counts are
    engineering defaults, NOT surveyed accuracy.
    """
    updated = json.loads(json.dumps(state))
    device_id = result['device_id']
    if result['status'] != 'CANDIDATE':
        return updated, result
    marker = {k: v for k, v in result.items() if k != 'status'}
    stamp = _utc(marker['observed_to_utc'])
    marker_start = _utc(marker['observed_from_utc'])
    if marker_start > stamp:
        raise ValueError('INVALID_OBSERVATION_INTERVAL')
    locations = updated.setdefault('provisional_device_locations', {})
    baselines = updated.setdefault('operational_location_baselines', {})
    histories = updated.setdefault('operational_location_history', {})
    pendings = updated.setdefault('pending_device_relocations', {})
    previous = locations.get(device_id)
    baseline = baselines.get(device_id)

    # Migration from legacy JSON state: preserve the previously accepted
    # operational marker; do not invent a surveyed displacement reference.
    if baseline is None and previous is not None:
        legacy_epoch = int(previous.get('operational_location_epoch', 1))
        if legacy_epoch < 1:
            raise ValueError('INVALID_LOCATION_EPOCH')
        baselines[device_id] = _epoch_marker(previous, legacy_epoch)
        histories.setdefault(device_id, [{'epoch': legacy_epoch,
                                          'reference': baselines[device_id]}])
        baseline = baselines[device_id]
    if previous is not None and stamp <= _utc(previous['observed_to_utc']):
        return updated, {**result, 'status': 'STALE_OBSERVATION_IGNORED'}
    if baseline is None:
        first = _epoch_marker(marker, 1)
        locations[device_id] = first
        baselines[device_id] = first
        histories[device_id] = [{'epoch': 1, 'reference': first}]
        pendings.pop(device_id, None)
        if device_id == base_id:
            updated['provisional_base_reference'] = first
            updated['reference_epoch'] = 1
            updated['reference_history'] = [{'epoch': 1, 'reference': first}]
            status = 'REFERENCE_INITIALIZED_PROVISIONAL'
        else:
            status = 'MARKER_READY'
        return updated, {**result, 'status': status, 'operational_location_epoch': 1,
                         'baseline_type': 'PROVISIONAL_OPERATIONAL_NOT_SURVEYED'}

    epoch = int(baseline.get('operational_location_epoch', 1))
    if epoch < 1:
        raise ValueError('INVALID_LOCATION_EPOCH')
    shift = distance_m(baseline, marker)
    noise_floor=max(20., 3 * max(float(marker.get('p95_horizontal_radius_m') or 0),
                                 float(baseline.get('p95_horizontal_radius_m') or 0)))
    if shift <= noise_floor:
        # Keep location baseline stable for the epoch, but refresh current map
        # position on every newer accepted SPP window.
        locations[device_id] = _epoch_marker(marker, epoch)
        pendings.pop(device_id, None)
        if device_id == base_id:
            updated['provisional_base_reference'] = baselines[device_id]
            updated['reference_epoch'] = epoch
            status = 'REFERENCE_UNCHANGED'
        else:
            status = 'MARKER_READY'
        return updated, {**result, 'status': status,
                         'operational_location_epoch': epoch,
                         'distance_from_operational_baseline_m': round(shift, 2)}

    # Fast relocation requires independent, non-overlapping consecutive windows.
    # Larger jumps require two stable windows; medium moves require three.
    # The candidate alone NEVER advances the published marker.
    required = 2 if shift > 100.0 else 3
    pending = pendings.get(device_id, {})
    samples = list(pending.get('observations', []))
    if samples:
        last=samples[-1]
        last_end=_utc(last['observed_to_utc'])
        if stamp <= last_end:
            return updated, {**result, 'status':'RELOCATION_CONFIRMING',
                             'confirmation_windows':len(samples),
                             'distance_from_operational_baseline_m':round(shift,2)}
        # Nonoverlapping; no fabricated confirmation from one longer recording.
        if marker_start < last_end:
            return updated, {**result, 'status':'RELOCATION_CONFIRMING',
                             'confirmation_windows':len(samples),
                             'distance_from_operational_baseline_m':round(shift,2)}
        # Every candidate must be in the same new-location cluster.
        if distance_m(last,marker)>max(25., 2 * max(
                float(marker.get('p95_horizontal_radius_m') or 0),
                float(last.get('p95_horizontal_radius_m') or 0))):
            samples=[]
    samples=(samples+[marker])[-required:]
    if len(samples)<required:
        pendings[device_id]={'observations':samples,
                             'distance_from_operational_baseline_m':round(shift,2)}
        return updated, {**result, 'status':'RELOCATION_CONFIRMING',
                         'confirmation_windows':len(samples),
                         'confirmation_required':required,
                         'distance_from_operational_baseline_m':round(shift,2)}
    next_epoch = epoch + 1
    accepted = _epoch_marker(marker, next_epoch)
    locations[device_id] = accepted
    baselines[device_id] = accepted
    histories.setdefault(device_id, []).append({'epoch': next_epoch, 'reference': accepted})
    pendings.pop(device_id, None)
    if device_id == base_id:
        updated['provisional_base_reference'] = accepted
        updated['reference_epoch'] = next_epoch
        updated['reference_history'] = updated.get('reference_history', []) + [
            {'epoch': next_epoch, 'reference': accepted}]
    # No automatic rebaseline for deformation: mark for separate survey QA.
    updated['displacement_baseline_status'] = 'REQUIRES_NEW_EPOCH_BASELINE_QA'
    return updated, {**result, 'status': 'REFERENCE_RELOCATED_AUTOMATICALLY',
                     'operational_location_epoch': next_epoch,
                     'distance_from_operational_baseline_m': round(shift, 2),
                     'displacement_baseline_status': updated['displacement_baseline_status']}

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
    return 0 if not output['status'].startswith('HOLD') else 2


if __name__ == '__main__':
    raise SystemExit(main())
