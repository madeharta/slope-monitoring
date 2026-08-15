# Project context: IoT streaming architecture benchmark for slope monitoring

This document gives an AI coding agent the background needed to work on this
project. Read it fully before proposing designs or writing code.

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
latency characteristics, only payload size and shape do.

> **Revised 2026-08-06.** This section originally added "(and those are
> simulated faithfully)". Contact with an operational deployment showed that
> claim does not hold unqualified: the load generator's *pattern* is steady
> where the field is burst-driven, and its payload may be orders of magnitude
> too small. The justification for synthetic load still stands; the assertion
> that the current implementation already satisfies it does not. See **§14**.

### In scope now

- Streaming pipeline implementation (multiple architecture variants)
- A load generator that realistically simulates many heterogeneous devices
- Per-hop and end-to-end latency instrumentation
- Throughput, CPU, memory, network measurement
- Failure and recovery scenarios
- A payload schema that supports heterogeneous sensors and microcontrollers
- A working monitoring dashboard UI — a graded deliverable, not just a
  debugging aid. It must render correctly from synthetic data in this phase.

### Explicitly NOT in scope now

- Machine learning models, prediction accuracy, model training
- Factor of Safety computation or geotechnical modelling
- Real sensor firmware deployed in the field
- Alert threshold tuning against real landslide events

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

**Feasibility risk — verify before committing effort.** A *native* Kafka bridge
is generally not an open-source-edition feature; EMQX and HiveMQ both place it
in their commercial editions, with trials available. Licensing terms change
between versions, so confirm against the documentation for the exact version to
be pinned before building. If it turns out to be unobtainable, C is dropped and
that is reported as a limitation — a documented constraint, not a failure. The
same check applies to the `MqttSourceConnector` used by B.

### Optional variant D — Kafka in KRaft mode

Any of B or C with Zookeeper eliminated.

### Why three variants and not two

Each variant plays a distinct role: **A is the null hypothesis** (the simplest
thing that could work), **B is the incumbent** (the prior work's design, the
thing being re-measured), and **C is the positive proposal** (what this project
suggests instead). Without C the thesis is purely critical — it dismantles the
prior answer without offering one.

The stronger justification is methodological. §9 requires sweeping **one
variable at a time**, and with only A and B that requirement is violated:

| Pair | What differs | Variables |
|---|---|---|
| A vs B | Kafka **and** Kafka Connect | **two** |
| A vs C | Kafka only | one |
| B vs C | Kafka Connect only | one |

With A and B alone, a measured difference confounds the cost of Kafka with the
cost of Kafka Connect, and neither can be attributed. **C is what makes the
comparison single-variable**, so it is a requirement of the design rather than
an optional third data point.

**The confound in C, stated plainly.** C does not change only one thing relative
to B: it removes Kafka Connect *and* replaces the broker (Mosquitto → EMQX). So
"B vs C isolates Kafka Connect" is not true as written. If C measures faster,
the cause could be the removed hop or simply a different broker implementation.

Close it with one control run — **topology A running on EMQX instead of
Mosquitto**:

```
A-Mosquitto  vs  A-EMQX   ->  the broker effect
A-EMQX       vs  C        ->  the Kafka Connect effect, attributable
```

One extra run buys the attribution. If it is not run, the claim must be weakened
to "C is lower-latency overall" with no stated cause, and this confound recorded
under Limitations. Raise it in the methodology chapter rather than waiting for an
examiner to find it.

**Do not claim C answers the prior work's future work.** Their stated
limitations (§3) list fault tolerance, partition count, device-side network, ML
practice, kriging, and UI/UX — **Kafka Connect is not among them**. Partition
count is the one that legitimately connects to B and C.

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

### Reference device profile — MPU6050 tiltmeter (confirmed hardware)

The MPU6050 is confirmed as one of the sensors for this project. Use it as the
concrete worked example throughout — it is a good demonstration of why the
envelope schema is necessary.

