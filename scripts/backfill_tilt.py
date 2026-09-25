from __future__ import annotations
import asyncio
import os
import asyncpg
from dotenv import load_dotenv
from ml.domain.canonical_schema import CanonicalAccelSample
from ml.pipeline.feature_engineering.tilt import compute_tilt
from services.monitoring_service.measurements_writer import MeasurementsWriter
load_dotenv()
_EVENT_GAP_SECONDS = 60
async def backfill() -> None:
    pool = await asyncpg.create_pool(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "slope"), user=os.getenv("DB_USER", "slope"),
        password=os.getenv("DB_PASSWORD"),
    )
    writer = MeasurementsWriter(pool)
    async with pool.acquire() as conn:
        devices = await conn.fetch("SELECT DISTINCT device_id FROM accel_raw_samples ORDER BY device_id")
        site_by_device = {
            r["device_id"]: r["site_id"]
            for r in await conn.fetch("SELECT device_id, site_id FROM devices")
        }
        total_events = 0
        for dev_row in devices:
            device_id = dev_row["device_id"]
            if device_id not in site_by_device:
                print(f"  LEWATI {device_id}: tidak terdaftar di tabel devices (site tidak diketahui)")
                continue
            site_id = site_by_device[device_id]
            rows = await conn.fetch(
                """
                SELECT time, adxl355_x_mps2, adxl355_y_mps2, adxl355_z_mps2,
                       mpu9250_x_mps2, mpu9250_y_mps2, mpu9250_z_mps2
                FROM accel_raw_samples WHERE device_id = $1 ORDER BY time ASC
                """,
                device_id,
            )
            if not rows:
                continue
            events: list[list] = [[rows[0]]]
            for prev, cur in zip(rows, rows[1:]):
                gap = (cur["time"] - prev["time"]).total_seconds()
                if gap > _EVENT_GAP_SECONDS:
                    events.append([])
                events[-1].append(cur)
            for event_rows in events:
                samples = [
                    CanonicalAccelSample(
                        device_id=device_id, sample_index=i, timestamp_utc=r["time"],
                        adxl355_xyz_mps2=(r["adxl355_x_mps2"], r["adxl355_y_mps2"], r["adxl355_z_mps2"]),
                        mpu9250_xyz_mps2=(r["mpu9250_x_mps2"], r["mpu9250_y_mps2"], r["mpu9250_z_mps2"]),
                        colocated_position=None,
                    )
                    for i, r in enumerate(event_rows)
                ]
                tilt = compute_tilt(samples, sensor="adxl355")
                event_time = event_rows[0]["time"]
                await writer.write_tilt(
                    device_id=device_id, site_id=site_id, timestamp_utc=event_time,
                    tilt_x_deg=tilt.tilt_x_deg, tilt_y_deg=tilt.tilt_y_deg,
                )
                total_events += 1
                print(f"  {device_id} @ {event_time}: tilt_x={tilt.tilt_x_deg:.2f}° tilt_y={tilt.tilt_y_deg:.2f}° ({len(samples)} sample)")
    await pool.close()
    print(f"\nSelesai — {total_events} event tilt ditulis.")
if __name__ == "__main__":
    asyncio.run(backfill())
