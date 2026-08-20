"""Consumer: MQTT (variant A) or Kafka (variants B/C/D) -> TimescaleDB, batched,
with a per-message hop stamp.

The *source* is selected by the SOURCE env var so a single consumer serves every
variant unchanged (context.md: "same consumer interface, so the benchmark
harness targets any variant unmodified"):

  SOURCE=mqtt   (default)  subscribe to the wildcard MQTT topic directly.
  SOURCE=kafka             consume the Kafka topic the MQTT Source Connector
                           (B) or native broker bridge (C) feeds. The Kafka
                           message value is the untouched JSON envelope (the
                           connector uses a bytes/ByteArray converter), so the
                           downstream path — parse, latency, batch, COPY — is
                           byte-for-byte identical to the MQTT path.

Either way: receipt time is stamped (the consumer hop), end-to-end latency is
computed against the payload's produce timestamp, then rows are *buffered* and
flushed in bulk — when the buffer fills (BATCH_MAX_ROWS) or on a timer
(BATCH_FLUSH_MS). Bulk writes use asyncpg's COPY path (`copy_records_to_table`),
far faster than one INSERT per reading, which is what lets a single consumer
keep up under load. Latency is stamped at receipt, *before* buffering, so it is
transport latency and does not include buffer wait.

Run (host, against a variant compose stack):

    python consumers/db-writer/writer.py                 # variant A (MQTT)
    SOURCE=kafka python consumers/db-writer/writer.py     # variant B/C/D (Kafka)

Env: SOURCE (mqtt|kafka), MQTT_HOST/MQTT_PORT,
     KAFKA_BOOTSTRAP (default localhost:9092), KAFKA_TOPIC, KAFKA_GROUP,
     DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD,
     BATCH_MAX_ROWS (default 500), BATCH_FLUSH_MS (default 1000).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Repo root on path so `common` imports work (this dir has a hyphen and
# cannot itself be an importable package).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from common.metrics import LatencyAccumulator  # noqa: E402
from common.schema import Envelope  # noqa: E402
from common.topics import KAFKA_TOPIC, SUBSCRIBE_ALL  # noqa: E402

_UPSERT_DEVICE = """
INSERT INTO devices (device_id, device_type, site_id, last_seen)
VALUES ($1, $2, $3, now())
ON CONFLICT (device_id) DO UPDATE SET last_seen = now();
"""

_MEASUREMENT_COLUMNS = [
    "time",
    "device_id",
    "site_id",
    "quantity",
    "value",
    "unit",
    "depth_cm",
    "quality_flag",
    "received_at",
    "latency_ms",
]


class Batcher:
    """Buffers measurement rows and flushes them in bulk (by size or timer).

    The buffer is swapped out under a lock before the (awaited) DB write, so
    messages arriving mid-flush accumulate into the next batch rather than
    racing the one being written.
    """

    def __init__(self, pool: asyncpg.Pool, max_rows: int, flush_interval_s: float) -> None:
        self._pool = pool
        self._max_rows = max_rows
        self._interval_s = flush_interval_s
        self._rows: list[tuple] = []
        self._devices: dict[str, tuple[str, str]] = {}
        self._lock = asyncio.Lock()
        self._trigger = asyncio.Event()  # set when the buffer hits max_rows

    async def add(self, envelope: Envelope, received_at: datetime, latency_ms: float) -> None:
        async with self._lock:
            self._devices[envelope.device_id] = (envelope.device_type, envelope.site_id)
            for r in envelope.readings:
                self._rows.append(
                    (
                        envelope.timestamp,
                        envelope.device_id,
                        envelope.site_id,
                        r.quantity,
                        r.value,
                        r.unit,
                        r.depth_cm,
                        r.quality_flag,
                        received_at,
                        latency_ms,
                    )
                )
            full = len(self._rows) >= self._max_rows
        if full:
            self._trigger.set()

    async def flush(self) -> int:
        async with self._lock:
            if not self._rows:
                self._trigger.clear()
                return 0
            rows, devices = self._rows, self._devices
            self._rows, self._devices = [], {}
            self._trigger.clear()

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if devices:
                    await conn.executemany(
                        _UPSERT_DEVICE, [(d, t, s) for d, (t, s) in devices.items()]
                    )
                await conn.copy_records_to_table(
                    "measurements", records=rows, columns=_MEASUREMENT_COLUMNS
                )
        print(f"flushed {len(rows)} row(s), {len(devices)} device(s)", flush=True)
        return len(rows)

    async def run(self, stop: asyncio.Event) -> None:
        """Flush on the timer, or as soon as the buffer fills, until stopped."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(self._trigger.wait(), timeout=self._interval_s)
            except TimeoutError:
                pass
            await self.flush()