**What it actually contributes.** The MPU6050 is a 6-axis IMU (accelerometer +
gyroscope). Only the **accelerometer** is useful here, used as a tiltmeter: it
senses the gravity vector direction, and changes in that direction are converted
to inclination. The gyroscope measures angular *rate* with a drifting bias, and
slope movement is far too slow to register before drift swamps it. **Do not
implement sensor fusion, complementary filters, or Kalman filters** — those
exist for fast-moving platforms, not creeping hillsides.

**Readings emitted per report** — this is the key point for schema design. One
physical device produces multiple measurements:

| quantity | unit | note |
|---|---|---|
| `tilt_x` | `deg` | derived from accelerometer |
| `tilt_y` | `deg` | derived from accelerometer |
| `board_temp` | `degC` | on-chip sensor — **mandatory, see below** |
| `accel_x/y/z` | `g` | optional raw, for diagnostics |

The prior work's flat seven-field JSON cannot express this. The `readings` array
in §6 handles it directly. Use this device as the example when writing up the
heterogeneity contribution.

**Temperature compensation is mandatory, not optional.** The MPU6050's zero-g
offset drifts with temperature, and the datasheet spec is loose. A daily 10–20 °C
swing in the field can produce **apparent tilt changes comparable to or larger
than real slope movement** — raw tilt plotted over a week shows a daily
sinusoid tracking the day/night cycle, not ground movement. The on-chip
temperature sensor is free to read; ship it alongside every tilt reading and
compensate downstream. Without it the tilt data is not trustworthy.

**Sampling vs reporting.** Configure accelerometer range to ±2g for maximum
sensitivity, enable the digital low-pass filter at its lowest bandwidth, and
average aggressively on-device — e.g. 1000 samples reduced to one reported value
every 10 minutes. Slopes do not move fast, so this is affordable. Note the
contrast with an event-driven rain gauge: two very different sampling patterns
coexisting in one system is exactly the heterogeneity this project claims.

**Report tilt as delta from an installation baseline**, not as an absolute
value. Record the initial orientation at install time in the `sensors` table.

**Realistic capability — state this in the limitations chapter.** After
aggressive averaging and temperature compensation, practical resolution is
roughly **0.05–0.1°**. Commercial geotechnical tiltmeters reach ~0.001° or
better — one to two orders of magnitude finer. So:

- Detectable: late-stage acceleration in the hours before failure — which is the
  most decision-relevant signal for early warning
- Not detectable: millimetre-scale creep over weeks

Frame this explicitly as designed for low-cost late-stage precursor detection,
not precision geotechnical monitoring. A stated limitation is stronger than an
overclaim.

**Mounting matters more than the sensor.** Deep-set steel rod, not
surface-mounted. If the post itself sways, no sensor quality compensates. This
is out of scope for the current phase but should be noted in the design.

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

  **Tilt specifically** (MPU6050, see §6) must be modelled as three components
  summed: a near-flat baseline; a **small daily oscillation correlated with the
  temperature series**, reproducing thermal zero-g drift; and slow real movement
  that appears only last, after moisture has risen and suction has fallen. The
  daily wobble is what real MPU6050 data actually looks like — including it is
  what makes the synthetic series credible rather than obviously generated.
  Emit `board_temp` alongside tilt so the compensation path can be exercised
  end to end.

  **Tertiary creep is mandatory.** At least one scenario must include a slope
  that enters accelerating creep — tilt rate rising roughly exponentially over
  the final hours — and then fails. Without it the inverse-velocity panel
  (§10.5) has nothing to fit and cannot be demonstrated. Record the true failure
  time in the scenario manifest so predicted-versus-actual lead time can be
  evaluated.

  **Multiple depths per slope.** Moisture and suction must be emitted at several
  `depth_cm` values with progressively longer lag at greater depth, so the
  wetting front visibly propagates downward. A single moisture value per slope
  makes the depth-profile panel meaningless.

  **Multi-day rainfall history.** Scenarios must span enough days for 3-, 7-,
  and 15-day antecedent rainfall to be computable, and should include both a
  storm on dry ground and a comparable storm on already-wet ground.
- *Device layer.* Different sampling rates, units, and sensor counts per device
  type. This is what exercises schema flexibility.
