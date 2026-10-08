from __future__ import annotations
import logging
import os
from datetime import timedelta
from common.errors import InvalidCsvError, NotFoundError
from ml.pipeline.feature_engineering.displacement import compute_displacement_mm
from ml.pipeline.feature_engineering.tilt import compute_tilt
from ml.pipeline.feature_engineering.vibration import analyze_accel_window, compute_vibration_metrics
from ml.pipeline.preprocessing.ppk_engine import PPKSolveError
from services.ingestion_service.raw_staging_repository import RawStagingRepository
from services.monitoring_service.device_repository import DeviceRepository
from services.monitoring_service.measurements_writer import MeasurementsWriter
from services.monitoring_service.ppk_solution_repository import PPKSolutionRepository
from services.monitoring_service.blast_event_repository import BlastEventRepository
from services.monitoring_service.reference_position_repository import ReferencePositionRepository
from services.monitoring_service.rover_baseline_repository import RoverBaselineRepository

logger = logging.getLogger("slope_monitoring.canonicalization")


class CanonicalizationService:
    def __init__(self, pool, ppk_engine_factory) -> None:
        self._pool = pool
        self._raw = RawStagingRepository(pool)
        self._devices = DeviceRepository(pool)
        self._reference = ReferencePositionRepository(pool)
        self._rover_baselines = RoverBaselineRepository(pool)
        self._measurements = MeasurementsWriter(pool)
        self._ppk_solutions = PPKSolutionRepository(pool)
        self._blast_events = BlastEventRepository(pool)
        self._ppk_engine_factory = ppk_engine_factory
        self._ppk_window_seconds = int(os.getenv("PPK_WINDOW_SECONDS", "300"))
        self._ppk_window_pad_seconds = int(os.getenv("PPK_WINDOW_PAD_SECONDS", "30"))
        self._ppk_min_epochs = int(os.getenv("PPK_MIN_EPOCHS", "4"))
        self._ppk_max_h_acc_m = float(os.getenv("PPK_MAX_H_ACC_M", "0.10"))
        self._ppk_accepted_quality = {
            int(value) for value in os.getenv("PPK_ACCEPTED_RTKLIB_QUALITY", "1").split(",") if value.strip()
        }

    async def handle_gnss_rows(
        self, device_id: str, device_role: str, file_name: str, rows: list[tuple],
    ) -> None:
        if not rows:
            return
        batch = [(device_id, ts, raw, file_name) for _dev, ts, raw in rows]
        await self._raw.insert_gnss_raw_batch(batch)
        site_id = await self._devices.get_site_id(device_id)
        base_id = await self._devices.get_base_device_id_for_site(site_id)
        timestamps = [ts for _dev, ts, _raw in rows]
        pad = timedelta(seconds=self._ppk_window_pad_seconds)
        window_start = min(timestamps) - pad
        window_end = max(timestamps) + pad
        if (window_end - window_start).total_seconds() < self._ppk_window_seconds:
            center = min(timestamps) + (max(timestamps) - min(timestamps)) / 2
            half = timedelta(seconds=self._ppk_window_seconds / 2)
            window_start = center - half
            window_end = center + half
        if device_role == "rover":
            rover_ids = [device_id]
        else:
            rover_ids = await self._devices.get_rover_device_ids_for_site(site_id)
        for rover_id in rover_ids:
            await self._process_ppk_window(
                site_id=site_id,
                base_id=base_id,
                rover_id=rover_id,
                window_start=window_start,
                window_end=window_end,
            )

    async def _process_ppk_window(
        self,
        *,
        site_id: str,
        base_id: str,
        rover_id: str,
        window_start,
        window_end,
    ) -> None:
        try:
            base_reference = await self._reference.get(base_id)
        except NotFoundError:
            logger.warning("no surveyed reference position for base %s — PPK pending for %s", base_id, rover_id)
            return
        if base_reference.vertical_datum != "ELLIPSOIDAL_WGS84":
            logger.warning(
                "base %s reference vertical datum is not confirmed ELLIPSOIDAL_WGS84 — PPK blocked",
                base_id,
            )
            return
        try:
            baseline = await self._rover_baselines.get(rover_id)
        except NotFoundError:
            logger.warning("approved rover baseline missing for %s; no displacement emitted", rover_id)
            return
        if baseline.vertical_datum != "ELLIPSOIDAL_WGS84":
            logger.warning("PPK requires ellipsoidal rover baseline for %s; no displacement emitted", rover_id)
            return
        base_rows = await self._raw.get_gnss_window(base_id, window_start, window_end)
        rover_rows = await self._raw.get_gnss_window(rover_id, window_start, window_end)
        if len(base_rows) < self._ppk_min_epochs or len(rover_rows) < self._ppk_min_epochs:
            logger.info(
                "PPK window pending %s: base=%d rover=%d min=%d [%s, %s]",
                rover_id, len(base_rows), len(rover_rows), self._ppk_min_epochs, window_start, window_end,
            )
            return
        base_stream = _dedupe_and_join(base_rows)
        rover_stream = _dedupe_and_join(rover_rows)
        observed_at = min(rover_rows, key=lambda row: row[0])[0]
        ppk_engine = self._ppk_engine_factory(base_reference)
        try:
            result = ppk_engine.solve_window(
                base_stream,
                rover_stream,
                observed_at=observed_at,
                station=None,
            )
        except PPKSolveError as exc:
            logger.warning("PPK window failed for %s [%s, %s]: %s", rover_id, window_start, window_end, exc)
            return
        for solution in result.solutions:
            if solution.rtklib_quality not in self._ppk_accepted_quality:
                logger.info(
                    "PPK solution rejected for %s @ %s: Q=%s",
                    rover_id, solution.timestamp_utc, solution.rtklib_quality,
                )
                continue
            max_h_acc = min(self._ppk_max_h_acc_m, baseline.max_h_acc_m)
            if not (0 <= solution.h_acc_m <= max_h_acc):
                logger.info(
                    "PPK solution rejected for %s @ %s: h_acc_m=%s max=%s",
                    rover_id, solution.timestamp_utc, solution.h_acc_m, max_h_acc,
                )
                continue
            disp = compute_displacement_mm(
                solution.latitude,
                solution.longitude,
                solution.ellipsoidal_height_m,
                baseline.latitude,
                baseline.longitude,
                baseline.altitude_m,
            )
            await self._ppk_solutions.write_accepted(
                site_id=site_id,
                base_device_id=base_id,
                rover_device_id=rover_id,
                solution=solution,
                result=result,
                displacement=disp,
            )
            await self._measurements.write_displacement(
                device_id=rover_id,
                site_id=site_id,
                timestamp_utc=solution.timestamp_utc,
                de_mm=disp.de_mm,
                dn_mm=disp.dn_mm,
                du_mm=disp.du_mm,
                total_mm=disp.total_mm,
                h_acc_m=solution.h_acc_m,
                rtklib_quality=solution.rtklib_quality,
                rtklib_ns=solution.satellites,
                rtklib_age_s=solution.age_s,
                rtklib_ratio=solution.ratio,
                rtklib_sdn_m=solution.sdn_m,
                rtklib_sde_m=solution.sde_m,
                rtklib_sdu_m=solution.sdu_m,
                source_file="RTKLIB_PPK",
                validation_status="unverified",
            )

    async def handle_position_rows(self, device_id: str, rows: list) -> None:
        if not rows:
            return
        site_id = await self._devices.get_site_id(device_id)
        for rover_id in {sample.device_id for sample in rows}:
            rover_site_id = await self._devices.get_site_id(rover_id)
            if rover_site_id != site_id:
                raise InvalidCsvError(
                    f"position.csv rover '{rover_id}' belongs to a different site than uploader '{device_id}'"
                )
        # Store the latest direct GNSS position independently from displacement.
        # A valid coordinate is useful for the device map even when the rover
        # baseline is unavailable or displacement remains UNVALIDATED.
        if self._pool is not None:
            from services.monitoring_service.device_position_repository import DevicePositionRepository

            position_repo = DevicePositionRepository(self._pool)
            for sample in rows:
                if sample.gnss_fix_type > 0:
                    await position_repo.write_rtk_direct(site_id=site_id, sample=sample)

        baselines = {}
        for rover_id in {sample.device_id for sample in rows}:
            try:
                baselines[rover_id] = await self._rover_baselines.get(rover_id)
            except NotFoundError:
                logger.warning("approved rover baseline missing for %s; no deformation emitted", rover_id)
        for sample in rows:
            baseline = baselines.get(sample.device_id)
            if (
                baseline is None
                or baseline.vertical_datum != "ELLIPSOIDAL_WGS84"
                or sample.gnss_fix_type == 0
                or not (0 <= sample.h_acc_m <= baseline.max_h_acc_m)
            ):
                logger.warning("skipping LoRa displacement for %s: baseline/datum/fix not accepted", sample.device_id)
                continue
            disp = compute_displacement_mm(
                sample.latitude,
                sample.longitude,
                sample.altitude_m,
                baseline.latitude,
                baseline.longitude,
                baseline.altitude_m,
            )
            await self._measurements.write_displacement(
                device_id=sample.device_id,
                site_id=site_id,
                timestamp_utc=sample.timestamp_utc,
                de_mm=disp.de_mm,
                dn_mm=disp.dn_mm,
                du_mm=disp.du_mm,
                total_mm=disp.total_mm,
                h_acc_m=sample.h_acc_m,
                gnss_fix_type=sample.gnss_fix_type,
            )

    async def handle_accel_rows(
        self, device_id: str, rows: list, blast_command_id: int | None = None,
        *, file_name: str, communication_mode: str,
    ) -> None:
        if not rows:
            return
        sample_devices = {sample.device_id for sample in rows}
        if sample_devices != {device_id}:
            raise InvalidCsvError(
                f"accelerometer CSV device_id mismatch: upload header={device_id}, rows={sorted(sample_devices)}"
            )
        await self._raw.insert_accel_raw_batch(
            device_id, rows, blast_command_id=blast_command_id, file_name=file_name,
        )
        site_id = await self._devices.get_site_id(device_id)
        quality = analyze_accel_window(rows)
        event_time = rows[0].timestamp_utc
        event_end = rows[-1].timestamp_utc

        adxl_metrics = None
        mpu_metrics = None
        if quality.quality_gate_status != "rejected":
            adxl_metrics = compute_vibration_metrics(rows, sensor="adxl355")
            mpu_metrics = compute_vibration_metrics(rows, sensor="mpu9250")

        await self._blast_events.write_event(
            site_id=site_id,
            device_id=device_id,
            source_file=file_name,
            communication_mode=communication_mode,
            event_start=event_time,
            event_end=event_end,
            sample_count=quality.sample_count,
            duration_ms=quality.duration_ms,
            observed_sample_rate_hz=quality.observed_sample_rate_hz,
            median_gap_ms=quality.median_gap_ms,
            max_gap_ms=quality.max_gap_ms,
            quality_gate_status=quality.quality_gate_status,
            quality_reasons=quality.reasons,
            adxl355_ppa_g=(adxl_metrics.ppa_g if adxl_metrics else None),
            adxl355_ppv_mm_s=(adxl_metrics.ppv_mm_s if adxl_metrics else None),
            mpu9250_ppa_g=(mpu_metrics.ppa_g if mpu_metrics else None),
            mpu9250_ppv_mm_s=(mpu_metrics.ppv_mm_s if mpu_metrics else None),
            blast_command_id=blast_command_id,
        )

        if adxl_metrics is None or mpu_metrics is None:
            logger.warning(
                "accelerometer event %s rejected by quality gate: %s",
                file_name, ",".join(quality.reasons),
            )
            return

        await self._measurements.write_vibration(
            device_id=device_id,
            site_id=site_id,
            timestamp_utc=event_time,
            ppa_g=adxl_metrics.ppa_g,
            ppv_mm_s=adxl_metrics.ppv_mm_s,
            ppa_mpu9250_g=mpu_metrics.ppa_g,
            ppv_mpu9250_mm_s=mpu_metrics.ppv_mm_s,
            sample_rate_hz=quality.observed_sample_rate_hz,
            duration_ms=quality.duration_ms,
            source_file=file_name,
            validation_status="unverified",
        )
        tilt = compute_tilt(rows, sensor="adxl355")
        await self._measurements.write_tilt(
            device_id=device_id,
            site_id=site_id,
            timestamp_utc=event_time,
            tilt_x_deg=tilt.tilt_x_deg,
            tilt_y_deg=tilt.tilt_y_deg,
            source_file=file_name,
            validation_status="unverified",
        )


def _dedupe_and_join(rows: list[tuple]) -> bytes:
    seen: set[tuple] = set()
    chunks: list[bytes] = []
    for timestamp, payload, _file_name in sorted(rows, key=lambda row: row[0]):
        key = (timestamp, payload)
        if key in seen:
            continue
        seen.add(key)
        chunks.append(payload)
    return b"".join(chunks)
