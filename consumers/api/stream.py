"""Single MQTT -> SSE fan-out.

Uses a paho background network thread (not aiomqtt) so it is independent of the
web server's asyncio loop policy — on Windows, uvicorn's default Proactor loop
cannot drive paho's add_reader/add_writer, so we keep MQTT off the async loop
entirely and bridge into the SSE queues with call_soon_threadsafe. One MQTT
subscription feeds every browser; the client routes by device_id (context.md
§10.9 — never one EventSource per sensor).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None
_client: mqtt.Client | None = None


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def _broadcast(event: dict) -> None:
    payload = json.dumps(event)

    def _put() -> None:
        for q in list(_subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow client — drop rather than stall the fan-out

    if _loop is not None:
        _loop.call_soon_threadsafe(_put)


def _on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe("slope/+/+/data")


def _on_message(client, userdata, msg):
    received = datetime.now(timezone.utc).isoformat()
    try:
        env = json.loads(msg.payload)
    except Exception:
        return
    for r in env.get("readings", []):
        _broadcast({
            "device_id": env.get("device_id"),
            "site_id": env.get("site_id"),
            "quantity": r.get("quantity"),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "depth_cm": r.get("depth_cm"),
            "quality_flag": r.get("quality_flag", "ok"),
            "t": env.get("timestamp"),
            "received": received,
        })


def start() -> None:
    """Capture the running asyncio loop and start paho's network thread."""
    global _loop, _client
    _loop = asyncio.get_running_loop()
    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dashboard-api")
    _client.on_connect = _on_connect
    _client.on_message = _on_message
    _client.connect_async(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")))
    _client.loop_start()


async def stop() -> None:
    global _client
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None
