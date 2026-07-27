# MAGRIS

Benchmarking streaming architectures for IoT-based slope monitoring (landslide mitigation).

This is an **infrastructure/systems engineering** study, not a machine learning study. The research question is comparative: *is a single streaming architecture sufficient across the realistic range of device counts and load patterns for slope monitoring, or do different scales require different architectures?*

- Project brief / full background: [`context.md`](./context.md)

## Repository layout

Organized by role — all producers, the shared contract, the consumers, and
each swappable architecture variant have their own place.

```text
MAGRIS/
├── common/                 # shared wire contract (producer + consumer agree here)
│   ├── schema.py           #   envelope + measurements payload (pydantic)
│   ├── topics.py           #   MQTT topic scheme: slope/{site}/{device}/data
│   └── metrics.py          #   latency percentiles + per-hop timing
│
├── loadgen/                # device simulator (realism experiments) — the "test_data_dummy"
│   ├── config.py           #   sites (real clustered coords), device profiles, seeding
│   ├── smoke.py            #   1 device → 1 message (end-to-end proof) ✅ works
│   ├── metrics.py          #   re-exports common.metrics
│   └── manifest.py         #   writes seed + full config beside every run
│
├── consumers/              # everything that reads the stream
│   ├── db-writer/          #   MQTT → TimescaleDB, batched COPY ✅ works
│   └── api/                #   FastAPI: SSE + REST (live view)
│
├── infra/                  # one docker-compose stack per architecture variant
│   ├── variant-a/          #   MQTT only            ✅ runs (broker + TimescaleDB)
│   ├── variant-b/          #   MQTT → Connect → Kafka
│   └── variant-c/          #   MQTT broker w/ native Kafka bridge
│
├── firmware/               # device code (hardware not deployed yet)
│   ├── esp32/  ├── arduino-mkr/  └── rpi-gateway/   (edge gateway)
│
├── bench/                  # benchmark harness + metrics collection
├── dashboard/              # Grafana provisioning
├── docs/                   # experiment log + decisions/ (ADRs)
│
├── tests/                  # unit tests (schema, metrics) — 14 passing ✅
├── context.md              # full project brief
├── requirements.txt        # pydantic, aiomqtt, asyncpg (+ pytest)
└── pyproject.toml          # ruff + pytest config
```

> Correspondence to the prior work's repo: `loadgen` ↔ `test_data_dummy`,
> `consumers/db-writer` ↔ `kafka_consumer_db`, `consumers/api` ↔
> `streaming_server`, `infra/variant-b` ↔ `run_connector`, `firmware` ↔
> `kode_IoT_Arduino`. Everything else (variants A/C, `bench`, `common`) is new.

## Status

Foundation working: the Variant-A pipeline (loadgen → MQTT → batched db-writer →
TimescaleDB) is proven end-to-end with per-hop latency instrumentation. Real
sensor hardware is not deployed; all load is synthetic. Realism layers (rainfall
model, failure injection) and Kafka variants B/C are next.

## Quick start

Each architecture variant starts with a single `docker compose up` and exposes
the same consumer interface, so the benchmark harness can target any variant
unmodified. Variant A works today:

```bash
python -m venv .venv && ./.venv/Scripts/python -m pip install -r requirements.txt

# 1. bring up the Variant-A stack (MQTT broker + TimescaleDB)
cd infra/variant-a && docker compose up -d && cd ../..

# 2. start the consumer (MQTT -> TimescaleDB, batched)
python consumers/db-writer/writer.py

# 3. in another terminal, publish one reading end-to-end
python loadgen/smoke.py
```

Run the tests with `pytest`. Lint/format with `ruff check` / `ruff format`.
