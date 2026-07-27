# Project context: IoT streaming architecture benchmark for slope monitoring

This document gives the background needed to work on this project. Read it
fully before designing or writing code.

---

## 1. What this project is

An undergraduate final-year project (skripsi) building and **benchmarking** a
data streaming architecture for IoT-based slope monitoring, aimed at landslide
mitigation. The system ingests readings from geotechnical sensors deployed on
slopes, moves them to storage and a dashboard in near real time, and is
evaluated on latency, throughput, and resource usage.

**The core research question is comparative:**

> Is a single streaming architecture sufficient across the realistic range of
> device counts and load patterns for slope monitoring, or do different scales
> require different architectures?

This is deliberately an **infrastructure/systems engineering** study, not a
machine learning accuracy study. See §3 for why.

---

## 2. Current phase and scope

Real sensor hardware is **not yet deployed**. Field data will arrive later; the
system will be revised at that point.

For now, all load is **synthetic**. This is standard practice for infrastructure
benchmarking and is not a compromise — real payload contents do not change
latency characteristics, only payload size and shape do (and those are
simulated faithfully).

### In scope now

- Streaming pipeline implementation (multiple architecture variants)
- A load generator that realistically simulates many heterogeneous devices
- Per-hop and end-to-end latency instrumentation
- Throughput, CPU, memory, network measurement
- Failure and recovery scenarios
- A payload schema that supports heterogeneous sensors and microcontrollers
- A monitoring dashboard, primarily to validate the pipeline end to end

### Explicitly NOT in scope now

- Machine learning models, prediction accuracy, model training
- Factor of Safety computation or geotechnical modelling
- Real sensor firmware deployed in the field
- Alert threshold tuning against real landslide events
- UI/UX polish

Do not add ML components unless explicitly asked. The prior work (see §3) lost
credibility by overreaching into ML with insufficient data.

---

## 3. Prior work this builds on

A 2024 final-year thesis from Universitas Indonesia, Faculty of Computer
Science, by Mochammad Agus Yahya and Zefanya Soplantila, titled *"Development
of a Real-Time Soil Moisture Monitoring System with Integration of Streaming
Data and Machine Learning Models to Support Prefailure Inspection on Slope
Stability."*

Two public repositories accompany it:

- `https://github.com/agusyahya23/IoT_Streaming` — Arduino firmware, Docker
  Compose for the streaming stack, Kafka Connect config, DB consumer, load test
- `https://github.com/Soplanz/interface-soil-project` — FastAPI web interface,
  ML notebook, pickled models, CSV datasets

### Their architecture

```
Arduino MKR WiFi 1010          (RK-520 soil moisture/temp sensor,
  |                             Keller pressure sensor for suction,
  |                             both over Modbus RS-485)
  v
Mosquitto MQTT broker          (GCP e2-micro, topic: sensor_mqtt)
  |
  v
Kafka Connect                  (GCP e2-medium, MqttSourceConnector)
  |
  v
Kafka broker + Zookeeper       (e2-medium + e2-micro, topic: sensor_data,
  |                             1 partition, replication factor 1)
  |
  +--> Consumer A (group 2) --> PostgreSQL on CloudSQL   [historical storage]
  +--> Consumer B (group 3) --> FastAPI + SSE --> browser [live charts]
```

The web server reads from Kafka directly rather than querying the database, to
keep the live view real time. Two consumers use different `GROUP_ID` values so
both receive every message.

### Their payload

Flat JSON, seven fields:
`sensor_id`, `timestamp`, `latitude`, `longitude`, `moisture`, `pressure`,
`temperature`

### Their reported results

Load test: 10 GCP VMs, each simulating 100 sensors, 1 minute, 5-second message
rate, sensor count swept from 100 to 1000.

| Metric | 100 sensors | 1000 sensors |
|---|---|---|
| Mean latency to DB | 338 ms | 1364 ms |
| Mean latency to web | 696 ms | 1404 ms |
| Throughput | ~5 KB/s | ~50 KB/s |

CPU stayed under 10% on MQTT, ~4–5% on Kafka, under 5% on Kafka Connect.
Headline claim: 500 sensors at under 1 second latency.

### Their stated limitations (verbatim from the thesis)

- Fault tolerance not evaluated
- Partition count and broker count held static, not varied
- Network from the IoT device itself not included in measurement
- ML best practices and model optimisation were not a focus
- Kriging interpolation could not be evaluated due to insufficient sensors
- UI/UX was not a focus