- *Failure layer.* Dropouts, stuck values, NaN, clock skew, duplicate messages,
  out-of-order arrival, devices going offline and reconnecting. A monitoring
  dashboard's real job is surfacing these, not drawing smooth lines.

  **Store-and-forward replay is a distinct scenario and must be implemented
  separately** (added 2026-08-06, see §14). A reconnect resumes live traffic; a
  replay delivers hours of buffered readings at maximum rate when a link
  returns. Real nodes buffer to local storage during an outage and auto-sync
  afterwards, which makes replay — not steady state — the moment of peak load.

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
| **Message pattern** | Steady, bursty, **post-outage replay** | **Primary axis** (raised 2026-08-06, §14). Real deployments are near-idle between 15-minute bursts; the peak is a replay of buffered data after a link outage, not steady traffic |
| **Payload size** | 1 / 10 / 100 / 900 readings per message | **Added 2026-08-06, §14.** A batched burst may be two to three orders of magnitude larger than the single-reading message currently benchmarked. Size, not format, is the dominant payload effect |
| Device count | Sweep until saturation, beyond 1000 | Prior work never found the limit. Note this axis measures *concurrent publishing sessions*, which equals node count only on a direct-IP path — gateway-mediated transports collapse many nodes into one session (§14) |
| MQTT QoS | 0, 1, 2 | Never examined in prior work; latency vs delivery guarantee trade-off matters when losing a landslide alert is costly |
| Kafka partitions | 1, 3, 6 | Prior work used 1 and flagged this as future work |
| Payload format | JSON vs Protobuf/Avro | Heterogeneous envelope is larger than a flat 7-field record |
| Failure injection | Kill/restart Connect, broker, consumer — **during a replay burst** | Prior work listed this as a limitation. Timing matters: where nodes buffer locally, an outage loses nothing, so injecting during steady traffic measures the wrong moment (§14) |

Do not run the full cross-product — that explodes into hundreds of runs. Pick a
baseline configuration, sweep one variable at a time, and only cross variables
where interaction is expected.

---

## 10. Dashboard

The dashboard is a **deliverable in this phase** and must work end to end on
synthetic data. Real sensors are not required for it to be considered complete.

### 10.1 Split the two audiences

- **Grafana — benchmark and infrastructure metrics.** Consumer lag, message
  rate, per-hop latency percentiles, broker CPU/memory. Provisioned as config;
  supports the benchmark work only.
- **Custom FastAPI + React (Vite) frontend — the slope monitoring dashboard.**
  This is the graded artefact. Do not try to make Grafana do this job.

### 10.2 This is a monitoring console, not a GIS dashboard

The primary analytical axis is **time**, not space. There are only ~6–20 fixed
sensor locations, and they never move. Consequences:

- Do **not** install PostGIS, GeoServer, or any heavy GIS stack. Leaflet with
  plain markers is sufficient for every mapping need in this phase.
- Optimise the database for time-range queries (TimescaleDB hypertables), not
  spatial indexes.
- The map is a navigation aid, not the centrepiece. It must not dominate the
  screen.
- Build the time-series views first; the map last.
- Design references are ISA-101 (HMI design), EEMUA 191 / ISA-18.2 (alarm
  management), and Indonesia's LEWS conventions (BNPB / GAMA-EWS) — not GIS
  literature.

### 10.3 Screen hierarchy — three separate routes

These are three distinct screens; only one renders at a time. They are NOT
merged into a single scrolling page.

| Route | Screen | Data loaded |
|---|---|---|
| `/` | Level 1 — site overview | latest status per slope only (light query) |
| `/sites/{site_id}` | Level 2 — slope detail | time series for that slope (heavy query) |
| `/sites/{site_id}/sensors/{device_id}` | Level 3 — sensor detail | raw readings, calibration metadata |

Use React Router. Row click calls `navigate('/sites/{id}')`; back button calls
`navigate(-1)`. URLs must be bookmarkable and shareable so a specific screen can
be sent to someone directly.

Rationale for splitting rather than merging: with 20 slopes, a merged page would
render ~40 panels and become unreadable, and it would trigger the heavy Level 2
query once per slope on every page load.

**Exception — the alarm summary bar does not change between screens.** It lives
in the parent layout component that wraps all routes, so an alarm on slope A
stays visible while the operator is looking at slope C.

