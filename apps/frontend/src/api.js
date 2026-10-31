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

// Authenticated SSE transport: bounded decoding, lifecycle, and abort-safe cleanup.
// Reconnection belongs to the store, not this single-connection transport.
export function openStream(onEvent, authFetch) {
  if (typeof authFetch !== "function") throw new TypeError("openStream requires authFetch");
  const controller = new AbortController();
  let closed = false;
  const handle = {
    onopen: null, onmessage: null, onerror: null,
    close() { closed = true; controller.abort(); },
  };
  (async () => {
    const response = await authFetch("/api/stream", {
      headers: { Accept: "text/event-stream" }, signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);
    if (!response.headers.get("content-type")?.includes("text/event-stream")) {
      throw new Error("Unexpected SSE content type");
    }
    if (closed) return;
    handle.onopen?.();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const parseFrame = (frame) => {
      const payload = frame.split("\n").filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart()).join("\n");
      if (!payload || closed) return;
      let parsed;
      try { parsed = JSON.parse(payload); } catch { return; }
      handle.onmessage?.({ data: payload });
      onEvent(parsed);
    };
    try {
      while (!closed) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        if (buffer.length > 1024 * 1024) throw new Error("Oversized SSE frame");
        let index;
        while ((index = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          parseFrame(frame);
        }
      }
    } finally {
      try { await reader.cancel(); } catch { /* already ended */ }
      reader.releaseLock();
    }
    if (!closed) throw new Error("SSE connection ended");
  })().catch((error) => {
    if (!closed && error?.name !== "AbortError") handle.onerror?.(error);
  });
  return handle;
}
