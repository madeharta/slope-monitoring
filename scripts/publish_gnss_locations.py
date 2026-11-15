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
    if count < 10 or not math.isfinite(spread) or spread > 10 or spread < 0:
        raise ValueError('quality gate failed')
    sats = int(item['min_satellites'])
    if sats < 7:
        raise ValueError('satellite gate failed')
    height = item.get('ellipsoidal_height_m')
    if height is not None:
        height = float(height)
        if not math.isfinite(height):
            raise ValueError('invalid height')
    return (device_id, lat, lon, height, stamp, 'RTKLIB_SPP', 5, 'ACCEPTED_SPP', count, spread,
            {'min_satellites': sats, 'vertical_datum': item.get('vertical_datum', 'ELLIPSOIDAL_WGS84')})


UPSERT = '''
INSERT INTO public.gnss_device_operational_locations
 (device_id, latitude, longitude, ellipsoidal_height_m, observed_at,
  position_source, quality_code, quality_status, accepted_solutions, max_spread_m, provenance)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
ON CONFLICT (device_id) DO UPDATE SET
 latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
 ellipsoidal_height_m = EXCLUDED.ellipsoidal_height_m,
 observed_at = EXCLUDED.observed_at, calculated_at = now(),
 position_source = EXCLUDED.position_source, quality_code = EXCLUDED.quality_code,
 quality_status = EXCLUDED.quality_status,
 accepted_solutions = EXCLUDED.accepted_solutions,
 max_spread_m = EXCLUDED.max_spread_m, provenance = EXCLUDED.provenance
WHERE public.gnss_device_operational_locations.observed_at < EXCLUDED.observed_at
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
    rows = [parse_marker(device, marker) for device, marker in state.get('provisional_device_locations', {}).items()
            if device in ALLOWED]
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
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            for row in rows:
                conn.execute(UPSERT, (*row[:-1], json.dumps(row[-1])))
    print(json.dumps({'mode':'APPLIED', 'device_ids':[r[0] for r in rows]}))

if __name__ == '__main__':
    main()