### 10.4 Level 1 — site overview

Purpose: the always-on screen. Answers "is anything wrong right now, and where".

Contents, in priority order:

1. **Alarm summary bar** (shared component, pinned). Counts of active Bahaya,
   active Siaga, unacknowledged alarms, and current alarm rate per 10 minutes.
   The alarm rate is displayed because it is measured against the EEMUA 191
   benchmark — see §10.7.
2. **Slope status list.** One row per slope, sorted by severity descending.
   Each row: status label, slope name, the required action sentence for that
   status, and the single most relevant current reading.
3. **Site map.** Markers coloured by status. Click navigates to Level 2. One
   panel among several — not full width.
4. **Device health summary.** Counts of online, offline, low battery, and
   detected data gaps. Clicking a count filters the list.

### 10.5 Level 2 — slope detail

Purpose: answers "what is happening on this slope, how fast, and how long until
it fails".

**Header** with breadcrumb back to Level 1, slope name, current status badge, and
the selected time window.

Panels are listed in build priority. Build the first three before any of the
rest — together they answer *what is happening*, *when will it fail*, and *how
deep has the water reached*.

#### Priority 1 — combined time series (the primary panel)

Rainfall and all sensor series share a **single time axis**. Rainfall renders as
bars (hydrological convention is an inverted hyetograph hanging from the top;
either orientation is acceptable, inverted is easier to distinguish from the
lines); moisture / suction / tilt render as lines. The shared axis is the entire
point — it is what makes the causal sequence readable: rain peaks, suction
falls, tilt moves last. Do not split these into separate charts.

**Threshold bands** drawn as shaded regions behind the series, not thin lines,
so "inside the zone" is readable at a glance. Stack a second band where a Bahaya
threshold also applies.

#### Priority 2 — inverse velocity (failure time estimate)

Plot `1 / (rate of change of tilt)` against time. Based on Saito (1965) and
Fukuzono (1985): inverse velocity trends toward zero as failure approaches, so
a linear fit extrapolated to the time axis estimates the time of failure. This
is the most widely used phenomenological failure-prediction method and is
applied operationally in open-pit mining.

Why it matters here: it produces a **lead time in hours**, not just a status
label. "Siaga" is a category; "estimated failure in ~3 hours" is an evacuation
decision. It also fits the MPU6050's capability — the method targets tertiary
creep (late-stage acceleration), which is exactly the regime a 0.05–0.1°
tiltmeter can resolve (see §6).

Implementation requirements:
- Smooth the displacement/tilt series before differentiating — raw noise is
  amplified badly in `1/v` and makes the fit meaningless. Moving average or
  equivalent data-extraction filtering is mandatory, not optional.
- Fit only over data **after the onset of acceleration**, never the full history.
- Render the fit as a dashed extrapolation to the x-axis, and label the
  zero-crossing as an estimated failure time with an explicit uncertainty band.
- Suppress the whole panel when the slope is not accelerating. A failure-time
  estimate on a stable slope is noise being read as signal.

#### Priority 3 — depth profile

Depth on the vertical axis, moisture or suction on the horizontal, one line per
timestamp with a time scrubber. Shows the **wetting front** propagating
downward. This is what makes `depth_cm` genuinely useful rather than a database
column.

#### Priority 4 — rainfall intensity–duration threshold

Log-log scatter: storm duration on x, intensity on y, one point for the current
storm, plotted against a published landslide-triggering threshold curve. Answers
whether current rainfall has crossed a level historically associated with
failures. Standard practice in landslide early warning; needs only the rain
gauge.

#### Priority 5 — antecedent cumulative rainfall

Daily rainfall bars overlaid with 3-, 7-, and 15-day cumulative lines.
Landslide susceptibility depends heavily on prior wetness: 40 mm on
already-saturated ground is far more dangerous than 40 mm on dry ground. This
panel explains why two similar storms produce different outcomes.

#### Priority 6 — tilt trajectory (x vs y)

Scatter/path plot of `tilt_x` against `tilt_y` over time. Shows **direction** of
movement. A consistent downslope-oriented track indicates real ground movement;
a wandering or looping track indicates noise or thermal drift. A cheap
signal-versus-noise discriminator, available only because the MPU6050 provides
two axes.

