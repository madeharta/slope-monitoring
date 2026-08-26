# Benchmarking streaming architectures for IoT-based slope monitoring (landslide mitigation).

This is an **infrastructure/systems engineering** study, not a machine learning study. The research question is comparative: *is a single streaming architecture sufficient across the realistic range of device counts and load patterns for slope monitoring, or do different scales require different architectures?*

- Project brief / full background: [`context.md`](./context.md)
- UI Figma Link: https://www.figma.com/design/jYqVApKqYT6ZhBpLiea0et/Design-System?node-id=9-2&t=HxsKa6xpchnZJgBl-1

## Environment variables:
```
# --- MQTT broker ---
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_QOS=1                     # sweep 0/1/2 in experiments

# --- Kafka  ---
KAFKA_BOOTSTRAP=localhost:9092
KAFKA_TOPIC=slope-data
KAFKA_PARTITIONS=1             # sweep 1/3/6 in experiments

# --- TimescaleDB / PostgreSQL ---
DB_HOST=localhost
DB_PORT=5432
DB_NAME=slope
DB_USER=slope
DB_PASSWORD=slope_dev  
SOURCE=kafka            

# --- Consumer: db-writer batching ---
BATCH_MAX_ROWS=500            # flush when the buffer reaches this many rows
BATCH_FLUSH_MS=1000           # ...or after this many ms, whichever comes first

# --- Load generator ---
LOADGEN_DEVICE_COUNT=100
LOADGEN_SEED=42                # deterministic runs
LOADGEN_MESSAGE_RATE_S=5       # seconds between messages per device

# --- Benchmark harness ---
BENCH_WARMUP_SECONDS=60
BENCH_DURATION_SECONDS=300
BENCH_RESULTS_DIR=bench/results

```

## Quick start

Each architecture variant starts with a single `docker compose up` and exposes
the same consumer interface, so the benchmark harness can target any variant
unmodified. Variant B (Prior) works:

```bash
python -m venv .venv && ./.venv/Scripts/python -m pip install -r requirements.txt -r consumers/api/requirements.txt

# 1. bring up the Variant-B stack (MQTT broker + Kafka + TimescaleDB)
cd infra/variant-b && docker compose up -d && cd ../..

# 2. start the consumer (MQTT -> Kafka -> TimescaleDB, batched)
$env:SOURCE="kafka"; python consumers/db-writer/writer.py

# 3. load generator
python loadgen/fleet.py

# Build Dashboard
cd frontend
npm install 
npm run build
cd ..

# 4. run dashboard API
$env:SOURCE="kafka"; python consumers/api/main.py
```