# loadgen — device simulator

First-class component, not a throwaway script.

**Hard requirements:**
1. One MQTT client with a **unique client ID per simulated device** (the prior work's #1 defect — see `context.md` §4.1).
2. Configurable device count, sensor mix per device, message rate, QoS.
3. Deterministic seeding so runs are reproducible.
4. Timestamps embedded in the payload for latency measurement.

**Prefer a mature tool** (`emqtt-bench`, `mqtt-stresser`, or k6 MQTT extension) for connection handling + percentile reporting. Write custom code only for payload-shape logic those tools can't express.

**Three realism layers:**
- *Physical* — generate rainfall first (storm intensity/duration), derive lagged sensor responses (moisture lags rain; pore pressure slower; tilt last). Lagged exponential model suffices.
- *Device* — varied sampling rates, units, sensor counts per device type.
- *Failure* — dropouts, stuck values, NaN, clock skew, duplicates, out-of-order, offline/reconnect.

Do NOT scatter coordinates with `random.uniform(-90, 90)`; cluster around real sites.

Not yet implemented.
