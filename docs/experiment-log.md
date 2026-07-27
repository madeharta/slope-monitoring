# Experiment log

One entry per benchmark run (or run-set). Record enough to reproduce and to compare across variants.

## Template

```
### <date> — <short title>
- Variant:            A | B | C | D
- Config:             device_count=, qos=, partitions=, payload=, pattern=
- Warm-up / duration: 60s / 300s
- Clock skew:         measured offset =
- Result file:        bench/results/<file>.jsonl
- Findings:           p50/p95/p99/max, throughput, CPU/mem, loss, consumer lag, saturation point
- Notes:
```

_No runs yet._
