export async function getOverview() {
  const r = await fetch("/api/overview");
  if (!r.ok) throw new Error("overview " + r.status);
  return r.json();
}

export async function getSite(
  id,
  hours = 24,
  fromTime = null,
  toTime = null,
  { signal } = {},
) {
  const params = new URLSearchParams({ hours });
  if (fromTime && toTime) {
    params.set("from", fromTime);
    params.set("to", toTime);
  }

  const r = await fetch(`/api/sites/${encodeURIComponent(id)}?${params}`, { signal });

  if (!r.ok) {
    const error = new Error("site " + r.status);
    error.status = r.status;

    if (r.status === 429) {
      const value = r.headers.get("Retry-After");

      if (value) {
        const seconds = Number(value);

        if (Number.isFinite(seconds) && seconds >= 0) {
          error.retryAfterMs = seconds * 1000;
        } else {
          const retryAt = Date.parse(value);
          if (Number.isFinite(retryAt)) {
            error.retryAfterMs = Math.max(0, retryAt - Date.now());
          }
        }
      }
    }

    throw error;
  }

  return r.json();
}

export function openStream(onEvent) {
  const es = new EventSource("/api/stream");
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {}
  };
  return es;
}
