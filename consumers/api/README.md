# consumers/api

FastAPI service: SSE (live view) + REST. Domain-specific displays only — operational/health panels belong in Grafana.

- Async; load models/config once at startup, not per request (prior work re-`pickle.load`ed on every request).
- Reads live data from the stream to keep the view real time.

Not yet implemented.
