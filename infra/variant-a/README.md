# infra/variant-a — MQTT only

`devices → MQTT broker → consumer → {TimescaleDB, dashboard}`

The simplest thing that could work. Realistic slope deployments may have only tens of nodes per site, where Kafka's overhead may not be justified. If A holds up to some N, that is a useful finding.

Starts with a single `docker compose up` and exposes the same consumer interface as all other variants. Image versions pinned explicitly (no `:latest`).

## Stack

- **mosquitto** (`:1883`) — MQTT broker
- **timescaledb** (`:5432`) — storage; schema auto-created from `init/001_schema.sql`

The consumer (`consumers/db-writer`) currently runs on the host for the smoke
test; it will be containerized here once the round-trip is stable.

## Start / stop

```bash
docker compose up -d          # start broker + TimescaleDB
docker compose ps             # check status
docker compose down           # stop (data kept in the tsdata volume)
docker compose down -v        # stop AND wipe all data + schema
```

## Refresh data back to 0

Empty the measurement/device data but keep the tables and seeded sites
(works the same in bash and PowerShell):

```bash
docker exec magris-variant-a-timescaledb-1 psql -U magris -d magris \
  -c "TRUNCATE measurements; DELETE FROM devices;"
```

For a full reset (tables + schema rebuilt from `init/`), use
`docker compose down -v && docker compose up -d`.