---

## 4. Known defects in the prior work — do not replicate these

These were found by reading the repositories directly. They matter because
this project may reuse parts of that code.

### 4.1 The load generator does not simulate multiple devices

In `test_data_dummy/test-concurrent.py`, a single `mqtt.Client()` is created at
module level, connected once, and then **every** worker thread calls
`client.publish()` on that same shared object.

So "1000 sensors" is actually one TCP connection, one client ID, one MQTT
session sending 1000x more messages. It does not exercise connection handling,
session state, keepalive traffic, or socket limits on the broker — which is the
dominant load for an MQTT broker. This is why their broker CPU stayed under
10%, and it invalidates their conclusion that MQTT handled the load
efficiently.

**Requirement for this project: one MQTT client instance with a unique client
ID per simulated device.**

Secondary issue: `ThreadPoolExecutor(max_workers=2000)` with Python threads and
`time.sleep()` means GIL contention likely made the actual publish rate differ
from the configured rate.

### 4.2 Measurement gaps

- Only mean/min/max latency reported. No percentiles. For an early warning
  system p95/p99 matter more than the mean; their max of 4281 ms signals a long
  tail they never investigated.
- Only end-to-end latency measured, so when latency rose they could only
  speculate about the cause ("possibly network load").
- Publishers ran on 10 separate VMs, so clock skew between publisher timestamps
  and consumer receipt time directly contaminates the latency figures. No NTP
  synchronisation is mentioned.
- 1-minute runs with no warm-up period. Kafka and Kafka Connect are JVM
  services still JIT-warming during the first minute.
- The sweep stopped at 1000 sensors while all components were still healthy
  under 10% CPU, so no saturation point was ever found. The "500 sensors" figure
  is simply where the curve crossed 1 second, not a capacity limit.

### 4.3 Application code bugs

- `interface-soil-project/app/main.py`: `data_store` is a hardcoded dict of
  `sensor1`–`sensor6`. Adding a sensor requires editing source.
- Same file: `process_data()` does `insert(0, data)` and never pops. The
  function containing the pop logic, `process_data_for_sensor()`, is never
  called. Unbounded memory growth.
- Same file: models are `pickle.load()`ed on every request instead of once at
  startup.
- `app/utils.py`: `kriging_calculation()` hardcodes six coordinates as list
  literals, and calls `OrdinaryKriging(list_latitude, list_longitude, ...)`.
  PyKrige expects `(x, y)` = `(lon, lat)`, so the axes are swapped.
- `ML_Development.ipynb` cell 44: `model_suction = model` and
  `model_moisture = model` bind the same estimator object, so both pickled
  models come from whichever fit ran last. The two "separate" models are not
  independent.

### 4.4 Security

Credentials are committed to both repositories — WiFi password, a Google API
key, and a Blynk auth token in `main.cpp`, and a PostgreSQL password in a
committed `.env`. **Never reuse any of these values, and never commit secrets
in this project.** Use environment variables loaded from an untracked `.env`,
with a checked-in `.env.example` documenting the required keys.

### 4.5 Stack age

Their stack is from 2018: `cp-kafka 5.1.0`, `eclipse-mosquitto 1.5.5`,
`zookeeper 3.4.9`. Modern Kafka supports **KRaft mode**, which removes
Zookeeper entirely. Prefer current versions; dropping Zookeeper is itself one
of the architectural variants worth measuring.

---

## 5. Architecture variants to build and compare

The point of the project is comparison, so the pipeline must be swappable via
configuration rather than hardcoded.

### Variant A — MQTT only, no Kafka

```
devices --> MQTT broker --> consumer --> {database, dashboard}
```

The simplest thing that could work. Realistic slope monitoring deployments may
only have tens of nodes per site, where Kafka's overhead may not be justified.
If A holds up to some N, that is a useful finding, not a negative result.

### Variant B — MQTT to Kafka via Kafka Connect

The prior work's design, reproduced as the baseline for comparison.

### Variant C — MQTT broker with a native Kafka bridge

```
devices --> EMQX/HiveMQ (built-in Kafka bridge) --> Kafka --> consumers
```

Removes Kafka Connect entirely: one fewer service, one fewer hop, one fewer VM.

