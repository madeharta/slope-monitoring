import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import { getOverview } from "../api";
import { getPalette } from "../theme";
import SiteMap from "../components/SiteMap.jsx";

const LABEL = { bahaya: "Bahaya", siaga: "Siaga", normal: "Normal" };
const SCOL = { bahaya: "var(--bahaya)", siaga: "var(--siaga)", normal: "var(--ok)" };
const SRING = { bahaya: "var(--bahaya-soft)", siaga: "var(--siaga-soft)", normal: "transparent" };

const fmt = (v) => (typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : v);

function reading(r) {
  if (!r) return "";
  return `${fmt(r.value)} ${r.unit}`;
}

function recentValues(recent, quantity, n = 28) {
  const out = [];
  for (const site in recent) for (const ev of recent[site]) if (ev.quantity === quantity && ev.value != null) out.push(ev.value);
  return out.slice(-n);
}

function Spark({ data, c, area }) {
  const W = 250, H = 62, pad = 7;
  if (!data.length) data = [0, 0];
  const mn = Math.min(...data), mx = Math.max(...data);
  const X = (i) => pad + (i / Math.max(data.length - 1, 1)) * (W - 2 * pad);
  const Y = (v) => H - pad - ((v - mn) / (mx - mn || 1)) * (H - 2 * pad);
  const pts = data.map((v, i) => `${X(i)},${Y(v)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`}>
      {area && <polygon points={`${pts} ${X(data.length - 1)},${H - pad} ${X(0)},${H - pad}`} fill={c.fill} />}
      <polyline points={pts} fill="none" stroke={c.stroke} strokeWidth="1.7" strokeLinejoin="round" />
      <circle cx={X(data.length - 1)} cy={Y(data[data.length - 1])} r="3" fill={c.end} />
    </svg>
  );
}

export default function Overview() {
  const nav = useNavigate();
  const { overview, setOverview, recent, variant } = useStore((s) => ({
    overview: s.overview, setOverview: s.setOverview, recent: s.recent, variant: s.variant,
  }));
  const pal = getPalette(variant);
  const [warnOpen, setWarnOpen] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = () => getOverview().then((o) => alive && setOverview(o)).catch(() => {});
    load();
    const t = setInterval(load, 8000);
    return () => { alive = false; clearInterval(t); };
  }, [setOverview]);

  const slopes = overview?.slopes || [];
  const c = overview?.status_counts || { normal: 0, siaga: 0, bahaya: 0 };
  const health = overview?.health || { online: 0, offline: 0, total: 0 };
  const alerts = slopes.filter((s) => s.status !== "normal");
  const warnings = c.siaga + c.bahaya;

  const rainArr = recentValues(recent, "rainfall");
  const moistArr = recentValues(recent, "soil_moisture");
  const rain = rainArr.length ? Math.round(Math.max(...rainArr)) : "—";
  const total = slopes.length || 1;

  return (
    <>
      <div className="mapwrap"><SiteMap slopes={slopes} /></div>
      <div className="scrim" />

      {/* LEFT — editorial headline + active-alarm cards, floating over the map */}
      <div className="ov-left">
        <div className="ov-eyebrow">ALL SLOPES <span>({slopes.length})</span></div>
        <button className="ov-title" onClick={() => setWarnOpen((o) => !o)} aria-expanded={warnOpen}>
          Warnings <span className="ov-count">({warnings})</span>
          <span className={"ov-chev" + (warnOpen ? " open" : "")}>⌄</span>
        </button>
        {warnOpen && (
          <div className="ov-alerts">
            {alerts.length === 0 && <div className="ov-empty">All slopes within safe limits.</div>}
            {alerts.map((s) => (
              <button key={s.site_id} className="alert-card" onClick={() => nav(`/sites/${s.site_id}`)}>
                <span className="ac-pip" style={{ background: SCOL[s.status], boxShadow: `0 0 0 3px ${SRING[s.status]}` }} />
                <span className="ac-body">
                  <span className="ac-name">{s.name}<span className="ac-tag"> · {LABEL[s.status]}</span></span>
                  <span className="ac-action">{s.action}</span>
                </span>
                <span className="ac-read">{reading(s.reading)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* BOTTOM-LEFT — weather + device stats */}
      <div className="ov-foot">
        <div className="wx">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9" /><line x1="8" y1="19" x2="8" y2="21" /><line x1="12" y1="18" x2="12" y2="22" /><line x1="16" y1="19" x2="16" y2="21" />
          </svg>
          <span className="wx-t">
            <span className="wx-v">{rain} <i>mm/h</i></span>
            <span className="wx-k">Peak rainfall · live</span>
          </span>
        </div>
        <span className="vdiv" />
        <div className="fstat"><span className="fs-v">{health.online}<i>/{health.total}</i></span><span className="fs-k">Devices online</span></div>
        <div className="fstat"><span className="fs-v warn">{c.siaga}</span><span className="fs-k">Siaga</span></div>
        <div className="fstat"><span className="fs-v crit">{c.bahaya}</span><span className="fs-k">Bahaya</span></div>
      </div>

      {/* RIGHT — status summary + live graphs (moved here from the old slide panel) */}
      <div className="ov-right">
        <div className="wcard">
          <div className="wcard-h"><h3>Rainfall live</h3><span className="wgic">⋯</span></div>
          <div className="wcard-b"><Spark data={rainArr} c={pal.spark} area /></div>
        </div>
        <div className="wcard">
          <div className="wcard-h"><h3>Moisture live</h3><span className="wgic">⋯</span></div>
          <div className="wcard-b"><Spark data={moistArr} c={pal.spark} area={pal.area} /></div>
        </div>
        <div className="wcard">
          <div className="wcard-h"><h3>Status Summary</h3></div>
          <div className="wcard-b">
            <div className="bar">
              {[["bahaya", c.bahaya], ["siaga", c.siaga], ["normal", c.normal]].map(([k, v]) =>
                v > 0 ? <i key={k} style={{ background: k === "normal" ? "var(--ok)" : `var(--${k})`, width: `${(v / total) * 100}%` }} /> : null
              )}
            </div>
            <div className="wcard-legend">
              <span><i style={{ background: "var(--bahaya)" }} />Bahaya {c.bahaya}</span>
              <span><i style={{ background: "var(--siaga)" }} />Siaga {c.siaga}</span>
              <span><i style={{ background: "var(--ok)" }} />Normal {c.normal}</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
