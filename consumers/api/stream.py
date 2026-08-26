from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from common.topics import KAFKA_TOPIC, SUBSCRIBE_ALL

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None
_client = None            # paho client (SOURCE=mqtt)
_kafka_task: asyncio.Task | None = None  # consumer task (SOURCE=kafka)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def _events_from_payload(payload: str | bytes, received: str) -> list[dict]:
    """Parse one envelope into one SSE event per reading. Shared by both sources
    so the event shape never diverges between variants."""
    try:
        env = json.loads(payload)
    except Exception:
        return []  # keepalive/comment lines or malformed payloads
    out = []
    for r in env.get("readings", []):
        out.append({
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
    return out


def _deliver(events: list[dict]) -> None:
    """Fan events out to every SSE queue. MUST run on the event loop."""
    for ev in events:
        payload = json.dumps(ev)
        for q in list(_subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow client — drop rather than stall the fan-out


# ---- MQTT source (paho background thread) ----
def _on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe(SUBSCRIBE_ALL)


def _on_message(client, userdata, msg):
    received = datetime.now(timezone.utc).isoformat()
    events = _events_from_payload(msg.payload, received)
    if events and _loop is not None:
        _loop.call_soon_threadsafe(_deliver, events)


def _start_mqtt() -> None:
    global _client
    import paho.mqtt.client as mqtt

    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dashboard-api")
    _client.on_connect = _on_connect
    _client.on_message = _on_message
    _client.connect_async(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")))
    _client.loop_start()


# ---- Kafka source (aiokafka task on the event loop) ----
async def _run_kafka() -> None:
    from aiokafka import AIOKafkaConsumer

    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", KAFKA_TOPIC)
    # A unique group per process, reading from `latest`: the dashboard wants the
    # live tail and must NOT share the db-writer's group (that would split
    # partitions between them). No commits needed for a fire-and-forget tail.
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=bootstrap,
        group_id=f"dashboard-{os.getpid()}",
        auto_offset_reset="latest", enable_auto_commit=False,
    )
    await consumer.start()
    try:
        async for msg in consumer:
            received = datetime.now(timezone.utc).isoformat()
            _deliver(_events_from_payload(msg.value, received))
    except asyncio.CancelledError:
        raise
    finally:
        await consumer.stop()


def start() -> None:
    """Capture the running loop and start the configured source."""
    global _loop, _kafka_task
    _loop = asyncio.get_running_loop()
    source = os.getenv("SOURCE", "mqtt").lower()
    if source == "kafka":
        _kafka_task = _loop.create_task(_run_kafka())
    else:
        _start_mqtt()


async def stop() -> None:
    global _client, _kafka_task
    if _kafka_task is not None:
        _kafka_task.cancel()
        try:
            await _kafka_task
        except asyncio.CancelledError:
            pass
        _kafka_task = None
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None
