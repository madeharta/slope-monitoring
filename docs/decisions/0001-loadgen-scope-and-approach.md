# 0001 — Load generator: scope and approach

**Status:** accepted · 2026-07-27

## Context

context.md §7 says to "prefer a mature tool" (emqtt-bench, mqtt-stresser,
k6-MQTT) for the load generator. That advice exists to avoid the prior
work's single defect: one shared MQTT client across all threads, so "1000
sensors" was really one connection (context.md §4.1). But mature bench tools
send fixed/templated payloads and cannot express our heterogeneous
envelope/measurements schema, the physical rainfall→sensor model, or failure
injection — which are the realism experiments this project is about.

## Decision

Build a **custom async Python simulator** (`aiomqtt`), where **each device is
its own client with a unique client id**. This satisfies the §7 constraint by
construction, avoids Python thread-pool GIL contention (so the actual publish
rate matches the configured rate), and keeps payload realism, seeding, and
failure injection in one place and one language.

**Scope split:**

- **This simulator → realism experiments only:** heterogeneous payloads,
  QoS 0/1/2 comparison, burst patterns, failure injection. Target scale
  **hundreds to low thousands of devices**.
- **Capacity / saturation sweeps → emqtt-bench (later).** Python asyncio hits
  its own connection ceiling at a few thousand clients per process; past that
  we would be measuring the load generator, not the architecture. Capacity
  runs need only connection count, message rate, and realistic payload size —
  no physical realism.

## Consequences

- Latency percentiles are computed by us (`common.metrics`), not a tool.
- A shared `common/` package holds the wire contract (schema, topics,
  metrics) so producer and consumer never drift. This is an addition to the
  context.md §11 layout.
- The build order is smoke test → physical layer → device layer → failure
  layer, proving hop instrumentation end-to-end before adding realism.
