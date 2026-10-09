from __future__ import annotations
from datetime import datetime
import json

BLAST_EVENT_SCHEMA_VERSION = "blast.event.v1"

class BlastEventRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def write_event(
        self, *, site_id: str, device_id: str, source_file: str,
        communication_mode: str, event_start: datetime, event_end: datetime,
        sample_count: int, duration_ms: float,
        observed_sample_rate_hz: float | None, median_gap_ms: float | None,
        max_gap_ms: float | None, quality_gate_status: str, quality_reasons: tuple[str, ...],
        adxl355_ppa_g: float | None, adxl355_ppv_mm_s: float | None,
        mpu9250_ppa_g: float | None, mpu9250_ppv_mm_s: float | None,
        blast_command_id: int | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO blast_event_records (
                    site_id, device_id, blast_command_id, source_file, communication_mode,
                    schema_version, event_start, event_end, sample_count, duration_ms,
                    observed_sample_rate_hz, median_gap_ms, max_gap_ms,
                    quality_gate_status, quality_reasons,
                    adxl355_ppa_g, adxl355_ppv_mm_s, mpu9250_ppa_g, mpu9250_ppv_mm_s,
                    validation_status
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,
                    $16,$17,$18,$19,'unvalidated'
                )
                ON CONFLICT (source_file) DO UPDATE SET
                    sample_count = EXCLUDED.sample_count,
                    duration_ms = EXCLUDED.duration_ms,
                    observed_sample_rate_hz = EXCLUDED.observed_sample_rate_hz,
                    median_gap_ms = EXCLUDED.median_gap_ms,
                    max_gap_ms = EXCLUDED.max_gap_ms,
                    quality_gate_status = EXCLUDED.quality_gate_status,
                    quality_reasons = EXCLUDED.quality_reasons,
                    adxl355_ppa_g = EXCLUDED.adxl355_ppa_g,
                    adxl355_ppv_mm_s = EXCLUDED.adxl355_ppv_mm_s,
                    mpu9250_ppa_g = EXCLUDED.mpu9250_ppa_g,
                    mpu9250_ppv_mm_s = EXCLUDED.mpu9250_ppv_mm_s,
                    processed_at = now()
                RETURNING event_id
                """,
                site_id, device_id, blast_command_id, source_file, communication_mode,
                BLAST_EVENT_SCHEMA_VERSION, event_start, event_end, sample_count, duration_ms,
                observed_sample_rate_hz, median_gap_ms, max_gap_ms,
                quality_gate_status, json.dumps(list(quality_reasons)),
                adxl355_ppa_g, adxl355_ppv_mm_s, mpu9250_ppa_g, mpu9250_ppv_mm_s,
            )
        return int(row["event_id"])

    async def list_events(self, *, site_id: str | None = None, device_id: str | None = None, limit: int = 100):
        clauses, args = [], []
        if site_id:
            args.append(site_id); clauses.append(f"site_id = ${len(args)}")
        if device_id:
            args.append(device_id); clauses.append(f"device_id = ${len(args)}")
        args.append(limit)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT event_id, site_id, device_id, blast_command_id, source_file, communication_mode,
                   schema_version, event_start, event_end, sample_count, duration_ms,
                   observed_sample_rate_hz, median_gap_ms, max_gap_ms,
                   quality_gate_status, quality_reasons,
                   adxl355_ppa_g, adxl355_ppv_mm_s, mpu9250_ppa_g, mpu9250_ppv_mm_s,
                   validation_status, processed_at
            FROM blast_event_records
            {where}
            ORDER BY event_start DESC
            LIMIT ${len(args)}
        """
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)
