from __future__ import annotations

from ml.pipeline.preprocessing.ppk_engine import PPK_OUTPUT_SCHEMA_VERSION, PPKSolutionEpoch, PPKWindowResult


PPK_VERTICAL_DATUM = "ELLIPSOIDAL_WGS84"


class PPKSolutionConflictError(RuntimeError):
    """An existing PPK epoch differs from the attempted write."""


# The order matches INSERT's 35 bind arguments (status fields are SQL constants).
_PERSISTED_FIELDS = (
    "time", "site_id", "base_device_id", "rover_device_id", "schema_version",
    "latitude", "longitude", "ellipsoidal_height_m",
    "displacement_e_mm", "displacement_n_mm", "displacement_u_mm", "displacement_total_mm",
    "h_acc_m", "rtklib_quality", "rtklib_ns", "rtklib_age_s", "rtklib_ratio",
    "rtklib_sdn_m", "rtklib_sde_m", "rtklib_sdu_m",
    "navigation_sha256", "navigation_source_url", "navigation_provider",
    "navigation_cache_hit", "rtklib_config_sha256",
    "vertical_datum", "processing_engine", "base_rawx_sha256", "rover_rawx_sha256",
    "base_obs_sha256", "rover_obs_sha256", "normalized_navigation_sha256",
    "convbin_sha256", "rnx2rtkp_sha256", "solution_pos_sha256",
)



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
            inserted = await conn.fetchrow(
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
                ON CONFLICT (rover_device_id, time, schema_version) DO NOTHING
                RETURNING rover_device_id
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
            if inserted is not None:
                return

            # A conflicting insert has committed (or become visible after a
            # concurrent inserter). Compare every persisted field, including
            # provenance and QA status; never silently accept a different run.
            existing = await conn.fetchrow(
                "SELECT " + ", ".join(_PERSISTED_FIELDS) +
                ", quality_gate_status, validation_status "
                "FROM ppk_solution_records "
                "WHERE rover_device_id=$1 AND time=$2 AND schema_version=$3",
                rover_device_id, solution.timestamp_utc, PPK_OUTPUT_SCHEMA_VERSION,
            )
            if existing is None:
                raise PPKSolutionConflictError("PPK epoch conflict without readable existing row")

            attempted = (
                solution.timestamp_utc, site_id, base_device_id, rover_device_id,
                PPK_OUTPUT_SCHEMA_VERSION, solution.latitude, solution.longitude,
                solution.ellipsoidal_height_m, displacement.de_mm, displacement.dn_mm,
                displacement.du_mm, displacement.total_mm, solution.h_acc_m,
                solution.rtklib_quality, solution.satellites, solution.age_s,
                solution.ratio, solution.sdn_m, solution.sde_m, solution.sdu_m,
                result.navigation_sha256, result.navigation_source_url,
                result.navigation_provider, result.navigation_cache_hit,
                result.rtklib_config_sha256, PPK_VERTICAL_DATUM, result.engine_name,
                result.base_rawx_sha256, result.rover_rawx_sha256,
                result.base_obs_sha256, result.rover_obs_sha256,
                result.normalized_navigation_sha256, result.convbin_sha256,
                result.rnx2rtkp_sha256, result.solution_pos_sha256,
            )
            if any(existing[field] != value for field, value in zip(_PERSISTED_FIELDS, attempted)) or (
                existing["quality_gate_status"] != "accepted"
                or existing["validation_status"] != "unvalidated"
            ):
                raise PPKSolutionConflictError(
                    "PPK epoch already exists with different values or provenance"
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