#### Priority 7 — slope cross-section

Side view of the slope with sensors plotted at their `depth_cm`, coloured by
current status. Explains visually why a 30 cm sensor responds before a 100 cm
one. The 3D hex-terrain rendering explored during design work belongs here, not
on Level 1.

#### Always visible — data quality panel

Placed **beside the charts, not hidden in an admin page**: message rate,
detected gaps, stuck values, out-of-range counts. Whoever reads the chart needs
to know whether the chart can be trusted.

Also surface **response lag** as a single figure — the measured delay between
rainfall peak and suction response. It is a per-slope characteristic and a
proxy for hydraulic conductivity; a short lag means a narrower warning window.

#### Level 3 panels

No special design work needed: raw readings table, data quality history,
calibration and installation metadata. Two diagnostic charts belong here:

- **Raw vs temperature-compensated tilt**, with `board_temp` plotted alongside.
  Demonstrates that the MPU6050 thermal compensation (§6) actually works.
- **Soil water characteristic curve** — measured moisture against measured
  suction, plotted separately for wetting and drying periods to reveal the
  hysteresis loop. A genuine geotechnical curve derived from two sensors already
  installed, with no additional hardware.

### 10.6 Registry-driven — hard requirement

Every panel, row, series, and legend entry must be derived at runtime from the
`devices` / `sensors` tables and the distinct `quantity` values present in the
data. Specifically:

- Level 1 slope list comes from the sites/devices tables, not a literal array
- Level 2 series and legend come from `SELECT DISTINCT quantity` for that site
- Cross-section marker positions come from `depth_cm`
- Data quality rows come from the `quality_flag` values actually present

Only three things may be hardcoded: the layout grid, the colour mapping, and the
status-to-action-sentence mapping.

The prior work hardcoded `sensor1`–`sensor6` in a module-level dict (§4.3);
adding a sensor meant editing source. Do not repeat this.

**Acceptance test:** with the system already running, introduce a device
carrying a previously unseen sensor type. It must appear in the dashboard with
no redeploy and no code change. This demo is the primary evidence for the
project's "flexible IoT" claim — treat it as a first-class requirement.

### 10.7 Status model and alarm behaviour

Use the Indonesian LEWS nomenclature: **Normal / Siaga / Bahaya**. Do not invent
alternative labels — examiners are likely to recognise the BNPB convention.

Status is an instruction, not a decoration. Every status must render an
accompanying **action sentence** in the UI, not just a coloured badge. Example
mapping (wording to be confirmed with the supervisor):

- Normal — readings within safe limits, no action
- Siaga — check field conditions, prepare evacuation route
- Bahaya — evacuate, immediate field response

Threshold *tuning* against real events is out of scope. The threshold
*mechanism* is not, and it must include:

- **Hysteresis / deadband** on every threshold, so a sensor oscillating around a
  limit does not emit hundreds of alarms
- **Debouncing** — a threshold must be exceeded for a configured duration before
  the status changes
- **Chattering suppression** for alarms that rapidly toggle
- **Grouping of related alarms** rather than firing all of them at once
- **Acknowledgement state** per alarm, surfaced in the summary bar

Target benchmark, from EEMUA 191: on average no more than one alarm per ten
minutes in steady state, and fewer than ten alarms in the first ten minutes
after a major event. Instrument the alarm rate and display it so this can be
verified during evaluation.

### 10.8 Visual principle — colour encodes abnormality only

Base UI is neutral greyscale. Colour is reserved for Siaga and Bahaya states.
**Normal state must be rendered in neutral grey, not green.** If safe states are
also coloured, the eye habituates to colour and genuine alarms stop standing
out. This is the ISA-101 high-performance HMI principle and is a defensible
design decision, not a stylistic preference.

Detailed layout is deferred; the constraint above is the part that must not be
negotiated away.

**Theme: Cobalt Mono (shadcn/ui), dark mode.**
`https://21st.dev/@serafimcloud/themes/cobalt-mono`

Note on the name: despite "Cobalt", the primary/accent in this theme is a
**bright violet**, not cobalt blue. Earlier drafts of this document described it
as blue — that was wrong. Copy exact token values from the source; the summary
below is approximate.