### Optional variant D — Kafka in KRaft mode

Any of B or C with Zookeeper eliminated.

---

## 6. Payload schema — heterogeneous devices

The project must support multiple sensor types (tilt, piezometer, rain gauge,
soil moisture, pore pressure) and multiple microcontroller families (ESP32,
Arduino MKR, Raspberry Pi). The prior work's flat seven-field JSON cannot
express this: a rain gauge has no moisture field, a tilt sensor emits two axes,
a piezometer may sit at three depths at one location.

Separate the **envelope** from the **measurements**:

```json
{
  "device_id": "esp32-slope-a-01",
  "device_type": "esp32",
  "site_id": "lereng-a",
  "timestamp": "2026-07-27T09:15:00+07:00",
  "location": { "lat": -6.3643, "lon": 106.8290 },
  "readings": [
    { "quantity": "soil_moisture",  "value": 32.4, "unit": "pct",  "depth_cm": 30 },
    { "quantity": "pore_pressure",  "value": -18.2, "unit": "kPa", "depth_cm": 60 },
    { "quantity": "tilt_x",         "value": 0.31,  "unit": "deg" }
  ]
}
```

### Storage shape

Store **narrow/long**, not wide: one row per measurement.

```
(time, device_id, site_id, quantity, value, unit, depth_cm, quality_flag)
```

Adding a new sensor type then requires no schema migration and no consumer code
change. Device and sensor metadata live in small `devices` and `sensors`
tables — this replaces the prior work's hardcoded `data_store` dict.

Consider **TimescaleDB** (a PostgreSQL extension, not a separate database).
Hypertables and continuous aggregates make dashboard time-series queries much
cheaper, and migration cost is near zero since it remains ordinary SQL.

### MQTT topic structure

```
slope/{site_id}/{device_id}/data
```

Consumers subscribe with `slope/+/+/data`, so adding a device requires no
server-side change.

### Device contract

