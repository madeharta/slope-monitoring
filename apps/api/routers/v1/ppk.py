from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

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
