// Backend client. In dev, Vite proxies /api to the FastAPI server.
export async function getOverview() {
  const r = await fetch("/api/overview");
  if (!r.ok) throw new Error("overview " + r.status);
  return r.json();
}

export async function getSite(id, hours = 24) {
  const r = await fetch(`/api/sites/${encodeURIComponent(id)}?hours=${hours}`);
  if (!r.ok) throw new Error("site " + r.status);
  return r.json();
}

// Single SSE connection for all devices; the caller routes by device_id/site_id.
export function openStream(onEvent) {
  const es = new EventSource("/api/stream");
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* keepalive/comment lines */
    }
  };
  return es;
}
