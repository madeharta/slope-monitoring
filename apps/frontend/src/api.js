export async function getOverview(authFetch) {
  const r = await authFetch("/api/overview");
  if (!r.ok) throw new Error("overview " + r.status);
  return r.json();
}

export async function getSite(
  id,
  hours = 24,
  fromTime = null,
  toTime = null,
  { signal, authFetch } = {},
) {
  const params = new URLSearchParams({ hours });
  if (fromTime && toTime) {
    params.set("from", fromTime);
    params.set("to", toTime);
  }

  const r = await authFetch(`/api/sites/${encodeURIComponent(id)}?${params}`, { signal });

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

// Native EventSource cannot attach a Bearer header. Stream via authenticated fetch;
// never place JWT credentials in a query string. Returns an EventSource-like
// handle exposing close(), onmessage and onerror for existing callers.
export function openStream(onEvent, authFetch) {
  const controller = new AbortController();
  const handle = { close: () => controller.abort(), onmessage: null, onerror: null };
  (async () => {
    const response = await authFetch("/api/stream", {
      headers: { Accept: "text/event-stream" },
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (!controller.signal.aborted) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const payload = chunk.split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart()).join("\n");
          if (!payload) continue;
          try {
            const event = { data: payload };
            handle.onmessage?.(event);
            onEvent(JSON.parse(payload));
          } catch { /* discard malformed events */ }
        }
      }
    } finally {
      reader.releaseLock();
    }
  })().catch((error) => {
    if (!controller.signal.aborted) handle.onerror?.(error);
  });
  return handle;
}
