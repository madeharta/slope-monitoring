# bench — benchmark harness

Targets any architecture variant unmodified (all expose the same consumer interface).

**Methodology (see `context.md` §8):**
- Report percentiles **p50/p95/p99 + max**, never just mean.
- **Instrument every hop**: ingress MQTT → egress bridge/Connect → ingress Kafka → consumer receipt.
- **Control clock skew** (NTP/chrony; report offset; prefer a single clock).
- **Warm up** (discard first 30–60s) and run ≥5 min.
- **Find the saturation point** — increase load until something breaks.

**Sweep one variable at a time** from a baseline (no full cross-product): architecture, device count (past 1000), QoS (0/1/2), Kafka partitions (1/3/6), payload format (JSON vs Protobuf/Avro), message pattern (steady/bursty), failure injection.

**Metrics:** per-hop + e2e latency percentiles, throughput (msg/s + bytes/s), CPU, memory, network I/O, message loss, consumer lag, recovery time.

Log each run to `results/` as JSON Lines or Parquet **with the full config recorded alongside**, so any run is reproducible. (`results/` is gitignored.)

Not yet implemented.
