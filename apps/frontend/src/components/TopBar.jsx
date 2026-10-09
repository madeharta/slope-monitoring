import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useStore, wibClock } from "../store";
import { useAuth } from "../context/AuthContext.jsx";
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
  satellite: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 19 19 5" /><path d="m14 5 5 5" /><path d="m5 14 5 5" /><path d="M8.5 8.5a4 4 0 0 0 7 7" /><path d="M3 21h6" />
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
  const location = useLocation();
  const isMapRoute = location.pathname === "/";
  const { auth, logout } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const { navKey, overview, connected, clock, variant, toggleVariant, setNav } = useStore(
    (s) => ({
      navKey: s.nav, overview: s.overview, connected: s.connected, clock: s.clock,
      variant: s.variant, toggleVariant: s.toggleVariant, setNav: s.setNav,
    })
  );
  const counts = overview?.operational_alarm_counts || {
    siaga: 0, bahaya: 0, total: 0,
  };
  const operationalReady = overview?.validation?.operational_ready === true;
  const active = operationalReady ? (counts.total || 0) : 0;
  const chipCls = operationalReady
    ? (counts.bahaya ? "crit" : counts.siaga ? "warn" : "")
    : "";
  const items = [
    { key: "map", label: "Overview", icon: I.dash, onClick: () => { nav("/"); setNav("map"); } },
    { key: "analytics", label: "Analytics", icon: I.chart, onClick: () => setNav("analytics") },
    { key: "ppk", label: "PPK", icon: I.satellite, onClick: () => { nav("/ppk"); setNav("ppk"); } },
    { key: "alarms", label: "Alarms", icon: I.bell, onClick: () => setNav("alarms") },
  ];
  return (
    <header className={"topbar" + (isMapRoute ? "" : " topbar--solid")}>
      <div className="brand">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 20 L8.5 7 L12.5 14 L15.5 9 L22 20 Z" /></svg>
        <b>MAGRIS</b><span>LEWS</span>
      </div>
      <nav className="topnav" aria-label="Primary">
        {items.map((it) => (
          <button key={it.key} className={"nav-item" + ((navKey === it.key || (it.key === "ppk" && location.pathname.startsWith("/ppk"))) ? " on" : "")}
            aria-current={(navKey === it.key || (it.key === "ppk" && location.pathname.startsWith("/ppk"))) ? "page" : "false"} onClick={it.onClick}>
            {it.icon}<span>{it.label}</span>
          </button>
        ))}
      </nav>
      <div className="topright">
        <div
          className={"alarmchip " + chipCls}
          title={operationalReady
            ? "Active operational alarms"
            : "Operational alarms suppressed pending validation"}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.3 4 2.5 18a1.5 1.5 0 0 0 1.3 2.2h16.4a1.5 1.5 0 0 0 1.3-2.2L13.7 4a1.5 1.5 0 0 0-2.6 0z" />
            <path d="M12 9.5v4" /><path d="M12 17h.01" />
          </svg>
          {operationalReady ? (
            <>
              <span className="un">{active}</span> active
            </>
          ) : (
            <>
              <span className="un">0</span> operational{" "}
              <span className="rlbl">suppressed</span>
            </>
          )}
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
        <div className="profile-menu" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setProfileOpen(false); }}>
          <button className="avatar" aria-label="Account" aria-expanded={profileOpen} onClick={() => setProfileOpen((v) => !v)}>
            {initialsFromEmail(auth?.email)}
          </button>
          {profileOpen && (
            <div className="profile-dropdown" role="menu">
              <div className="pd-header">
                <div className="pd-name">{auth?.email || "—"}</div>
                <div className="pd-role">{auth?.role || "—"}</div>
              </div>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/sites"); }}>
                Sites
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/devices"); }}>
                Devices
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/uploads"); }}>
                Uploads
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/ppk"); setNav("ppk"); }}>
                PPK Technical Results
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/settings"); }}>
                Settings
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/audit-log"); }}>
                Audit Log
              </button>
              {auth?.role === "admin" && (
                <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/users"); }}>
                  Users
                </button>
              )}
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/mfa/enroll"); }}>
                Aktifkan / Kelola MFA (2FA)
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); nav("/panduan"); }}>
                Panduan Penggunaan
              </button>
              <button role="menuitem" onClick={() => { setProfileOpen(false); window.open("mailto:support@namadomain.id"); }}>
                Bantuan
              </button>
              <button role="menuitem" className="pd-danger" onClick={() => { setProfileOpen(false); logout(); nav("/login", { replace: true }); }}>
                Keluar
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
function initialsFromEmail(email) {
  if (!email) return "?";
  const local = email.split("@")[0];
  const parts = local.split(/[._-]/).filter(Boolean);
  const initials = parts.slice(0, 2).map((p) => p[0]?.toUpperCase() || "").join("");
  return initials || local.slice(0, 2).toUpperCase();
}
