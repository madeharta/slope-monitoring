import { useNavigate } from "react-router-dom";
import { useStore, wibClock } from "../store";

const I = {
  dash: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  ),
  map: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21s7-6.5 7-11a7 7 0 1 0-14 0c0 4.5 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" />
    </svg>
  ),
  chart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19V5" /><path d="M4 15l4.5-4.5 3.5 3 7-7.5" />
    </svg>
  ),
  bell: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 8a6 6 0 0 1 12 0c0 6 2.5 7 2.5 7H3.5S6 14 6 8z" /><path d="M10.5 20a1.6 1.6 0 0 0 3 0" />
    </svg>
  ),
};

export default function TopBar() {
  const nav = useNavigate();
  const { navKey, overview, connected, clock, variant, toggleVariant, setNav } = useStore(
    (s) => ({
      navKey: s.nav, overview: s.overview, connected: s.connected, clock: s.clock,
      variant: s.variant, toggleVariant: s.toggleVariant, setNav: s.setNav,
    })
  );

  const counts = overview?.status_counts || { siaga: 0, bahaya: 0 };
  const active = (counts.siaga || 0) + (counts.bahaya || 0);
  const rate = (active * 0.1).toFixed(1);
  const chipCls = counts.bahaya ? "crit" : counts.siaga ? "warn" : "";

  const items = [
    { key: "overview", label: "Overview", icon: I.dash, onClick: () => { nav("/"); setNav("overview"); } },
    { key: "map", label: "Map", icon: I.map, onClick: () => { nav("/"); setNav("map"); } },
    { key: "analytics", label: "Analytics", icon: I.chart, onClick: () => setNav("analytics") },
    { key: "alarms", label: "Alarms", icon: I.bell, onClick: () => setNav("alarms") },
  ];

  return (
    <header className="topbar">
      <div className="brand">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 20 L8.5 7 L12.5 14 L15.5 9 L22 20 Z" /></svg>
        <b>MAGRIS</b><span>LEWS</span>
      </div>
      <nav className="topnav" aria-label="Primary">
        {items.map((it) => (
          <button key={it.key} className={"nav-item" + (navKey === it.key ? " on" : "")}
            aria-current={navKey === it.key ? "page" : "false"} onClick={it.onClick}>
            {it.icon}<span>{it.label}</span>
          </button>
        ))}
      </nav>
      <div className="topright">
        <div className={"alarmchip " + chipCls} title="Active alarms · alarm rate per 10 min (EEMUA 191)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.3 4 2.5 18a1.5 1.5 0 0 0 1.3 2.2h16.4a1.5 1.5 0 0 0 1.3-2.2L13.7 4a1.5 1.5 0 0 0-2.6 0z" />
            <path d="M12 9.5v4" /><path d="M12 17h.01" />
          </svg>
          <span className="un">{active}</span> active <span style={{ color: "var(--ink-3)" }}>·</span>{" "}
          <span className="rate">{rate}</span><span className="rlbl">/10m</span>
        </div>
        <div className="search"><span className="ic" aria-hidden>⌕</span>
          <input type="text" placeholder="Search slope / device…" aria-label="Search" />
        </div>
        <span className={"live" + (connected ? "" : " off")}><span className="dot" />{connected ? "Live" : "Offline"}</span>
        <span className="clock">{wibClock(clock)}</span>
        <button className="variant-toggle" onClick={toggleVariant} title="Toggle theme (Vibrant / ISA-101 mono)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="9" /><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none" /></svg>
          {variant === "editorial" ? "Editorial" : "ISA-101"}
        </button>
        <button className="avatar" aria-label="Account">RB</button>
      </div>
    </header>
  );
}
