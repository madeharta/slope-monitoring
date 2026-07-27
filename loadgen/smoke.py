"""Smoke test producer: one device, one measurement, published once.

Proves the schema + broker round-trip and gives the db-writer something to
stamp on receipt. Run the db-writer first, then:

    python loadgen/smoke.py

Env: MQTT_HOST (default localhost), MQTT_PORT (1883), MQTT_QOS (1),
     LOADGEN_SEED (42).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running as a plain script (`python loadgen/smoke.py`) from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiomqtt  # noqa: E402

from common.schema import Envelope, Location, Reading  # noqa: E402
from common.topics import build_topic  # noqa: E402
from loadgen.config import ESP32_SOIL, SITES, WIB, device_rng, jittered_location  # noqa: E402


async def main() -> None:
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    qos = int(os.getenv("MQTT_QOS", "1"))
    seed = int(os.getenv("LOADGEN_SEED", "42"))

    site = SITES["lereng-a"]
    device_id = "esp32-lereng-a-01"
    rng = device_rng(seed, device_id)
    lat, lon = jittered_location(site, rng)
    spec = ESP32_SOIL.quantities[0]

    envelope = Envelope(
        device_id=device_id,
        device_type=ESP32_SOIL.device_type,
        site_id=site.site_id,
        timestamp=datetime.now(WIB),  # produce/ingress time, sub-second, tz-aware
        location=Location(lat=lat, lon=lon),
        readings=[
            Reading(
                quantity=spec.quantity,
                value=round(rng.uniform(20.0, 45.0), 2),
                unit=spec.unit,
                depth_cm=spec.depth_cm,
                quality_flag="ok",
            )
        ],
    )

    topic = build_topic(site.site_id, device_id)
    payload = envelope.to_json()

    # Unique client identifier per simulated device — the single most
    # important requirement (context.md §4.1/§7).
    async with aiomqtt.Client(hostname=host, port=port, identifier=device_id) as client:
        await client.publish(topic, payload=payload, qos=qos)

    print(f"published to {topic} (qos={qos}, client_id={device_id})")
    print(payload)


if __name__ == "__main__":
    # paho-mqtt (under aiomqtt) needs add_reader/add_writer, which on Windows
    # only the Selector loop implements — the default Proactor loop raises
    # NotImplementedError. No-op on Linux/Docker.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
