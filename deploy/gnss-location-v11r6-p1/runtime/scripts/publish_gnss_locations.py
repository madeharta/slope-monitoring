"""One-shot location state publisher, run with restricted DB writer DSN.

Input is GNSS v4 state JSON with validated device markers. Does not touch
reference_position, displacement baselines, sites or alarm configuration.
Requires psycopg3 only when --apply is used. Default is dry-run.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = {'BASE-01', 'ROVER-B1-01', 'ROVER-B1-02'}


def parse_marker(device_id, item):
    if device_id not in ALLOWED or not isinstance(item, dict):
        raise ValueError('unexpected device marker')
    lat, lon = float(item['latitude']), float(item['longitude'])
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        raise ValueError('invalid coordinate')
    stamp = datetime.fromisoformat(item['observed_to_utc'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timezone required')
    stamp = stamp.astimezone(timezone.utc)
    if stamp > datetime.now(timezone.utc):
        raise ValueError('future observation')
    if item.get('source') != 'RTKLIB_SPP':
        raise ValueError('unexpected position source; PPK needs separate acceptance adapter')
    count = int(item['accepted_solutions'])
    spread = float(item['max_spread_m'])
    from scripts.map_quality_v11r5 import POLICY
    if item.get('policy_id') != POLICY.policy_id or item.get('quality_gate_passed') is not True:
        raise ValueError('SPP_POLICY_NOT_VALIDATED')
    if item.get('quality_reasons') != [] or item.get('displacement_eligible') is not False:
        raise ValueError('SPP_POLICY_INCONSISTENT')
    if item.get('publication_purpose') != 'PROVISIONAL_OPERATIONAL_MARKER_ONLY':
        raise ValueError('SPP_WRONG_PURPOSE')
    count=int(item['accepted_solutions'])
    total=int(item['total_solutions'])
    sats=int(item['min_satellites'])
    spread=float(item['max_spread_m'])
    p95=float(item['p95_horizontal_radius_m'])
    fraction=float(item['valid_fraction'])
    span=float(item['valid_span_seconds'])
    bins=int(item['occupied_5min_bins'])
    if (count < POLICY.min_epochs or total<count or total<=0
        or sats < POLICY.min_satellites_for_solver
        or not math.isfinite(fraction) or not POLICY.min_fraction<=fraction<=1.
        or not math.isfinite(span) or span<POLICY.min_span_seconds
        or bins<1 or bins>count
        or not math.isfinite(spread) or spread<0
        or not math.isfinite(p95) or not 0<=p95<=POLICY.max_p95_radius_m
        or spread<p95):
        raise ValueError('SPP_MAP_QUALITY_GATE_FAILED')
    height = item.get('ellipsoidal_height_m')
    if height is not None:
        height = float(height)
        if not math.isfinite(height):
            raise ValueError('invalid height')
    epoch = int(item.get('operational_location_epoch', 0))
    if epoch <= 0:
        raise ValueError('OPERATIONAL_BASELINE_EPOCH_MISSING')
    return (device_id, lat, lon, height, stamp, 'RTKLIB_SPP', 5, 'ESTIMATED_OPERATIONAL', count, spread,
            {'min_satellites': sats, 'vertical_datum': item.get('vertical_datum', 'ELLIPSOIDAL_WGS84'),
             'quality_policy_id': POLICY.policy_id, 'quality_policy_calibrated': False,
             'valid_fraction': fraction, 'valid_span_seconds': span, 'p95_horizontal_radius_m':p95, 'position_accuracy_certified':False,
             'occupied_5min_bins': bins, 'total_solutions': total,
             'publication_purpose': 'PROVISIONAL_OPERATIONAL_MARKER_ONLY',
             'displacement_eligible': False, 'operational_location_epoch': epoch,
             'operational_baseline_type': 'PROVISIONAL_NOT_SURVEYED',
             'nav_sha256':item.get('nav_sha256'), 'solution_sha256':item.get('solution_sha256'),
             'quality_status':'ESTIMATED_OPERATIONAL'})


UPSERT = '''
INSERT INTO public.gnss_device_operational_locations
 (device_id, latitude, longitude, ellipsoidal_height_m, observed_at,
  position_source, quality_code, quality_status, accepted_solutions, max_spread_m, reference_epoch, provenance)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (device_id) DO UPDATE SET
 latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
 ellipsoidal_height_m = EXCLUDED.ellipsoidal_height_m,
 observed_at = EXCLUDED.observed_at, calculated_at = now(),
 position_source = EXCLUDED.position_source, quality_code = EXCLUDED.quality_code,
 quality_status = EXCLUDED.quality_status,
 accepted_solutions = EXCLUDED.accepted_solutions,
 max_spread_m = EXCLUDED.max_spread_m,
 reference_epoch = EXCLUDED.reference_epoch, provenance = EXCLUDED.provenance
WHERE public.gnss_device_operational_locations.observed_at < EXCLUDED.observed_at
  AND (public.gnss_device_operational_locations.reference_epoch IS NULL
       OR EXCLUDED.reference_epoch >= public.gnss_device_operational_locations.reference_epoch)
RETURNING device_id, reference_epoch, observed_at
''' 




def parse_ppk_pos(device_id, path, *, minimum_fix=10, minimum_float=20, max_spread_m=10.0):
    """Convert RTKLIB UTC LLH .pos into an operational marker (not displacement baseline).

    Favor FIX epochs from a session, then FLOAT when FIX is insufficient.
    Never mix FIX and FLOAT in the aggregate; never treat SINGLE as relative PPK.
    Caller must ensure this file belongs to the rover and acquisition window.
    """
    from statistics import median
    if device_id not in {'ROVER-B1-01', 'ROVER-B1-02'}:
        raise ValueError('PPK_ROVER_NOT_ALLOWED')
    accepted = []
    for line in Path(path).read_text(errors='replace').splitlines():
        if not line.strip() or line.lstrip().startswith('%'):
            continue
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            stamp = datetime.fromisoformat(parts[0].replace('/', '-') + 'T' + parts[1].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                # RTKLIB was required to run with -t -u; date and time then denote UTC.
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            lat, lon, h = map(float, parts[2:5])
            q, sats = int(parts[5]), int(parts[6])
        except ValueError:
            continue
        if not all(map(math.isfinite, (lat, lon, h))):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        if q in (1, 2) and sats >= 6:
            accepted.append((stamp, lat, lon, h, q, sats))
    fixes = [r for r in accepted if r[4] == 1]
    floats = [r for r in accepted if r[4] == 2]
    if len(fixes) >= minimum_fix:
        rows, quality_code, quality_status = fixes, 1, 'ACCEPTED_PPK_FIX'
    elif len(floats) >= minimum_float:
        rows, quality_code, quality_status = floats, 2, 'ACCEPTED_PPK_FLOAT'
    else:
        raise ValueError('PPK_INSUFFICIENT_RELATIVE_SOLUTIONS')
    lat = median(r[1] for r in rows)
    lon = median(r[2] for r in rows)
    h = median(r[3] for r in rows)
    spread = max(math.hypot((r[1]-lat)*111320, (r[2]-lon)*111320*math.cos(math.radians(lat))) for r in rows)
    if not math.isfinite(spread) or spread > max_spread_m:
        raise ValueError('PPK_SPREAD_GATE_FAILED')
    observed = max(r[0] for r in rows)
    if observed > datetime.now(timezone.utc):
        raise ValueError('PPK_FUTURE_OBSERVATION')
    return (device_id, lat, lon, h, observed, 'RTKLIB_PPK', quality_code,
            quality_status, len(rows), round(spread, 3),
            {'min_satellites': min(r[5] for r in rows), 'vertical_datum': 'ELLIPSOIDAL_WGS84',
             'fix_epochs': len(fixes), 'float_epochs': len(floats),
             'solution_sha256': __import__('hashlib').sha256(Path(path).read_bytes()).hexdigest()})


def pick_newest_per_device(rows):
    """Newest observation wins; SQL upsert still protects against older DB writes."""
    latest = {}
    for row in rows:
        previous = latest.get(row[0])
        if previous is None or row[4] > previous[4]:
            latest[row[0]] = row
    return [latest[key] for key in sorted(latest)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', type=Path, required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--ppk-pos', action='append', default=[], metavar='DEVICE=FILE',
                    help='Additional accepted RTKLIB UTC LLH .pos files for ROVERs')
    args = ap.parse_args()
    state = json.loads(args.state.read_text())
    rows = []
    for device, marker in state.get('provisional_device_locations', {}).items():
        if device not in ALLOWED:
            continue
        baseline = state.get('operational_location_baselines', {}).get(device)
        if not baseline or int(baseline.get('operational_location_epoch', 0)) != int(marker.get('operational_location_epoch', 0)):
            raise ValueError('OPERATIONAL_BASELINE_STATE_INCONSISTENT')
        rows.append(parse_marker(device, marker))
    for spec in args.ppk_pos:
        device, sep, filename = spec.partition('=')
        if not sep or not filename:
            raise SystemExit('PPK_POS_FORMAT_DEVICE_EQUALS_FILE_REQUIRED')
        rows.append(parse_ppk_pos(device, Path(filename)))
    rows = pick_newest_per_device(rows)
    if not args.apply:
        print(json.dumps({'mode':'DRY_RUN','validated_device_ids':[r[0] for r in rows]}))
        return
    dsn = os.environ.get('MAGRIS_GNSS_LOCATION_WRITER_DSN')
    if not dsn:
        raise SystemExit('MAGRIS_GNSS_LOCATION_WRITER_DSN is required')
    import psycopg
    # Provenance and epoch history come from the immutable accepted baseline
    # snapshots, not the later continuously refreshed map marker.
    history = state.get('operational_location_history', {})
    applied = []
    with psycopg.connect(dsn) as conn:
        who = conn.execute('SELECT current_database(), current_user').fetchone()
        if who != ('slope_iot', 'gnss_location_publisher'):
            raise RuntimeError('WRITER_IDENTITY_MISMATCH')
        with conn.transaction():
            for row in rows:
                epoch = row[-1].get('operational_location_epoch')
                written = conn.execute(
                    UPSERT, (*row[:-1], epoch, json.dumps(row[-1]))
                ).fetchone()
                if written is None:
                    continue  # old/out-of-order observation, never overwrite
                applied.append(row[0])
                if row[7] == 'ESTIMATED_OPERATIONAL':
                    entries = history.get(row[0])
                    if not isinstance(entries, list) or not entries:
                        raise RuntimeError('OPERATIONAL_HISTORY_MISSING')
                    previous_epoch = 0
                    for entry in entries:
                        historical_epoch = int(entry['epoch'])
                        baseline = entry['reference']
                        if historical_epoch != previous_epoch + 1 or historical_epoch > epoch:
                            raise RuntimeError('OPERATIONAL_HISTORY_INVALID')
                        if int(baseline['operational_location_epoch']) != historical_epoch:
                            raise RuntimeError('OPERATIONAL_HISTORY_EPOCH_MISMATCH')
                        historical_time = datetime.fromisoformat(
                            baseline['observed_to_utc'].replace('Z','+00:00'))
                        if historical_time.tzinfo is None or historical_time > row[4]:
                            raise RuntimeError('OPERATIONAL_HISTORY_TIME_INVALID')
                        inserted_history = conn.execute("""
                            INSERT INTO public.gnss_operational_location_epochs
                              (device_id, reference_epoch, latitude, longitude,
                               ellipsoidal_height_m, observed_at, quality_status, provenance)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                            ON CONFLICT (device_id, reference_epoch) DO NOTHING
                            RETURNING reference_epoch
                        """, (row[0], historical_epoch,
                                baseline['latitude'], baseline['longitude'],
                                baseline.get('ellipsoidal_height_m'), historical_time,
                                row[7], json.dumps({
                                  'baseline_type':'PROVISIONAL_OPERATIONAL_NOT_SURVEYED',
                                  'source':'RTKLIB_SPP',
                                  'quality_policy_id':baseline.get('policy_id'),
                                  'displacement_eligible':False,
                                  'nav_sha256':baseline.get('nav_sha256'),
                                  'solution_sha256':baseline.get('solution_sha256')}))).fetchone()
                        # A duplicate epoch may be replayed, but its immutable
                        # location, timestamp, and provenance may never change.
                        # Test in SQL, avoiding float/JSON roundtrip comparisons.
                        if inserted_history is None:
                            matches = conn.execute("""
                                SELECT 1 FROM public.gnss_operational_location_epochs
                                WHERE device_id = %s AND reference_epoch = %s
                                  AND latitude IS NOT DISTINCT FROM %s
                                  AND longitude IS NOT DISTINCT FROM %s
                                  AND ellipsoidal_height_m IS NOT DISTINCT FROM %s
                                  AND observed_at IS NOT DISTINCT FROM %s
                                  AND quality_status IS NOT DISTINCT FROM %s
                                  AND provenance IS NOT DISTINCT FROM %s::jsonb
                            """, (row[0], historical_epoch,
                                  baseline['latitude'], baseline['longitude'],
                                  baseline.get('ellipsoidal_height_m'), historical_time,
                                  row[7], json.dumps({
                                    'baseline_type':'PROVISIONAL_OPERATIONAL_NOT_SURVEYED',
                                    'source':'RTKLIB_SPP',
                                    'quality_policy_id':baseline.get('policy_id'),
                                    'displacement_eligible':False,
                                    'nav_sha256':baseline.get('nav_sha256'),
                                    'solution_sha256':baseline.get('solution_sha256')}))).fetchone()
                            if matches is None:
                                raise RuntimeError('OPERATIONAL_HISTORY_IMMUTABLE_CONFLICT')
                        previous_epoch = historical_epoch
                    if previous_epoch != epoch:
                        raise RuntimeError('OPERATIONAL_HISTORY_INCOMPLETE')
    print(json.dumps({'mode':'APPLIED', 'device_ids':applied,
                      'validated_device_ids':[r[0] for r in rows]}))

if __name__ == '__main__':
    main()
