from __future__ import annotations

from ml.pipeline.preprocessing.ppk_engine import PPK_OUTPUT_SCHEMA_VERSION, PPKSolutionEpoch, PPKWindowResult


PPK_VERTICAL_DATUM = "ELLIPSOIDAL_WGS84"


def is_complete_provenance(row) -> bool:
    required = (
        "base_rawx_sha256",
        "rover_rawx_sha256",
        "base_obs_sha256",
        "rover_obs_sha256",
        "navigation_sha256",
        "normalized_navigation_sha256",
        "convbin_sha256",
        "rnx2rtkp_sha256",
        "solution_pos_sha256",
    )
    return all(row[name] for name in required)


class PPKSolutionRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def write_accepted(
        self,
        *,
        site_id: str,
        base_device_id: str,
        rover_device_id: str,
        solution: PPKSolutionEpoch,
        result: PPKWindowResult,
        displacement,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ppk_solution_records (
                    time, site_id, base_device_id, rover_device_id, schema_version,
                    latitude, longitude, ellipsoidal_height_m,
                    displacement_e_mm, displacement_n_mm, displacement_u_mm, displacement_total_mm,
                    h_acc_m, rtklib_quality, rtklib_ns, rtklib_age_s, rtklib_ratio,
                    rtklib_sdn_m, rtklib_sde_m, rtklib_sdu_m,
                    navigation_sha256, navigation_source_url, navigation_provider,
                    navigation_cache_hit, rtklib_config_sha256,
                    vertical_datum, processing_engine,
                    base_rawx_sha256, rover_rawx_sha256,
                    base_obs_sha256, rover_obs_sha256,
                    normalized_navigation_sha256, convbin_sha256, rnx2rtkp_sha256,
                    solution_pos_sha256,
                    quality_gate_status, validation_status
                )
                VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8,
                    $9, $10, $11, $12,
                    $13, $14, $15, $16, $17,
                    $18, $19, $20,
                    $21, $22, $23, $24, $25,
                    $26, $27,
                    $28, $29, $30, $31,
                    $32, $33, $34, $35,
                    'accepted', 'unvalidated'
                )
                ON CONFLICT (rover_device_id, time, schema_version) DO UPDATE SET
                    site_id = EXCLUDED.site_id,
                    base_device_id = EXCLUDED.base_device_id,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    ellipsoidal_height_m = EXCLUDED.ellipsoidal_height_m,
                    displacement_e_mm = EXCLUDED.displacement_e_mm,
                    displacement_n_mm = EXCLUDED.displacement_n_mm,
                    displacement_u_mm = EXCLUDED.displacement_u_mm,
                    displacement_total_mm = EXCLUDED.displacement_total_mm,
                    h_acc_m = EXCLUDED.h_acc_m,
                    rtklib_quality = EXCLUDED.rtklib_quality,
                    rtklib_ns = EXCLUDED.rtklib_ns,
                    rtklib_age_s = EXCLUDED.rtklib_age_s,
                    rtklib_ratio = EXCLUDED.rtklib_ratio,
                    rtklib_sdn_m = EXCLUDED.rtklib_sdn_m,
                    rtklib_sde_m = EXCLUDED.rtklib_sde_m,
                    rtklib_sdu_m = EXCLUDED.rtklib_sdu_m,
                    navigation_sha256 = EXCLUDED.navigation_sha256,
                    navigation_source_url = EXCLUDED.navigation_source_url,
                    navigation_provider = EXCLUDED.navigation_provider,
                    navigation_cache_hit = EXCLUDED.navigation_cache_hit,
                    rtklib_config_sha256 = EXCLUDED.rtklib_config_sha256,
                    vertical_datum = EXCLUDED.vertical_datum,
                    processing_engine = EXCLUDED.processing_engine,
                    base_rawx_sha256 = EXCLUDED.base_rawx_sha256,
                    rover_rawx_sha256 = EXCLUDED.rover_rawx_sha256,
                    base_obs_sha256 = EXCLUDED.base_obs_sha256,
                    rover_obs_sha256 = EXCLUDED.rover_obs_sha256,
                    normalized_navigation_sha256 = EXCLUDED.normalized_navigation_sha256,
                    convbin_sha256 = EXCLUDED.convbin_sha256,
                    rnx2rtkp_sha256 = EXCLUDED.rnx2rtkp_sha256,
                    solution_pos_sha256 = EXCLUDED.solution_pos_sha256,
                    quality_gate_status = 'accepted',
                    validation_status = 'unvalidated',
                    processed_at = now()
                """,
                solution.timestamp_utc,
                site_id,
                base_device_id,
                rover_device_id,
                PPK_OUTPUT_SCHEMA_VERSION,
                solution.latitude,
                solution.longitude,
                solution.ellipsoidal_height_m,
                displacement.de_mm,
                displacement.dn_mm,
                displacement.du_mm,
                displacement.total_mm,
                solution.h_acc_m,
                solution.rtklib_quality,
                solution.satellites,
                solution.age_s,
                solution.ratio,
                solution.sdn_m,
                solution.sde_m,
                solution.sdu_m,
                result.navigation_sha256,
                result.navigation_source_url,
                result.navigation_provider,
                result.navigation_cache_hit,
                result.rtklib_config_sha256,
                PPK_VERTICAL_DATUM,
                result.engine_name,
                result.base_rawx_sha256,
                result.rover_rawx_sha256,
                result.base_obs_sha256,
                result.rover_obs_sha256,
                result.normalized_navigation_sha256,
                result.convbin_sha256,
                result.rnx2rtkp_sha256,
                result.solution_pos_sha256,
            )

    async def list_records(
        self,
        *,
        site_id: str,
        rover_device_id: str | None = None,
        limit: int = 500,
    ) -> list:
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT time, site_id, base_device_id, rover_device_id, schema_version,
                       latitude, longitude, ellipsoidal_height_m, vertical_datum,
                       displacement_e_mm, displacement_n_mm, displacement_u_mm, displacement_total_mm,
                       h_acc_m, rtklib_quality, rtklib_ns, rtklib_age_s, rtklib_ratio,
                       rtklib_sdn_m, rtklib_sde_m, rtklib_sdu_m,
                       navigation_sha256, navigation_source_url, navigation_provider,
                       navigation_cache_hit, rtklib_config_sha256,
                       processing_engine, base_rawx_sha256, rover_rawx_sha256,
                       base_obs_sha256, rover_obs_sha256, normalized_navigation_sha256,
                       convbin_sha256, rnx2rtkp_sha256, solution_pos_sha256,
                       quality_gate_status, validation_status, processed_at
                FROM ppk_solution_records
                WHERE site_id = $1
                  AND ($2::text IS NULL OR rover_device_id = $2)
                ORDER BY time DESC
                LIMIT $3
                """,
                site_id,
                rover_device_id,
                limit,
            )
