# infra/variant-c — MQTT broker with native Kafka bridge

`devices → EMQX/HiveMQ (built-in Kafka bridge) → Kafka → consumers`

Removes Kafka Connect entirely: one fewer service, one fewer hop, one fewer VM. Optional variant D: run Kafka in KRaft mode (no Zookeeper).

Must start with a single `docker compose up` and expose the same consumer interface as all other variants. Pin explicit image versions (no `:latest`).

Not yet implemented.
