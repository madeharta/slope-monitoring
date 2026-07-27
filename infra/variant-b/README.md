# infra/variant-b — MQTT → Kafka Connect → Kafka

`devices → MQTT broker → Kafka Connect (MqttSourceConnector) → Kafka → consumers`

The prior work's design, reproduced as the baseline for comparison. Prefer current Kafka versions over the 2018 stack. Optional variant D: run Kafka in KRaft mode (no Zookeeper).

Must start with a single `docker compose up` and expose the same consumer interface as all other variants. Pin explicit image versions (no `:latest`).

Not yet implemented.
