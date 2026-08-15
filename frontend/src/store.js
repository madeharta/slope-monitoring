import { create } from "zustand";
import { openStream } from "./api";

// One store: SSE connection + live readings, plus small UI state (nav, overview
// panel). Streaming data lives here, not in per-chart useState, so a message
// doesn't re-render the whole tree (context.md §10.10).
export const useStore = create((set, get) => ({
  connected: false,
  clock: new Date(),
  overview: null,       // latest /api/overview payload (shared with the top bar)
  last: {},             // `${site}:${device}:${quantity}` -> latest event
  recent: {},           // site_id -> rolling recent events (live chart tail)
  overviewOpen: false,
  nav: "map",
  variant: (() => {
    let v = (typeof localStorage !== "undefined" && localStorage.getItem("magris-variant")) || "editorial";
    return v === "vibrant" ? "editorial" : v;
  })(),
  _es: null,

  setVariant: (v) => {
    try { localStorage.setItem("magris-variant", v); } catch {}
    document.documentElement.dataset.variant = v;
    set({ variant: v });
  },
  toggleVariant: () => get().setVariant(get().variant === "editorial" ? "mono" : "editorial"),

  setOverview: (o) => set({ overview: o }),
  setNav: (n) => set({ nav: n }),
  toggleOverview: () =>
    set((s) => ({ overviewOpen: !s.overviewOpen, nav: s.overviewOpen ? "map" : "overview" })),
  closeOverview: () => set({ overviewOpen: false, nav: "map" }),

  connect: () => {
    if (get()._es) return;
    document.documentElement.dataset.variant = get().variant;
    const es = openStream((ev) => {
      set((s) => {
        const key = `${ev.site_id}:${ev.device_id}:${ev.quantity}`;
        const recent = { ...s.recent };
        recent[ev.site_id] = (recent[ev.site_id] || []).concat(ev).slice(-500);
        return { last: { ...s.last, [key]: ev }, recent, connected: true };
      });
    });
    es.onopen = () => set({ connected: true });
    es.onerror = () => set({ connected: false });
    setInterval(() => set({ clock: new Date() }), 1000);
    set({ _es: es });
  },
}));

// true WIB (UTC+7) regardless of the viewer's timezone
export function wibClock(d) {
  const w = new Date(d.getTime() + (d.getTimezoneOffset() + 420) * 60000);
  const p = (n) => String(n).padStart(2, "0");
  return `${w.getFullYear()}-${p(w.getMonth() + 1)}-${p(w.getDate())} ${p(w.getHours())}:${p(
    w.getMinutes()
  )}:${p(w.getSeconds())} WIB`;
}
