from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request


def _qa_schema_missing(exc: Exception) -> bool:
    """Recognize missing QA tables/columns; never mask other DB failures."""
    return getattr(exc, "sqlstate", None) in ("42P01", "42703")


from apps.api.dependencies import get_db_pool, require_role
from common.security import TokenPayload
from ml.pipeline.preprocessing.ppk_engine import PPK_ENGINE_NAME, PPK_OUTPUT_SCHEMA_VERSION
from services.monitoring_service.ppk_solution_repository import PPKSolutionRepository, is_complete_provenance

router = APIRouter(prefix="/api/v1/ppk", tags=["ppk"])


def _iso(value):
    return value.isoformat() if value else None



@router.get("/solutions")
async def list_ppk_solutions(
    request: Request,
    user: TokenPayload = Depends(require_role("viewer")),
    site_id: str = Query(...),
    rover_device_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    rows = await PPKSolutionRepository(get_db_pool(request)).list_records(
        site_id=site_id,
        rover_device_id=rover_device_id,
        limit=limit,
    )
    return {
        "ok": True,
        "schema_version": PPK_OUTPUT_SCHEMA_VERSION,
        "solution_contract": {
            "schema_version": PPK_OUTPUT_SCHEMA_VERSION,
            "locked": True,
            "vertical_datum": "ELLIPSOIDAL_WGS84",
            "processing_engine": PPK_ENGINE_NAME,
            "production_geodetic_validation": False,
        },
        "validation_status": "unvalidated",
        "operational_ready": False,
        "rows": [
            {
                "time": _iso(r["time"]),
                "site_id": r["site_id"],
                "base_device_id": r["base_device_id"],
                "rover_device_id": r["rover_device_id"],
                "schema_version": r["schema_version"],
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "ellipsoidal_height_m": r["ellipsoidal_height_m"],
                "vertical_datum": r["vertical_datum"],
                "displacement_e_mm": r["displacement_e_mm"],
                "displacement_n_mm": r["displacement_n_mm"],
                "displacement_u_mm": r["displacement_u_mm"],
                "displacement_total_mm": r["displacement_total_mm"],
                "h_acc_m": r["h_acc_m"],
                "rtklib_quality": r["rtklib_quality"],
                "rtklib_ns": r["rtklib_ns"],
                "rtklib_age_s": r["rtklib_age_s"],
                "rtklib_ratio": r["rtklib_ratio"],
                "rtklib_sdn_m": r["rtklib_sdn_m"],
                "rtklib_sde_m": r["rtklib_sde_m"],
                "rtklib_sdu_m": r["rtklib_sdu_m"],
                "navigation_sha256": r["navigation_sha256"],
                "navigation_source_url": r["navigation_source_url"],
                "navigation_provider": r["navigation_provider"],
                "navigation_cache_hit": r["navigation_cache_hit"],
                "rtklib_config_sha256": r["rtklib_config_sha256"],
                "processing_engine": r["processing_engine"],
                "provenance_complete": is_complete_provenance(r),
                "provenance": {
                    "base_rawx_sha256": r["base_rawx_sha256"],
                    "rover_rawx_sha256": r["rover_rawx_sha256"],
                    "base_obs_sha256": r["base_obs_sha256"],
                    "rover_obs_sha256": r["rover_obs_sha256"],
                    "navigation_source_sha256": r["navigation_sha256"],
                    "navigation_normalized_sha256": r["normalized_navigation_sha256"],
                    "rtklib_config_sha256": r["rtklib_config_sha256"],
                    "convbin_sha256": r["convbin_sha256"],
                    "rnx2rtkp_sha256": r["rnx2rtkp_sha256"],
                    "solution_pos_sha256": r["solution_pos_sha256"],
                },
                "quality_gate_status": r["quality_gate_status"],
                "validation_status": r["validation_status"],
                "processed_at": _iso(r["processed_at"]),
            }
            for r in rows
        ],
    }


# b12-unified-filter-v1 — experimental QA only, never displacement.



def get_ppk_qa_pool(request: Request):
    """Return isolated QA read-only pool; never fall back to main DB."""
    from fastapi import HTTPException

    pool = getattr(request.app.state, "ppk_qa_db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="PPK QA database is not configured",
        )
    return pool


@router.get('/qa/rovers')
async def list_experimental_ppk_qa_rovers(
    request: Request,
    user: TokenPayload = Depends(require_role("viewer")),
    site_id: str = Query(default='ITB-STAGING-01'),
) -> dict:
    pool = get_ppk_qa_pool(request)
    try:
        async with pool.acquire() as conn:
            values = await conn.fetch('''SELECT DISTINCT rover_device_id FROM public.ppk_qa_experimental_solutions
                                          WHERE site_id=$1 ORDER BY rover_device_id''', site_id)
    except Exception as exc:
        if not _qa_schema_missing(exc):
            raise
        return {'availability_status': 'schema_unavailable', 'rovers': []}
    return {'availability_status': 'available', 'rovers': [r['rover_device_id'] for r in values]}

# B13_5_PAGINATION_V1 — experimental QA, independent from operational PPK.
@router.get('/qa/solutions')
async def list_experimental_ppk_qa_solutions(
    request: Request,
    user: TokenPayload = Depends(require_role("viewer")),
    site_id: str = Query(default='ITB-STAGING-01'),
    rover_device_id: str | None = Query(default='ROVER-B1-02'),
    limit: int = Query(default=500, ge=1, le=2000),
    time_range: str = Query(default='all', pattern='^(all|24h|7d|30d)$'),
    cursor: str | None = None,
) -> dict:
    """Read-only experimental QA. Cursor is a deterministic epoch+id position.

    Existing fields are preserved for current dashboard clients. Observation
    UTC is emitted only within a documented GPS/UTC offset interval.
    """
    import base64
    import binascii
    import json
    import math
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException

    def parse_cursor(token):
        if token is None:
            return None
        if not isinstance(token, str) or len(token) > 256:
            raise HTTPException(status_code=422, detail="Invalid QA pagination cursor")
        try:
            raw = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
            value = json.loads(raw)
            if (not isinstance(value, list) or len(value) != 3
                    or type(value[0]) is not int or value[0] < 0
                    or type(value[1]) not in (int, float)
                    or not math.isfinite(value[1]) or not 0 <= value[1] < 604800
                    or type(value[2]) is not int or value[2] < 0):
                raise ValueError('invalid cursor values')
            return value
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
            raise HTTPException(status_code=422, detail='Invalid QA pagination cursor') from exc

    def encode_cursor(row):
        encoded = json.dumps([row['gps_week'], row['gps_tow_s'], row['id']], separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(encoded).decode().rstrip('=')

    gps_epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    # At the experimental 2026 epoch GPS-UTC is 18 seconds. Avoid pretending
    # that this constant works before 2017 or indefinitely in the future.
    valid_start = datetime(2017, 1, 1, tzinfo=timezone.utc)
    valid_until = datetime(2027, 1, 1, tzinfo=timezone.utc)
    cutoff = None
    if time_range != 'all':
        delta = {'24h': 86400, '7d': 604800, '30d': 2592000}[time_range]
        cutoff = (now - gps_epoch).total_seconds() + 18 - delta

    offset = parse_cursor(cursor)
    pool = get_ppk_qa_pool(request)
    availability_status = 'available'
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id,site_id,base_device_id,rover_device_id,source_pos_sha256,
                       gps_week,gps_tow_s,latitude_deg,longitude_deg,
                       ellipsoidal_height_m,rtklib_quality,satellite_count,
                       sdn_m,sde_m,sdu_m,sdne_m,sdeu_m,sdun_m,age_s,ratio,
                       reference_type,validation_status,schema_version,created_at
                FROM public.ppk_qa_experimental_solutions
                WHERE site_id=$1
                  AND ($2::text IS NULL OR rover_device_id=$2)
                  AND ($3::double precision IS NULL OR
                       (gps_week::double precision*604800.0+gps_tow_s)>=$3)
                  AND ($4::int IS NULL OR
                       (gps_week,gps_tow_s,id) > ($4::int,$5::double precision,$6::bigint))
                ORDER BY gps_week ASC,gps_tow_s ASC,id ASC
                LIMIT $7
            """, site_id, rover_device_id, cutoff,
                offset[0] if offset else None,
                offset[1] if offset else None,
                offset[2] if offset else None,
                limit + 1)
    except Exception as exc:
        if not _qa_schema_missing(exc):
            raise
        availability_status = 'schema_unavailable'
        rows = []

    has_more = len(rows) > limit
    selected = rows[:limit]
    results = []
    for r in selected:
        item = dict(r)
        item.pop('id', None)  # internal pagination tie-breaker
        # QA v1 stores ellipsoidal height exclusively.
        # Explicit datum prevents interpreting it as MSL elevation.
        item['vertical_datum'] = 'ELLIPSOIDAL_WGS84'
        gps_time = gps_epoch + timedelta(weeks=r['gps_week'], seconds=r['gps_tow_s'])
        derived_utc = gps_time - timedelta(seconds=18)
        if valid_start <= derived_utc < valid_until:
            item['observation_time_utc'] = derived_utc.isoformat()
            item['gps_utc_offset_s'] = 18
            item['time_conversion_status'] = 'GPS_UTC_OFFSET_18S_EPOCH_LIMITED'
        else:
            item['observation_time_utc'] = None
            item['gps_utc_offset_s'] = None
            item['time_conversion_status'] = 'OFFSET_UNVERIFIED'
        item['created_at'] = r['created_at'].isoformat() if r['created_at'] else None
        # Storage v1 has no reference version or deterministic job FK.
        item['base_reference_version'] = None
        item['processing_job_id'] = None
        results.append(item)
    return {
        'availability_status': availability_status,
        'schema_version': 'ppk.qa.solution.v1',
        'api_contract_version': 'ppk.qa.api.v1',
        'scope': 'EXPERIMENTAL_ENGINE_QA_ONLY',
        'applied_filters': {
            'site_id': site_id, 'rover_device_id': rover_device_id,
            'time_range': time_range, 'limit': limit,
        },
        'reference_type': 'PROVISIONAL_SPP',
        'validation_status': 'unvalidated',
        'operational_displacement_approved': False,
        'rows': results,
        'pagination': {
            'has_more': has_more,
            'next_cursor': encode_cursor(selected[-1]) if has_more and selected else None,
            'returned': len(results),
        },
    }
