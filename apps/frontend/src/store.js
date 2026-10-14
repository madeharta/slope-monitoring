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
  _retry: null,
  _clockTimer: null,
  _generation: 0,

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

  disconnect: () => {
    const state = get();
    state._es?.close();
    if (state._retry != null) clearTimeout(state._retry);
    if (state._clockTimer != null) clearInterval(state._clockTimer);
    set({ _es: null, _retry: null, _clockTimer: null, connected: false,
      _generation: state._generation + 1, last: {}, recent: {} });
  },
  connect: (authFetch) => {
    if (typeof authFetch !== "function") throw new TypeError("connect requires authFetch");
    get().disconnect();
    document.documentElement.dataset.variant = get().variant;
    const generation = get()._generation;
    let attempts = 0;
    const clockTimer = setInterval(() => set({ clock: new Date() }), 1000);
    set({ _clockTimer: clockTimer });
    const dial = () => {
      if (generation !== get()._generation) return;
      const es = openStream((ev) => {
        if (generation !== get()._generation || !ev?.site_id) return;
        set((state) => {
          const key = `${ev.site_id}:${ev.device_id}:${ev.quantity}`;
          const recent = { ...state.recent };
          recent[ev.site_id] = (recent[ev.site_id] || []).concat(ev).slice(-500);
          return { last: { ...state.last, [key]: ev }, recent };
        });
      }, authFetch);
      es.onopen = () => { if (generation === get()._generation) {
        attempts = 0; set({ connected: true });
      }};
      es.onerror = () => {
        if (generation !== get()._generation) return;
        es.close();
        const delay = Math.min(30000, 1000 * 2 ** Math.min(attempts++, 5));
        const retry = setTimeout(() => {
          if (generation !== get()._generation) return;
          set({ _retry: null });
          dial();
        }, delay);
        set({ _es: null, _retry: retry, connected: false });
      };
      set({ _es: es });
    };
    dial();
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