| Token | Value |
|---|---|
| Background | near-black, ~`#09090b` |
| Card | very dark grey, slightly lifted from background |
| Primary / accent | bright violet |
| Secondary, Muted | very dark desaturated violet |
| Destructive | deep red |
| Border | dark grey, low contrast |
| Font | Inter |
| Border radius | 1.4rem — noticeably rounded, apply consistently |

Chosen deliberately, not stylistically: a monochrome base with a single accent
hue is the ISA-101 high-performance HMI principle expressed as a theme, and a
dark screen is standard practice for continuously-monitored consoles. State this
rationale in the report and cite ISA-101.

**Gap to fill: the theme has no amber.** It ships a destructive red usable for
Bahaya, but nothing for Siaga. Add a single amber that reads clearly on
near-black and register it as a theme token. Do not fall back to violet for
Siaga — violet is the UI accent and would collide.

**Reserved semantic colours — override the theme if it conflicts.**

| Role | Use | Allowed anywhere else |
|---|---|---|
| Violet (theme primary) | links, focus rings, active nav, selected rows | yes |
| Neutral grey | all normal-state data, all Normal status rows | yes |
| Amber (added) | Siaga status only | **no** |
| Red (theme destructive) | Bahaya status only | **no** |

shadcn/ui uses `destructive` for ordinary delete/danger buttons by default. In
this application red means Bahaya and nothing else — remap destructive buttons
to neutral or outline variants. Same rule for any amber the component library
introduces for generic warnings.

Also prohibited, regardless of what reference designs show: per-metric icon
colours on stat cards (colour that encodes nothing defeats the whole scheme),
glows, gradients, and drop shadows behind numeric readouts.

**Chart theming.** shadcn/ui exposes CSS custom properties; ECharts has its own
theme system and will not inherit them. Map the theme tokens into an ECharts
theme object once, at a single source of truth, and derive series colours from
the same semantic roles above. Otherwise the charts will look pasted in from a
different application.

**Map rendering.** Leaflet with CARTO `dark_matter` tiles (free, matches the
`#09090b` base), plus a satellite or terrain layer toggle — when a slope enters
Bahaya, the operator needs to see actual terrain, not a road map. Markers are
plain circles coloured by status.

Do **not** use hex-bin, choropleth, or any density-aggregation map style. Those
techniques exist to summarise hundreds or thousands of points; with ~6–20 fixed
sensors each cell would contain zero or one point, so the aggregation conveys
nothing. Working zoom level is site scale (a few hundred metres to a few km),
not global.

### 10.9 Two data paths

Live view streams from the broker/Kafka via SSE. Historical view queries
TimescaleDB. Both must work; do not implement one and stub the other.

**Use a single SSE connection for all devices, routed client-side by
`device_id`.** The prior work exposed `/chart-data/{sensor_id}`, requiring one
EventSource per sensor; browsers cap concurrent connections per origin at
roughly six on HTTP/1.1, so that design cannot scale past a handful of devices.

### 10.10 Frontend implementation notes

React (Vite) + ECharts, built to static files served by FastAPI — deployment
stays a single service. React is chosen specifically because dynamically
generated panels are a core requirement (§10.6); reconciling that by hand in
vanilla JS is where chart-lifecycle bugs accumulate.

- Manage ECharts instances explicitly: `echarts.init` in `useEffect`,
  `dispose()` in its cleanup, one shared `ResizeObserver`
- Update charts with `setOption` merge, never re-init
- Keep streaming data in a single store (Zustand or a reducer); do not hold it
  in per-chart `useState`, or every message re-renders the tree
- Use Leaflet with OpenStreetMap tiles for the map, not ECharts geo

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

---

## 14. Field contact and revisions

**2026-08-06 — briefing from the ITB IoT team.**

Everything in §1–§13 was written before any contact with a deployed system. This
section records what changed after the first such contact, and which earlier
statements it supersedes. Earlier text is **not** rewritten — the sequence of
what was assumed, what was checked, and what was revised is part of the thesis
argument.

