import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import { getOverview } from "../api";
import { getPalette } from "../theme";
import { useAuth } from "../context/AuthContext.jsx";
import SiteMap from "../components/SiteMap.jsx";
const LABEL = { bahaya: "Bahaya", siaga: "Siaga", normal: "Normal", unknown: "Belum terverifikasi" };
const SCOL = { bahaya: "var(--bahaya)", siaga: "var(--siaga)", normal: "var(--ok)", unknown: "#8b8c96" };
const SRING = { bahaya: "var(--bahaya-soft)", siaga: "var(--siaga-soft)", normal: "transparent", unknown: "transparent" };
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
function latestBySite(recent, quantity) {
  const out = {};
  for (const site in recent) {
    for (const ev of recent[site]) {
      if (ev.quantity === quantity && ev.value != null) out[site] = ev.value;
    }
  }
  return out;
}
function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
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
  const { authFetch } = useAuth();
  const [warnOpen, setWarnOpen] = useState(true);
  const weatherFetchedRef = useRef(false);
  useEffect(() => {
    let alive = true;
    const load = () => getOverview().then((o) => alive && setOverview(o)).catch(() => {});
    load();
    const t = setInterval(load, 8000);
    return () => { alive = false; clearInterval(t); };
  }, [setOverview]);
  useEffect(() => {
    if (weatherFetchedRef.current || !overview?.slopes?.length) return;
    weatherFetchedRef.current = true;
    overview.slopes.forEach((s) => {
      authFetch(`/api/v1/weather/fetch/${encodeURIComponent(s.site_id)}`, { method: "POST" })
        .catch((err) => console.debug("weather auto-fetch skipped for", s.site_id, err));
    });
  }, [overview, authFetch]);
  const slopes = overview?.slopes || [];
  const c = overview?.status_counts || { normal: 0, siaga: 0, bahaya: 0 };
  const health = overview?.health || { online: 0, offline: 0, total: 0 };
  const alerts = slopes.filter((s) => s.status !== "normal");
  const warnings = c.siaga + c.bahaya + (c.unknown || 0);
  const dispArr = recentValues(recent, "displacement");
  const vibArr = recentValues(recent, "ppv");
  const peakDisp = dispArr.length ? Math.round(Math.max(...dispArr)) : "—";
  const total = slopes.length || 1;
  const rainBySite = latestBySite(recent, "rainfall_external");
  const rain24hBySite = latestBySite(recent, "rainfall_24h_external");
  const tempBySite = latestBySite(recent, "temperature_external");
  const humidBySite = latestBySite(recent, "humidity_external");
  const allWeatherSiteIds = [...new Set([...Object.keys(rainBySite), ...Object.keys(tempBySite), ...Object.keys(humidBySite)])];
  const [userPos, setUserPos] = useState(null);
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => setUserPos({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => setUserPos(null),
      { timeout: 5000 }
    );
  }, []);
  const siteById = Object.fromEntries(slopes.map((s) => [s.site_id, s]));
  const weatherSites = [...allWeatherSiteIds]
    .filter((id) => siteById[id])
    .sort((a, b) => {
      if (!userPos) return 0;
      const da = haversineKm(userPos.lat, userPos.lon, siteById[a].lat, siteById[a].lon);
      const db = haversineKm(userPos.lat, userPos.lon, siteById[b].lat, siteById[b].lon);
      return da - db;
    })
    .slice(0, 2);
  return (
    <>
      <div role="status" style={{position:"fixed",top:64,left:16,zIndex:1000,background:"#35240c",color:"#ffe7ac",padding:"8px 12px",border:"1px solid #b88b43",borderRadius:6,maxWidth:510,fontSize:12}}>
        DATA BELUM TERVALIDASI LAPANGAN — angka historis sebelum persetujuan baseline disembunyikan. Status Normal bukan sertifikasi aman.
      </div>
      <div className="mapwrap"><SiteMap slopes={slopes} /></div>
      <div className="scrim" />
      <div className="ov-left">
        <div className="ov-eyebrow">ALL SLOPES <span>({slopes.length})</span></div>
        <button className="ov-title" onClick={() => setWarnOpen((o) => !o)} aria-expanded={warnOpen}>
          Warnings <span className="ov-count">({warnings})</span>
          <span className={"ov-chev" + (warnOpen ? " open" : "")}>⌄</span>
        </button>
        {warnOpen && (
          <div className="ov-alerts">
            {alerts.length === 0 && <div className="ov-empty">Tidak ada alarm aktif; bukan bukti kondisi lereng aman.</div>}
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
      <div className="ov-foot">
        <div className="wx">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9" /><line x1="8" y1="19" x2="8" y2="21" /><line x1="12" y1="18" x2="12" y2="22" /><line x1="16" y1="19" x2="16" y2="21" />
          </svg>
          <span className="wx-t">
            <span className="wx-v">{peakDisp} <i>mm</i></span>
            <span className="wx-k">Peak displacement · live</span>
          </span>
        </div>
        <span className="vdiv" />
        <div className="fstat"><span className="fs-v">{health.online}<i>/{health.total}</i></span><span className="fs-k">Devices online</span></div>
        <div className="fstat"><span className="fs-v warn">{c.siaga}</span><span className="fs-k">Siaga</span></div>
        <div className="fstat"><span className="fs-v crit">{c.bahaya}</span><span className="fs-k">Bahaya</span></div>
      </div>
      <div className="ov-right">
        <div className="wcard">
          <div className="wcard-h"><h3>Displacement (baseline-approved only; not field validated)</h3><span className="wgic">⋯</span></div>
          <div className="wcard-b"><Spark data={dispArr} c={pal.spark} area /></div>
        </div>
        <div className="wcard">
          <div className="wcard-h"><h3>Vibration (PPV) live</h3><span className="wgic">⋯</span></div>
          <div className="wcard-b"><Spark data={vibArr} c={pal.spark} area={pal.area} /></div>
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
              <span><i style={{ background: "#8b8c96" }} />Belum terverifikasi {c.unknown || 0}</span>
            </div>
          </div>
        </div>
        {weatherSites.length > 0 && (
          <div className="wcard">
            <div className="wcard-h"><h3>External weather</h3><span className="wgic" title="Open-Meteo, bukan sensor lapangan">ⓘ</span></div>
            <div className="wcard-b wx-ext">
              {weatherSites.map((siteId) => (
                <div key={siteId} className="wx-ext-site">
                  <div className="wx-ext-site-name">
                    {siteById[siteId]?.name || siteId}
                    {userPos && <span className="wx-ext-dist"> · {haversineKm(userPos.lat, userPos.lon, siteById[siteId].lat, siteById[siteId].lon).toFixed(1)} km dari Anda</span>}
                  </div>
                  <div className="wx-ext-row"><span>Rainfall</span><b>{rainBySite[siteId] ?? "—"} mm</b></div>
                  <div className="wx-ext-row"><span>24h rainfall</span><b>{rain24hBySite[siteId] ?? "—"} mm</b></div>
                  <div className="wx-ext-row"><span>Temperature</span><b>{tempBySite[siteId] ?? "—"} °C</b></div>
                  <div className="wx-ext-row"><span>Humidity</span><b>{humidBySite[siteId] ?? "—"} %</b></div>
                </div>
              ))}
              <div className="wx-ext-attr">Weather data by Open-Meteo.com (CC BY 4.0)</div>
              {allWeatherSiteIds.length > weatherSites.length && (
                <div className="wx-ext-more">
                  +{allWeatherSiteIds.length - weatherSites.length} site lain punya data cuaca — lihat di halaman detail lereng masing-masing.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
