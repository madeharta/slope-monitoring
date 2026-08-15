"""Continuous multi-device fleet for the dashboard: several slopes, each with a
GNSS rover, an accelerometer node, a rain gauge, a soil-moisture probe, and a
piezometer. One aiomqtt client per device (unique client id), all driven by the
shared per-site physical model so the causal chain rainfall -> pore pressure ->
tilt -> creep displacement is visible and plausible.

Each device can carry several readings in one envelope (the GNSS rover emits its
3D resultant plus east/north/vertical components; the accelerometer node emits
two tilt axes plus micro-vibration; the piezometer emits suction and pore
pressure at different depths). This matches the real field nodes from the ITB
contact (§14) and exercises the multi-reading payload shape, not just 1 reading.

    python loadgen/fleet.py

Env: MQTT_HOST/MQTT_PORT/MQTT_QOS, LOADGEN_SEED (42),
     FLEET_INTERVAL_S (3), FLEET_SPEEDUP (8 simulated minutes per real second).
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import aiomqtt  # noqa: E402

from common.schema import Envelope, Location, Reading  # noqa: E402
from common.topics import build_topic  # noqa: E402
from loadgen.config import SITES, WIB, device_rng, jittered_location  # noqa: E402
from loadgen.physical import SiteWeather  # noqa: E402

# A device is (suffix, device_type, [reading, ...]) where each reading is
# (quantity, unit, depth_cm, reader). Devices with more than one reading publish
# them together in a single envelope.
DEVICES = [
    ("gnss", "gnss", [
        ("displacement", "mm", None, lambda w: w.disp_resultant()),
        ("disp_e", "mm", None, lambda w: w.disp_e()),
        ("disp_n", "mm", None, lambda w: w.disp_n()),
        ("disp_u", "mm", None, lambda w: w.disp_u()),
    ]),
    ("accel", "esp32", [  # ADXL355 / MPU9025 node
        ("tilt_x", "deg", None, lambda w: w.tilt_x()),
        ("tilt_y", "deg", None, lambda w: w.tilt_y()),
        ("vibration", "Hz", None, lambda w: w.vibration()),
    ]),
    ("rain", "arduino-mkr", [
        ("rainfall", "mm/h", None, lambda w: w.rain_mmh()),
    ]),
    ("soil", "esp32", [
        ("soil_moisture", "pct", 30.0, lambda w: w.moisture()),
    ]),
    ("piezo", "esp32", [
        ("suction", "kPa", 60.0, lambda w: w.suction()),
        ("pore_pressure", "kPa", 100.0, lambda w: w.pore_pressure()),
    ]),
]


async def device_task(site, spec, weather, host, port, qos, interval, seed):
    suffix, dtype, channels = spec
    device_id = f"{dtype}-{site.site_id}-{suffix}"
    rng = device_rng(seed, device_id)
    lat, lon = jittered_location(site, rng)
    while True:
        try:
            async with aiomqtt.Client(hostname=host, port=port, identifier=device_id) as client:
                while True:
                    env = Envelope(
                        device_id=device_id, device_type=dtype, site_id=site.site_id,
                        timestamp=datetime.now(WIB), location=Location(lat=lat, lon=lon),
                        readings=[
                            Reading(quantity=q, value=reader(weather), unit=unit,
                                    depth_cm=depth, quality_flag="ok")
                            for (q, unit, depth, reader) in channels
                        ],
                    )
                    await client.publish(build_topic(site.site_id, device_id), env.to_json(), qos=qos)
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(2)  # broker hiccup — reconnect

# Trigger the per-site weather model to step forward in time, so that all devices
async def weather_task(weathers, speedup):
    while True:
        for w in weathers.values():
            w.step(minutes=speedup)
        await asyncio.sleep(1.0)


async def main():
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    qos = int(os.getenv("MQTT_QOS", "1"))
    seed = int(os.getenv("LOADGEN_SEED", "42"))
    interval = float(os.getenv("FLEET_INTERVAL_S", "3"))
    speedup = float(os.getenv("FLEET_SPEEDUP", "8"))

    # per-site hazard bias -> a stable spread of Normal / Siaga / Bahaya
    hazard = {"lereng-a": 0.2, "lereng-b": 0.95, "lereng-c": 0.28,
              "lereng-d": 0.6, "lereng-e": 0.3, "lereng-f": 0.55}
    weathers = {
        sid: SiteWeather(rng=random.Random(f"{seed}:{sid}"), hazard=hazard.get(sid, 0.3))
        for sid in SITES
    }
    # settle wetness to each site's equilibrium so the baseline status is stable
    for w in weathers.values():
        for _ in range(300):
            w.step(minutes=1.0)

    n_dev = len(SITES) * len(DEVICES)
    print(f"fleet up: {len(SITES)} slopes x {len(DEVICES)} devices = {n_dev} devices "
          f"-> {host}:{port} (interval {interval}s, speedup {speedup}x)", flush=True)

    tasks = [asyncio.create_task(weather_task(weathers, speedup))]
    for site in SITES.values():
        for spec in DEVICES:
            tasks.append(asyncio.create_task(
                device_task(site, spec, weathers[site.site_id], host, port, qos, interval, seed)
            ))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
