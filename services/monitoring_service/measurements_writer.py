from __future__ import annotations
from datetime import datetime


class MeasurementsWriter:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def write_displacement(
        self,
        device_id: str,
        site_id: str,
        timestamp_utc: datetime,
        de_mm: float,
        dn_mm: float,
        du_mm: float,
        total_mm: float,
        h_acc_m: float,
        gnss_fix_type: int | None = None,
        rtklib_quality: int | None = None,
        rtklib_ns: int | None = None,
        rtklib_age_s: float | None = None,
        rtklib_ratio: float | None = None,
        rtklib_sdn_m: float | None = None,
        rtklib_sde_m: float | None = None,
        rtklib_sdu_m: float | None = None,
        source_file: str | None = None,
        validation_status: str = "unverified",
    ) -> None:
        rows = [
            (device_id, site_id, "displacement", total_mm, "mm"),
            (device_id, site_id, "disp_e", de_mm, "mm"),
            (device_id, site_id, "disp_n", dn_mm, "mm"),
            (device_id, site_id, "disp_u", du_mm, "mm"),
            (device_id, site_id, "h_acc_m", h_acc_m, "m"),
        ]
        optional = [
            ("gnss_fix_type", gnss_fix_type, ""),
            ("rtklib_quality", rtklib_quality, ""),
            ("rtklib_ns", rtklib_ns, ""),
            ("rtklib_age_s", rtklib_age_s, "s"),
            ("rtklib_ratio", rtklib_ratio, ""),
            ("rtklib_sdn_m", rtklib_sdn_m, "m"),
            ("rtklib_sde_m", rtklib_sde_m, "m"),
            ("rtklib_sdu_m", rtklib_sdu_m, "m"),
        ]
        rows.extend(
            (device_id, site_id, quantity, float(value), unit)
            for quantity, value, unit in optional
            if value is not None
        )
        await self._insert_rows(
            timestamp_utc, rows, source_kind="derived", source_file=source_file,
            validation_status=validation_status,
        )

    async def write_vibration(
        self, device_id: str, site_id: str, timestamp_utc: datetime, ppa_g: float, ppv_mm_s: float,
    ) -> None:
        rows = [
            (device_id, site_id, "ppa", ppa_g, "g"),
            (device_id, site_id, "ppv", ppv_mm_s, "mm/s"),
        ]
        await self._insert_rows(timestamp_utc, rows, source_kind="derived")

    async def write_tilt(
        self, device_id: str, site_id: str, timestamp_utc: datetime, tilt_x_deg: float, tilt_y_deg: float,
    ) -> None:
        rows = [
            (device_id, site_id, "tilt_x", tilt_x_deg, "deg"),
            (device_id, site_id, "tilt_y", tilt_y_deg, "deg"),
        ]
        await self._insert_rows(timestamp_utc, rows, source_kind="derived")

    async def write_weather(
        self, site_id: str, timestamp_utc: datetime, rainfall_mm: float, temperature_c: float, humidity_pct: float,
        rainfall_24h_mm: float | None = None, rainfall_72h_mm: float | None = None,
    ) -> None:
        rows = [
            ("WEATHER-API", site_id, "rainfall_external", rainfall_mm, "mm"),
            ("WEATHER-API", site_id, "temperature_external", temperature_c, "C"),
            ("WEATHER-API", site_id, "humidity_external", humidity_pct, "%"),
        ]
        if rainfall_24h_mm is not None:
            rows.append(("WEATHER-API", site_id, "rainfall_24h_external", rainfall_24h_mm, "mm"))
        if rainfall_72h_mm is not None:
            rows.append(("WEATHER-API", site_id, "rainfall_72h_external", rainfall_72h_mm, "mm"))
        await self._insert_rows(
            timestamp_utc,
            rows,
            source_kind="external",
            source_file="Open-Meteo",
            validation_status="not_applicable",
        )

    async def _insert_rows(
        self,
        timestamp_utc: datetime,
        rows: list[tuple],
        *,
        source_kind: str = "device",
        source_file: str | None = None,
        validation_status: str = "unverified",
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO measurements (
                    time, device_id, site_id, quantity, value, unit, received_at,
                    source_kind, source_file, validation_status
                )
                VALUES ($1, $2, $3, $4, $5, $6, now(), $7, $8, $9)
                ON CONFLICT (device_id, quantity, time) DO NOTHING
                """,
                [
                    (
                        timestamp_utc, device_id, site_id, quantity, value, unit,
                        source_kind, source_file, validation_status,
                    )
                    for device_id, site_id, quantity, value, unit in rows
                ],
            )
