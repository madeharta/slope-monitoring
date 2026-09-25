from __future__ import annotations
import logging
from common.errors import InvalidCsvError, NotFoundError
from ml.pipeline.feature_engineering.displacement import compute_displacement_mm
from ml.pipeline.feature_engineering.tilt import compute_tilt
from ml.pipeline.feature_engineering.vibration import compute_vibration_metrics
from ml.pipeline.preprocessing.ppk_engine import PPKEngine, PPKSolveError
from services.ingestion_service.raw_staging_repository import RawStagingRepository
from services.monitoring_service.device_repository import DeviceRepository
from services.monitoring_service.measurements_writer import MeasurementsWriter
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
        self._ppk_engine_factory = ppk_engine_factory
    async def handle_gnss_rows(
        self, device_id: str, device_role: str, file_name: str, rows: list[tuple],
    ) -> None:
        batch = [(device_id, ts, raw, file_name) for _dev, ts, raw in rows]
        await self._raw.insert_gnss_raw_batch(batch)
        if device_role != "rover":
            return
        site_id = await self._devices.get_site_id(device_id)
        base_id = await self._devices.get_base_device_id_for_site(site_id)
        try:
            base_reference = await self._reference.get(base_id)
        except NotFoundError:
            logger.warning("no surveyed reference position for base %s — skipping PPK for %s", base_id, device_id)
            return
        try:
            baseline = await self._rover_baselines.get(device_id)
        except NotFoundError:
            logger.warning("approved rover baseline missing for %s; no displacement emitted", device_id)
            return
        if baseline.vertical_datum != "ELLIPSOIDAL_WGS84":
            logger.warning("4G PPK requires ellipsoidal baseline for %s; no displacement emitted", device_id)
            return
        ppk_engine = self._ppk_engine_factory(base_reference)
        for _dev, ts, rover_raw in rows:
            base_epoch = await self._raw.find_nearest_base_epoch(base_id, ts)
            if base_epoch is None:
                logger.info("no base epoch within tolerance for rover %s @ %s — epoch dropped", device_id, ts)
                continue
            _base_ts, base_raw = base_epoch
            try:
                result = ppk_engine.solve(base_raw, rover_raw)
            except PPKSolveError as exc:
                logger.warning("PPK failed for %s @ %s: %s", device_id, ts, exc)
                continue
            if result.gnss_fix_type != 4 or not (0 <= result.h_acc_m <= baseline.max_h_acc_m):
                logger.warning("PPK %s @ %s quality not accepted: fix=%s, h_acc_m=%s; no displacement emitted", device_id, ts, result.gnss_fix_type, result.h_acc_m)
                continue
            disp = compute_displacement_mm(
                result.latitude, result.longitude, result.altitude_m,
                baseline.latitude, baseline.longitude, baseline.altitude_m,
            )
            await self._measurements.write_displacement(
                device_id=device_id, site_id=site_id, timestamp_utc=ts,
                de_mm=disp.de_mm, dn_mm=disp.dn_mm, du_mm=disp.du_mm, total_mm=disp.total_mm,
                h_acc_m=result.h_acc_m, gnss_fix_type=result.gnss_fix_type,
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
        baselines = {}
        for rover_id in {sample.device_id for sample in rows}:
            try:
                baselines[rover_id] = await self._rover_baselines.get(rover_id)
            except NotFoundError:
                logger.warning("approved rover baseline missing for %s; no deformation emitted", rover_id)
        for sample in rows:
            baseline = baselines.get(sample.device_id)
            if (baseline is None or baseline.vertical_datum != "MSL_CONFIRMED"
                or sample.gnss_fix_type == 0 or not (0 <= sample.h_acc_m <= baseline.max_h_acc_m)):
                logger.warning("skipping LoRa displacement for %s: baseline/datum/fix not accepted", sample.device_id)
                continue
            disp = compute_displacement_mm(
                sample.latitude, sample.longitude, sample.altitude_m,
                baseline.latitude, baseline.longitude, baseline.altitude_m,
            )
            await self._measurements.write_displacement(
                device_id=sample.device_id, site_id=site_id, timestamp_utc=sample.timestamp_utc,
                de_mm=disp.de_mm, dn_mm=disp.dn_mm, du_mm=disp.du_mm, total_mm=disp.total_mm,
                h_acc_m=sample.h_acc_m, gnss_fix_type=sample.gnss_fix_type,
            )
    async def handle_accel_rows(
        self, device_id: str, rows: list, blast_command_id: int | None = None,
    ) -> None:
        if not rows:
            return
        await self._raw.insert_accel_raw_batch(device_id, rows, blast_command_id=blast_command_id)
        site_id = await self._devices.get_site_id(device_id)
        metrics = compute_vibration_metrics(rows, sensor="adxl355")
        event_time = rows[0].timestamp_utc
        await self._measurements.write_vibration(
            device_id=device_id, site_id=site_id, timestamp_utc=event_time,
            ppa_g=metrics.ppa_g, ppv_mm_s=metrics.ppv_mm_s,
        )
        tilt = compute_tilt(rows, sensor="adxl355")
        await self._measurements.write_tilt(
            device_id=device_id, site_id=site_id, timestamp_utc=event_time,
            tilt_x_deg=tilt.tilt_x_deg, tilt_y_deg=tilt.tilt_y_deg,
        )
