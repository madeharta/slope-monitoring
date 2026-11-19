"""Fast operational map location policy; NOT displacement-grade GNSS.

Uncalibrated engineering thresholds. Treat satellite count as observability
metadata, not a hard >=7 requirement. Robust spatial and temporal checks are
required before an operational marker may be published.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil, isfinite
from statistics import median

@dataclass(frozen=True)
class MapPolicy:
    policy_id: str = 'MAGRIS_OPERATIONAL_MAP_V11R5_UNCALIBRATED'
    min_epochs: int = 8
    min_fraction: float = .40
    min_span_seconds: int = 120
    min_satellites_for_solver: int = 4
    max_p95_radius_m: float = 25.0
    min_fresh_age_seconds: int = 0

POLICY = MapPolicy()

def parse_utc(text):
    value=datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None:
        raise ValueError('GNSS_TIMEZONE_REQUIRED')
    return value.astimezone(timezone.utc)

def evaluate_map_quality(raw, distance_m, *, policy=POLICY):
    """Return aggregated candidate and evidence; no database writes.

    Worst-case radial spread is recorded separately from the 95th-percentile
    radius. Outliers cannot establish a distant relocation cluster because a
    majority must be spatially close to the median.
    """
    accepted=[r for r in raw if r['quality']==5 and r['satellites']>=policy.min_satellites_for_solver]
    accepted.sort(key=lambda r: parse_utc(r['time']))
    center=None
    radius=None
    p95=None
    filtered=[]
    if accepted:
        center={'latitude':median(r['latitude'] for r in accepted),
                'longitude':median(r['longitude'] for r in accepted)}
        radii=[distance_m(center, r) for r in accepted]
        p95=sorted(radii)[ceil(.95*len(radii))-1]
        radius=max(radii)
        filtered=[r for r,d in zip(accepted,radii) if d<=max(policy.max_p95_radius_m,3*p95)]
    span=(parse_utc(accepted[-1]['time'])-parse_utc(accepted[0]['time'])).total_seconds() if len(accepted)>1 else 0.
    frac=len(accepted)/len(raw) if raw else 0.
    reasons=[]
    if len(accepted)<policy.min_epochs: reasons.append('MAP_INSUFFICIENT_EPOCHS')
    if frac<policy.min_fraction: reasons.append('MAP_INSUFFICIENT_COVERAGE')
    if span<policy.min_span_seconds: reasons.append('MAP_INSUFFICIENT_SPAN')
    if p95 is None or not isfinite(p95) or p95>policy.max_p95_radius_m:
        reasons.append('MAP_UNSTABLE_POSITION')
    if len(filtered)<policy.min_epochs: reasons.append('MAP_INSUFFICIENT_INLIERS')
    result={'policy_id':policy.policy_id,'policy_calibrated':False,
            'quality_gate_passed':not reasons,'quality_reasons':reasons,
            'total_solutions':len(raw),'accepted_solutions':len(accepted),
            'valid_fraction':round(frac,4),'valid_span_seconds':round(span,1),
            'occupied_5min_bins':len({int(parse_utc(r['time']).timestamp())//300 for r in accepted}),
            'min_satellites':min((r['satellites'] for r in accepted),default=None),
            'p95_horizontal_radius_m':round(p95,3) if p95 is not None else None,
            'max_spread_m':round(radius,3) if radius is not None else None,
            'inlier_solutions':len(filtered),'publication_purpose':'PROVISIONAL_OPERATIONAL_MARKER_ONLY',
            'displacement_eligible':False,'position_accuracy_certified':False,
            'quality_status':'ESTIMATED_OPERATIONAL'}
    if not reasons:
        result.update({'latitude':round(center['latitude'],8),'longitude':round(center['longitude'],8),
            'ellipsoidal_height_m':round(median(r['ellipsoidal_height_m'] for r in filtered),3),
            'vertical_datum':'ELLIPSOIDAL_WGS84','source':'RTKLIB_SPP',
            'validation_status':'estimated_operational',
            'observed_from_utc':accepted[0]['time'], 'observed_to_utc':accepted[-1]['time']})
    return result