class Ingest:
    """Shared receive path: parse one raw payload, stamp latency, buffer it.

    Both source loops (MQTT and Kafka) call `handle`, so the parse / latency /
    batch logic is identical regardless of transport — the whole point of a
    single consumer across variants.

    Malformed-payload logging is rate-limited on purpose. A single stray
    publisher on a matching topic can produce hundreds of thousands of drops,
    and printing a full pydantic error for each one grew the log past 500 MB in
    minutes during a benchmark run. Log the first few in full, then a periodic
    count.
    """

    DROP_LOG_FIRST = 5
    DROP_LOG_EVERY = 10_000

    def __init__(self, batcher: "Batcher", acc: LatencyAccumulator) -> None:
        self._batcher = batcher
        self._acc = acc
        self.dropped = 0

    async def handle(self, payload: str | bytes, where: str) -> None:
        received_at = datetime.now(UTC)  # consumer-receipt hop stamp
        try:
            envelope = Envelope.from_json(payload)
        except Exception as exc:  # malformed payload — log and drop, don't crash
            self.dropped += 1
            if self.dropped <= self.DROP_LOG_FIRST:
                print(f"! dropped malformed message on {where}: {exc}", file=sys.stderr)
                if self.dropped == self.DROP_LOG_FIRST:
                    print(
                        f"! further malformed-payload details suppressed; "
                        f"a count is reported every {self.DROP_LOG_EVERY}",
                        file=sys.stderr,
                    )
            elif self.dropped % self.DROP_LOG_EVERY == 0:
                print(
                    f"! {self.dropped} malformed messages dropped so far "
                    f"(most recent: {where}) — is another publisher using this source?",
                    file=sys.stderr,
                )
            return
        latency_ms = (received_at - envelope.timestamp).total_seconds() * 1000.0
        self._acc.add(latency_ms)
        await self._batcher.add(envelope, received_at, latency_ms)


async def consume_mqtt(ingest: Ingest) -> None:
    import aiomqtt

    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    print(f"db-writer source=mqtt: subscribing {SUBSCRIBE_ALL} on {host}:{port}", flush=True)
    async with aiomqtt.Client(hostname=host, port=port, identifier="db-writer") as client:
        await client.subscribe(SUBSCRIBE_ALL)
        async for message in client.messages:
            await ingest.handle(message.payload, str(message.topic))


async def consume_kafka(ingest: Ingest) -> None:
    from aiokafka import AIOKafkaConsumer

    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", KAFKA_TOPIC)
    group = os.getenv("KAFKA_GROUP", "db-writer")
    # latest: a benchmark measures live traffic, not the backlog. auto-commit is
    # fine — at-least-once with a possible dup on crash is acceptable for a
    # metrics sink, and it keeps the hot path free of manual commits.
    consumer = AIOKafkaConsumer(
        topic, bootstrap_servers=bootstrap, group_id=group,
        auto_offset_reset="latest", enable_auto_commit=True,
    )
    print(f"db-writer source=kafka: consuming '{topic}' group '{group}' on {bootstrap}", flush=True)
    await consumer.start()
    try:
        async for msg in consumer:
            await ingest.handle(msg.value, f"{topic}[{msg.partition}]")
    finally:
        await consumer.stop()


async def main() -> None:
    source = os.getenv("SOURCE", "mqtt").lower()
    if source not in ("mqtt", "kafka"):
        raise SystemExit(f"SOURCE must be 'mqtt' or 'kafka', got {source!r}")
    max_rows = int(os.getenv("BATCH_MAX_ROWS", "500"))
    flush_interval_s = int(os.getenv("BATCH_FLUSH_MS", "1000")) / 1000.0

    pool = await asyncpg.create_pool(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "magris"),
        user=os.getenv("DB_USER", "magris"),
        password=os.getenv("DB_PASSWORD", "magris_dev"),
        min_size=1,
        max_size=4,
    )
    acc = LatencyAccumulator()
    batcher = Batcher(pool, max_rows=max_rows, flush_interval_s=flush_interval_s)
    ingest = Ingest(batcher, acc)
    stop = asyncio.Event()
    flusher = asyncio.create_task(batcher.run(stop))

    print(
        f"db-writer up: source={source} "
        f"(batch: {max_rows} rows / {flush_interval_s * 1000:.0f} ms, Ctrl-C to stop)",
        flush=True,
    )
    try:
        if source == "kafka":
            await consume_kafka(ingest)
        else:
            await consume_mqtt(ingest)
    finally:
        stop.set()
        batcher._trigger.set()  # wake the flusher so it exits promptly
        await flusher
        await batcher.flush()  # drain anything still buffered
        await pool.close()
        if ingest.dropped:
            print(f"\n! {ingest.dropped} malformed messages dropped in total", file=sys.stderr)
        print("\nlatency summary (ms):", json.dumps(acc.summary(), indent=2))


if __name__ == "__main__":
    # See smoke.py: Windows needs the Selector loop for paho-mqtt sockets.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