Firmware differs per platform; output must be identical. Three implementations:
ESP32 (PubSubClient or ESP-MQTT), Arduino MKR (WiFiNINA + PubSubClient, can be
adapted from the prior work's `main.cpp`), Raspberry Pi (paho-mqtt in Python).

Give the Raspberry Pi a distinct role as an **edge gateway** — collecting
serial/LoRa sensors and forwarding to MQTT — rather than a third identical
publisher. That is realistic for remote slopes and demonstrates genuinely
different device capabilities.

---

## 7. Load generator requirements

Treat this as a first-class component, not a throwaway script.

**Hard requirements:**

1. One MQTT client with a unique client ID per simulated device. See §4.1.
2. Configurable device count, sensor mix per device, message rate, QoS.
3. Deterministic seeding so runs are reproducible.
4. Timestamps embedded in the payload for latency measurement.

**Prefer a mature tool over writing from scratch** — `emqtt-bench`,
`mqtt-stresser`, or k6 with its MQTT extension. These handle per-device
connections and percentile reporting correctly. Write custom code only for the
payload-shape logic that those tools cannot express.

**Three layers of realism:**

- *Physical layer.* Generate rainfall first (storm events with intensity and
  duration), then derive sensor responses from it with lag: moisture rises tens
  of minutes after rain begins, pore pressure follows more slowly, tilt moves
  last and only under extreme conditions. A lagged exponential response model is
  sufficient — a full Richards equation is not needed.
- *Device layer.* Different sampling rates, units, and sensor counts per device
  type. This is what exercises schema flexibility.
- *Failure layer.* Dropouts, stuck values, NaN, clock skew, duplicate messages,
  out-of-order arrival, devices going offline and reconnecting. A monitoring
  dashboard's real job is surfacing these, not drawing smooth lines.

Do not use the prior work's approach of `random.uniform(-90, 90)` for latitude —
that scatters sensors across the entire globe and makes any spatial view
meaningless.

---

## 8. Measurement methodology

**Report percentiles**: p50, p95, p99, plus max. Not just the mean.

**Instrument every hop.** Stamp the message on ingress to MQTT, on egress from
the bridge/Connect, on ingress to Kafka, and on receipt at the consumer. This
turns "latency increased, possibly network" into a specific attribution.

**Control clock skew.** Run `chrony`/NTP and report the measured offset. Where
possible, measure with a single clock.

**Warm up.** Discard the first 30–60 seconds. Run for at least 5 minutes.

**Find the saturation point.** Keep increasing load until something actually
breaks — queue depth grows without bound, messages are dropped, or latency goes
non-linear. A curve that stays flat means the test was too easy.

**Metrics to collect:** latency percentiles per hop and end to end, throughput
in messages/sec *and* bytes/sec, CPU, memory, network I/O, message loss rate,
consumer lag, and recovery time after induced failure.

---

## 9. Experiment variables

| Variable | Values to sweep | Why it matters |
|---|---|---|
| Architecture | A, B, C (and optionally D) | The central research question |
| Device count | Sweep until saturation, beyond 1000 | Prior work never found the limit |
| MQTT QoS | 0, 1, 2 | Never examined in prior work; latency vs delivery guarantee trade-off matters when losing a landslide alert is costly |
| Kafka partitions | 1, 3, 6 | Prior work used 1 and flagged this as future work |
| Payload format | JSON vs Protobuf/Avro | Heterogeneous envelope is larger than a flat 7-field record |
| Message pattern | Steady vs bursty | Rain gauges tip irregularly; during heavy rain all nodes report faster at once |
| Failure injection | Kill/restart Connect, broker, consumer | Prior work listed this as a limitation |

Do not run the full cross-product — that explodes into hundreds of runs. Pick a
baseline configuration, sweep one variable at a time, and only cross variables
where interaction is expected.

---

## 10. Dashboard

Its purpose here is **validating the pipeline**, not being a product.

Useful panels: site map with per-device health (last seen, battery, RSSI);
combined time series with rainfall as bars and moisture/suction/tilt as lines on
a shared axis (this is the standard plot in landslide early-warning literature,
because cause and effect read directly off it); data quality panel showing
message rate, gap detection, out-of-range counts; and simple static thresholds
per sensor.

**Use Grafana** for operational and health panels — free, connects straight to
TimescaleDB, saves weeks. Build custom FastAPI views only for domain-specific
displays. The prior work built everything by hand and then conceded the
interface was not a research focus.

---

## 11. Suggested repository layout

```
/firmware
  /esp32            # PlatformIO project
  /arduino-mkr      # PlatformIO project
  /rpi-gateway      # Python edge gateway
/infra
  /variant-a        # docker-compose: MQTT only
  /variant-b        # docker-compose: MQTT + Connect + Kafka
  /variant-c        # docker-compose: EMQX bridge + Kafka
/loadgen            # device simulator + physical/failure layers
/consumers
  /db-writer        # Kafka/MQTT -> TimescaleDB
  /api              # FastAPI: SSE + REST
/bench              # harness, metrics collection, analysis notebooks
/dashboard          # Grafana provisioning + custom views
/docs               # architecture decisions, experiment log
```

---

## 12. Conventions

- Python 3.11+. Type hints on public functions. `ruff` for linting.
- Async consumers via `aiokafka` / `asyncio-mqtt`; do not mix blocking DB calls
  into async paths.
- All configuration through environment variables; `.env` untracked,
  `.env.example` committed.
- Every architecture variant must be startable with a single
  `docker compose up` and must expose the same consumer interface, so the
  benchmark harness can target any variant without modification.
- Log benchmark runs to structured files (JSON lines or Parquet) with the full
  configuration recorded alongside the results, so any run is reproducible.
- Pin container image versions explicitly; do not use `:latest`.

---

## 13. Domain glossary

- **Slope monitoring** — instrumenting a hillside to detect conditions
  preceding failure.
- **Prefailure inspection** — observing and analysing conditions before a
  failure occurs, so preventive action is possible.
- **Soil moisture** — water content of the soil, percent by volume.
- **Soil suction / matric suction** — negative pore water pressure in
  unsaturated soil. Higher suction means more apparent cohesion and a more
  stable slope. Rainfall infiltration reduces suction, which is the primary
  mechanism of rainfall-induced landslides.
- **Pore water pressure** — water pressure in soil voids; rises as soil
  saturates, reducing effective stress and shear strength.
- **Piezometer** — instrument measuring pore water pressure or groundwater
  level.
- **Inclinometer / tilt sensor** — measures ground displacement or rotation;
  movement typically appears late in the failure sequence.
- **Factor of Safety (FoS)** — ratio of resisting to driving forces on a slope.
  Below 1.0 indicates failure. Out of scope for this phase, but the eventual
  target output.
