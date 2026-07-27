# dashboard

Purpose is **validating the pipeline end to end**, not being a product.

**Use Grafana** (connects straight to TimescaleDB) for operational/health panels:
- site map with per-device health (last seen, battery, RSSI)
- combined time series: rainfall as bars + moisture/suction/tilt as lines on a shared axis (the standard landslide early-warning plot)
- data-quality panel: message rate, gap detection, out-of-range counts
- simple static thresholds per sensor

This directory holds Grafana provisioning (datasources, dashboards). Custom domain-specific views live in `consumers/api`.

Not yet implemented.
