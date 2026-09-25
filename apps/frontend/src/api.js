export async function getOverview() {
  const r = await fetch("/api/overview");
  if (!r.ok) throw new Error("overview " + r.status);
  return r.json();
}
export async function getSite(id, hours = 24, fromTime = null, toTime = null) {
  const params = new URLSearchParams({ hours });
  if (fromTime && toTime) {
    params.set("from", fromTime);
    params.set("to", toTime);
  }
  const r = await fetch(`/api/sites/${encodeURIComponent(id)}?${params}`);
  if (!r.ok) throw new Error("site " + r.status);
  return r.json();
}
export function openStream(onEvent) {
  const es = new EventSource("/api/stream");
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch
  };
  return es;
}
