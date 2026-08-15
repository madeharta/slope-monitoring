"""Variant-A consumer: MQTT -> TimescaleDB, batched, with per-message hop stamp.

Subscribes to the wildcard data topic, stamps receipt time (the consumer hop),
computes end-to-end latency against the payload's produce timestamp, then
*buffers* rows and flushes them in bulk — either when the buffer fills
(BATCH_MAX_ROWS) or on a timer (BATCH_FLUSH_MS), whichever comes first.

Bulk writes use asyncpg's COPY path (`copy_records_to_table`), which is far
faster than one INSERT per reading and is what lets a single consumer keep up
under load. Latency is stamped at message receipt, *before* buffering, so the
reported latency is transport latency and does not include buffer wait.

Run (host, against the Variant-A compose stack):

    python consumers/db-writer/writer.py

Env: MQTT_HOST/MQTT_PORT, DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD,
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

import aiomqtt  # noqa: E402
import asyncpg  # noqa: E402

from common.metrics import LatencyAccumulator  # noqa: E402
from common.schema import Envelope  # noqa: E402
from common.topics import SUBSCRIBE_ALL  # noqa: E402

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


async def main() -> None:
    mqtt_host = os.getenv("MQTT_HOST", "localhost")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
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
    stop = asyncio.Event()
    flusher = asyncio.create_task(batcher.run(stop))

    print(
        f"db-writer up: subscribing {SUBSCRIBE_ALL} on {mqtt_host}:{mqtt_port} "
        f"(batch: {max_rows} rows / {flush_interval_s * 1000:.0f} ms, Ctrl-C to stop)",
        flush=True,
    )
    # Malformed-payload logging is rate-limited on purpose. A single stray
    # publisher on a matching topic can produce hundreds of thousands of drops,
    # and printing a full pydantic error for each one grew the log past 500 MB in
    # minutes during a benchmark run. Log the first few in full, then only a
    # periodic count.
    dropped = 0
    DROP_LOG_FIRST = 5
    DROP_LOG_EVERY = 10_000

    try:
        async with aiomqtt.Client(
            hostname=mqtt_host, port=mqtt_port, identifier="db-writer"
        ) as client:
            await client.subscribe(SUBSCRIBE_ALL)
            async for message in client.messages:
                received_at = datetime.now(UTC)  # consumer-receipt hop stamp
                try:
                    envelope = Envelope.from_json(message.payload)
                except Exception as exc:  # malformed payload — log and drop, don't crash
                    dropped += 1
                    if dropped <= DROP_LOG_FIRST:
                        print(
                            f"! dropped malformed message on {message.topic}: {exc}",
                            file=sys.stderr,
                        )
                        if dropped == DROP_LOG_FIRST:
                            print(
                                f"! further malformed-payload details suppressed; "
                                f"a count is reported every {DROP_LOG_EVERY}",
                                file=sys.stderr,
                            )
                    elif dropped % DROP_LOG_EVERY == 0:
                        print(
                            f"! {dropped} malformed messages dropped so far "
                            f"(most recent topic: {message.topic}) — is another "
                            f"publisher using this broker?",
                            file=sys.stderr,
                        )
                    continue
                latency_ms = (received_at - envelope.timestamp).total_seconds() * 1000.0
                acc.add(latency_ms)
                await batcher.add(envelope, received_at, latency_ms)
    finally:
        stop.set()
        batcher._trigger.set()  # wake the flusher so it exits promptly
        await flusher
        await batcher.flush()  # drain anything still buffered
        await pool.close()
        if dropped:
            print(f"\n! {dropped} malformed messages dropped in total", file=sys.stderr)
        print("\nlatency summary (ms):", json.dumps(acc.summary(), indent=2))


if __name__ == "__main__":
    # See smoke.py: Windows needs the Selector loop for paho-mqtt sockets.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
