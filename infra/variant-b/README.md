# infra/variant-b — MQTT → Kafka Connect → Kafka

`devices → MQTT broker → Kafka Connect (MqttSourceConnector) → Kafka → consumers`

The prior work's design, reproduced as the baseline for comparison. Same MQTT
front door as variant A, so devices and the load harness are **unchanged**;
Kafka Connect and Kafka are inserted between the broker and the consumer. Comes
up with a single `docker compose up` and exposes the same consumer interface as
every other variant — the db-writer just reads Kafka instead of MQTT, selected
by one env var.

Zookeeper is used here deliberately: this is the classic baseline. Variant D is
the same topology in KRaft mode (Zookeeper removed), so the cost of Zookeeper is
itself a measurable comparison.

## Stack

- **mosquitto** (`:1883`) — MQTT broker (identical config to variant A)
- **zookeeper** (`:2181`) — Kafka coordination
- **kafka** (`:9092` host / `29092` in-network) — broker
- **kafka-connect** (`:8083`) — Connect worker + Stream Reactor MQTT source connector (built from `./kafka-connect`)
- **connect-init** — one-shot; registers the connector, then exits
- **timescaledb** (`:5432`) — storage; schema auto-created from `init/001_schema.sql`

The MQTT Source Connector subscribes `slope/+/+/data` and writes every message
into the single Kafka topic **`slope-data`**. The payload is passed through as
raw bytes (`BytesConverter` + `ByteArrayConverter`), so the Kafka message value
is byte-for-byte the JSON envelope the device published — the consumer parses it
exactly as in variant A, and end-to-end latency stays comparable.

## Start / stop

```bash
docker compose up -d --build     # --build compiles the connector image the first time
docker compose ps
docker compose logs -f connect-init   # confirm "mqtt-source registered."
docker compose down              # stop (data kept in the tsdata volume)
docker compose down -v           # stop AND wipe data + schema
```

Then run the consumer against Kafka (on the host):

```bash
SOURCE=kafka python consumers/db-writer/writer.py
# Windows PowerShell:  $env:SOURCE="kafka"; python consumers/db-writer/writer.py
```

Point the load generator / benchmark at MQTT on `:1883` exactly as for variant A
— nothing about the publisher side changes.

## Verify the pipeline

```bash
# connector is RUNNING (not FAILED)
curl -s localhost:8083/connectors/mqtt-source/status

# messages are landing in Kafka
docker exec magris-variant-b-kafka-1 \
  kafka-console-consumer --bootstrap-server localhost:9092 \
  --topic slope-data --max-messages 3
```

Then the db-writer (`SOURCE=kafka`) should print `flushed N row(s)` and rows
appear in TimescaleDB, same as variant A.

## The consumer interface (why nothing else changes)

Both consumers are source-aware via `SOURCE=mqtt|kafka`, so the *whole*
dashboard flows through the variant's pipeline:

- `consumers/db-writer/writer.py` — the parse → latency-stamp → batch → COPY path
  is shared (`Ingest.handle`); only the transport differs.
- `consumers/api/stream.py` — the live SSE tail reads the same source. With
  `SOURCE=kafka` it runs an `aiokafka` consumer on the API event loop, so the
  real-time overlay also traverses Kafka (not just the DB-backed panels).

Run the API with the same env as the writer:

```bash
SOURCE=kafka python consumers/api/main.py
# Windows PowerShell:  $env:SOURCE="kafka"; python consumers/api/main.py
```

Leave `SOURCE` unset (or `mqtt`) and the live tail reads MQTT directly, which is
also valid — the broker is present in every variant.

## Per-hop instrumentation (context.md §4 — attribute latency, don't guess)

Variant B adds two hops over variant A. Measure each:

1. **ingress MQTT** — broker receive (device publish → broker).
2. **egress Connect / ingress Kafka** — the connector's produce. Read Connect
   metrics (`source-record-poll-rate`, `source-record-write-rate`) via JMX, and
   compare the Kafka message timestamp against the envelope `timestamp`.
3. **consumer receipt** — `received_at` stamped in the db-writer (already
   recorded per row as `latency_ms`).

Report p50/p95/p99 + max per hop, never just the mean.

## Known caveat — connector version

`kafka-connect/Dockerfile` downloads the Stream Reactor MQTT connector at build
time (`SR_VERSION`, default `8.1.30`). If the build fails on the download step,
the release asset name changed — check
<https://github.com/lensesio/stream-reactor/releases> and bump `SR_VERSION`
(or override the asset name):

```bash
docker compose build --build-arg SR_VERSION=<ver> kafka-connect
```

The connector's config keys in `connectors/mqtt-source.json` are stable across
8.x. If you must fall back to Confluent's `io.confluent.connect.mqtt` connector
instead, note it is under the Confluent evaluation licence — acceptable for a
one-off run, a licensing risk for repeated benchmarking.

## Not yet validated live

The stack is written and pinned but has not been brought up on this machine
(Docker was not running at authoring time). The one thing to confirm on first
`up --build` is the connector download; everything downstream (converters,
topic, consumer) follows the tested variant-A path.