Source notes: `slope-monitoring/raw/2026-08-06-itb-meeting.md`.

### The system described

An operational slope-monitoring installation on mine highwalls (PPA). Nodes in
IP67 enclosures carry a **GNSS ZED-F9P** dual-band receiver for surface creep
(10 mm + 1 ppm, up to 10 Hz) and **ADXL355 / MPU9025** accelerometers for
blast-induced vibration. A Base Station on stable ground with a choke-ring
antenna supplies RTK/PPK corrections.

Telemetry is three-tier: **4G primary** (report every 15 minutes carrying
1-second logs), **LoRa failover** through the Base Station, and **SD-card
buffering** with automatic burst replay when the link returns.

### What this changes

1. **Load pattern, not device count, is the axis that matters.** Normal
   operation is near-idle; the peak is a post-outage replay. §9 revised
   accordingly, and §7's failure layer gains replay as a distinct scenario.
2. **The synthetic-load justification needs qualifying.** §2's original claim
   that payload size and shape were "simulated faithfully" does not survive:
   the generator is steady where the field bursts, and its ~250-byte message may
   be far smaller than a batched burst. The *principle* is unaffected — only the
   claim that the current implementation already meets it.
3. **Payload size becomes a sweep variable in its own right** (§9). Previously
   only payload *format* was swept.
4. **Failure injection must happen during a replay burst** (§9). Because nodes
   buffer locally, a network outage loses nothing without help from the
   pipeline — so the durability advantage of a retained log narrows to one
   specific window: a *consumer* restart while a replay is in flight. That is a
   sharper and more measurable claim than the general argument in §5.
5. **The device-count axis needs a caveat.** On LoRa failover, nodes hold no IP
   session and the Base Station relays for all of them, so N nodes appear as one
   publisher. The axis measures concurrent sessions, not nodes. This does not
   weaken §4.1 — that is a rule about the *load generator*, and it stands.
6. **Latency must be reported per population.** Replayed records carry
   timestamps hours older than their receipt, so pooling replay and live traffic
   into one percentile produces a meaningless number. §8's percentile rule now
   requires stating which population and which hop a figure covers.

### What this confirms

- **The Raspberry Pi edge-gateway decision (§6).** The Base Station is exactly
  that shape. The choice predates contact with a deployment that uses one.
- **Narrow/long storage (§6).** GNSS displacement and vibration enter as new
  `quantity` values with no migration and no consumer change.
- **One client per device (§4.1).** Now also verified in measurement:
  `bench/BENCHMARK.md` records established connections equal to device count at
  every scale from 100 to 4000.
- **The measured throughput range is relevant.** The ITB team independently
  nominates 2,000–4,000 msg/s as the realistic extreme for replay, which
  brackets the ceiling reached by the Variant A sweep.

### Unresolved — resolve before sizing any replay experiment

- **"900 data per 1 detik" is ambiguous by a factor of 900.** It reads either as
  900 records per 15-minute cycle (1 Hz logging over 900 seconds, consistent
  with the same source's description of the 4G path) or as 900 records per
  second sustained. Under the first, a 20-node fleet drains a six-hour backlog
  in roughly four minutes at measured Variant A capacity; under the second the
  same fleet produces ~18,000 msg/s at rest. **These give opposite answers to
  the research question**, and no further benchmarking resolves it.
- **Batched or per-record?** Whether a burst is one large message or ~900 small
  ones. Broker cost differs completely.
- **Node count per site**, still unanchored.
- **Accelerometer sampling rate.** Bears on whether narrow/long storage suits
  high-rate waveform data, or whether triggered segments are needed alongside it.
- **The HTTP endpoint** mentioned alongside MQTT — if real, a second ingestion
  path outside every variant's contract.

### Scope

The described system lists AI/ML training for slope-stability prediction among
its purposes. That remains **out of scope** here (§2). The defensible position is
that this pipeline *supplies* clean, latency-characterised data for such work;
the modelling is a separate study.

### Status of this source

First-hand from the team that built the system, but delivered verbally and
summarised secondhand — no datasheets, no captured payloads, no timing traces.
Treat as **medium confidence**. Actual JSON samples, a burst timing capture, and
a node count would raise it.