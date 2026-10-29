import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import { getOverview } from "../api";
import { getPalette } from "../theme";
import { useAuth } from "../context/AuthContext.jsx";
import SiteMap from "../components/SiteMap.jsx";

const LABEL = { bahaya: "Danger", siaga: "Warning", normal: "Normal", unknown: "Not verified" };
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

// FIX (2026-09-20): weather sebelumnya digabung SEMUA site jadi satu
// angka tanpa penanda lokasi — ambigu begitu >1 site punya data cuaca.
// Helper ini kembalikan { site_id: nilai_terakhir } supaya bisa
// ditampilkan per-site secara eksplisit.
function latestBySite(recent, quantity) {
  const out = {};
  for (const site in recent) {
    for (const ev of recent[site]) {
      if (ev.quantity === quantity && ev.value != null) out[site] = ev.value; // event terakhir menang (recent[site] sudah urut waktu)
    }
  }
  return out;
}

// Jarak great-circle sederhana (2026-09-20) — dipakai murni untuk
// MENGURUTKAN site terdekat dari lokasi browser pengguna, bukan untuk
// perhitungan presisi (itu urusan backend, ml/pipeline/.../displacement.py).
function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function Spark({ data, c, area }) {
  const W = 250, H = 62, pad = 7;
  if (!data.length) return null;
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


// B12_PPK_CROSSPAGE_AUTO: isolated QA outcomes, never operational displacement.
function summarizeExperimentalPpkQa(payload) {
  if (payload?.scope !== "EXPERIMENTAL_ENGINE_QA_ONLY" || payload?.reference_type !== "PROVISIONAL_SPP" || payload?.validation_status !== "unvalidated" || !Array.isArray(payload.rows)) {
    throw new Error("Unexpected experimental QA contract");
  }
  const counts = { FIX: 0, FLOAT: 0, SINGLE: 0, OTHER: 0 };
  for (const row of payload.rows) {
    const q = Number(row.rtklib_quality);
    if (q === 1) counts.FIX += 1;
    else if (q === 2) counts.FLOAT += 1;
    else if (q === 5) counts.SINGLE += 1;
    else counts.OTHER += 1;
  }
  return { total: payload.rows.length, counts, limited: payload.rows.length >= 2000 };
}

export default function Overview() {
  const nav = useNavigate();
  const { overview, setOverview, recent, variant } = useStore((s) => ({
    overview: s.overview, setOverview: s.setOverview, recent: s.recent, variant: s.variant,
  }));
  const pal = getPalette(variant);
  const { authFetch } = useAuth();
  const [warnOpen, setWarnOpen] = useState(true);

  // B12_PPK_CROSSPAGE_AUTO: single QA read, no periodic PPK solver or upload.
  const [ppkQaSummary, setPpkQaSummary] = useState({ state: "loading", result: null });
  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({site_id: "ITB-STAGING-01", rover_device_id: "ROVER-B1-02", limit: "2000"});
    authFetch(`/api/v1/ppk/qa/solutions?${params}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`PPK QA HTTP ${response.status}`);
        return summarizeExperimentalPpkQa(await response.json());
      })
      .then((result) => { if (alive) setPpkQaSummary({state: "ok", result}); })
      .catch(() => { if (alive) setPpkQaSummary({state: "error", result: null}); });
    return () => { alive = false; };
  }, [authFetch]);

  const [ppkQa, setPpkQa] = useState({ loading: true, error: false, rows: [] });
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    async function loadPpkQa() {
      try {
        const url = "/api/v1/ppk/qa/solutions?site_id=ITB-STAGING-01&rover_device_id=ROVER-B1-02&limit=500";
        const response = await authFetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`PPK QA HTTP ${response.status}`);
        const data = await response.json();
        if (data?.schema_version !== "ppk.qa.solution.v1" || data?.reference_type !== "PROVISIONAL_SPP" || data?.validation_status !== "unvalidated" || data?.operational_displacement_approved !== false || !Array.isArray(data?.rows)) {
          throw new Error("Unexpected PPK QA schema or validation flags");
        }
        if (alive) setPpkQa({ loading: false, error: false, rows: data.rows });
      } catch (err) {
        if (alive && !controller.signal.aborted) setPpkQa({ loading: false, error: true, rows: [] });
      }
    }
    loadPpkQa();
    return () => { alive = false; controller.abort(); };
  }, [authFetch]);
  const ppkCounts = ppkQa.rows.reduce((a, r) => {
    const q = Number(r.rtklib_quality);
    if (q === 1) a.fix++;
    else if (q === 2) a.float++;
    else if (q === 5) a.single++;
    return a;
  }, { fix: 0, float: 0, single: 0 });


  useEffect(() => {
    let alive = true;
    const load = () => getOverview(authFetch).then((o) => alive && setOverview(o)).catch(() => {});
    load();
    const t = setInterval(load, 8000);
    return () => { alive = false; clearInterval(t); };
  }, [setOverview, authFetch]);

  // Weather refresh is owned by backend's 15-minute worker; Overview is read-only.
  const slopes = overview?.slopes || [];
  const c = overview?.status_counts || { normal: 0, siaga: 0, bahaya: 0, unknown: 0 };
  const health = overview?.health || { online: 0, offline: 0, total: 0 };
  const deviceHealth = overview?.device_health || { online: health.online || 0, stale: 0, offline: health.offline || 0, unknown: 0, total: health.total || 0 };
  const devices = overview?.devices || [];
  const operationalCounts = overview?.operational_alarm_counts || {
    siaga: 0, bahaya: 0, total: 0,
  };
  const operationalReady = overview?.validation?.operational_ready === true;

  // Fail closed if validation metadata is absent/old.
  const alerts = slopes.filter((s) => s.operational_alarm === true);
  const warnings = operationalReady ? (operationalCounts.total || 0) : 0;

  // FIX (2026-09-20): rainfall/soil_moisture SELALU kosong — tidak ada
  // rain gauge/soil-moisture probe di hardware sistem ini (GNSS +
  // accelerometer saja). Diganti quantity yang benar-benar ada datanya.
  const dispArr = recentValues(recent, "displacement");
  const vibArr = recentValues(recent, "ppv");
  const peakDisp = dispArr.length ? Math.round(Math.max(...dispArr)) : "—";
  const total = slopes.length || 1;

  // BATCH11G_DB_WEATHER_V2: last persisted weather per site is authoritative.
  // Read-only authenticated GET, no telemetry lookback limit and no browser cache.
  const [persistedWeather, setPersistedWeather] = useState({});
  const [weatherLoaded, setWeatherLoaded] = useState(false);
  const [weatherError, setWeatherError] = useState(false);
  useEffect(() => {
    let alive = true;
    async function loadWeather() {
      try {
        const response = await authFetch("/api/v1/weather/latest");
        if (!response.ok) throw new Error(`Weather API HTTP ${response.status}`);
        const payload = await response.json();
        if (!payload || payload.ok !== true || !payload.sites || typeof payload.sites !== "object" || Array.isArray(payload.sites)) {
          throw new Error("Invalid latest weather response");
        }
        if (alive) {
          setPersistedWeather(payload.sites);
          setWeatherLoaded(true);
          setWeatherError(false);
        }
      } catch (error) {
        // Do not erase an earlier successful snapshot on transient errors.
        if (alive) { setWeatherLoaded(true); setWeatherError(true); }
      }
    }
    loadWeather();
    const timer = setInterval(loadWeather, 60000); // UI GET refresh; not Open-Meteo polling.
    return () => { alive = false; clearInterval(timer); };
  }, [authFetch]);

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
  const weatherSiteIds = Object.keys(persistedWeather).filter((id) => siteById[id]);
  const weatherSites = weatherSiteIds.sort((a, b) => {
    if (!userPos) return 0;
    const sa = siteById[a], sb = siteById[b];
    return haversineKm(userPos.lat, userPos.lon, sa.lat, sa.lon) - haversineKm(userPos.lat, userPos.lon, sb.lat, sb.lon);
  }).slice(0, 2);
  const weatherObservedAt = (value) => {
    if (!value) return "Observation time unavailable";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Invalid observation time" : parsed.toLocaleString("en-GB", { timeZone: "Asia/Jakarta", dateStyle: "medium", timeStyle: "short" }) + " WIB";
  };
  const weatherAgeLabel = (value) => {
    const t = Date.parse(value || "");
    if (!Number.isFinite(t)) return "HISTORICAL · time unknown";
    const age = Date.now() - t;
    return age >= 0 && age <= 30 * 60 * 1000 ? "LAST OBSERVED" : "HISTORICAL / STALE";
  };
  // Weather display only: keep raw backend/database precision unchanged.
  const wxNumber = (value, digits = 1) => {
    if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
    const rounded = Number(Number(value).toFixed(digits));
    return new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(rounded);
  };

  return (
    <>
      <div className="mapwrap"><SiteMap slopes={slopes} devices={devices} /></div>
      <div className="scrim" />

      {/* LEFT — editorial headline + active-alarm cards, floating over the map */}
      <div className="ov-left">
        <div className="ov-validation" role="status"><strong>RESEARCH · UNVALIDATED</strong> — Operational alarms and response instructions remain disabled until field, PPK, and baseline validation are approved.</div>
        <div className="ov-eyebrow">ALL SLOPES <span>({slopes.length})</span></div>
        <button className="ov-title" onClick={() => setWarnOpen((o) => !o)} aria-expanded={warnOpen}>
          Operational alerts <span className="ov-count">({warnings})</span>
          <span className={"ov-chev" + (warnOpen ? " open" : "")}>⌄</span>
        </button>
        {warnOpen && (
          <div className="ov-alerts">
            {alerts.length === 0 && (
              <div className="ov-empty">
                {operationalReady
                  ? "No active operational alarms. This does not confirm slope safety."
                  : "Operational alarms are suppressed pending validation acceptance."}
              </div>
            )}
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
        {operationalReady && dispArr.length > 0 && <div className="wx">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 16.2A4.5 4.5 0 0 0 17.5 8h-1.8A7 7 0 1 0 4 14.9" /><line x1="8" y1="19" x2="8" y2="21" /><line x1="12" y1="18" x2="12" y2="22" /><line x1="16" y1="19" x2="16" y2="21" />
          </svg>
          <span className="wx-t">
            <span className="wx-v">{peakDisp} <i>mm</i></span>
            <span className="wx-k">Displacement · research only</span>
          </span>
        </div>}
        {operationalReady && dispArr.length > 0 && <span className="vdiv" />}
        <div className="fstat"><span className="fs-v">{deviceHealth.online}<i>/{deviceHealth.total}</i></span><span className="fs-k">Devices online</span></div>
        <div className="fstat"><span className="fs-v warn">{deviceHealth.stale}</span><span className="fs-k">Devices stale</span></div>
        <div className="fstat"><span className="fs-v">{deviceHealth.offline + deviceHealth.unknown}</span><span className="fs-k">Offline / unknown</span></div>
        <div className="fstat"><span className="fs-v warn">{c.siaga}</span><span className="fs-k">Technical Warning</span></div>
        <div className="fstat"><span className="fs-v crit">{c.bahaya}</span><span className="fs-k">Technical Danger</span></div>
      </div>

      {/* RIGHT — status summary + live graphs (moved here from the old slide panel) */}
      <div className="ov-right">
        {operationalReady && dispArr.length > 0 && (
          <div className="wcard">
            <div className="wcard-h"><h3>Displacement (baseline-approved only; not field validated)</h3><span className="wgic">⋯</span></div>
            <div className="wcard-b"><Spark data={dispArr} c={pal.spark} area /></div>
          </div>
        )}
        {vibArr.length > 0 && (
          <div className="wcard">
            <div className="wcard-h"><h3>Vibration (PPV) · observations</h3><span className="wgic">⋯</span></div>
            <div className="wcard-b"><Spark data={vibArr} c={pal.spark} area={pal.area} /></div>
          </div>
        )}
        <div className="wcard ppk-overview-card">
          <div className="wcard-h"><h3>PPK engine QA · ROVER-B1-02</h3><span className="wgic" title="Experimental / unvalidated">ⓘ</span></div>
          <div className="wcard-b">
            {ppkQaSummary.state === "loading" && <div className="ppk-overview-copy">Loading stored QA results…</div>}
            {ppkQaSummary.state === "error" && <div className="ppk-overview-copy">PPK QA results are unavailable. Operational data is unaffected.</div>}
            {ppkQaSummary.state === "ok" && ppkQaSummary.result?.total === 0 && <div className="ppk-overview-copy">No experimental solutions are available for this rover.</div>}
            {ppkQaSummary.state === "ok" && ppkQaSummary.result?.total > 0 && (
              <>
                <div style={{display:"grid",gridTemplateColumns:"repeat(3,minmax(0,1fr))",gap:8,marginBottom:8}}>
                  {(["FIX","FLOAT","SINGLE"]).map((label) => <div key={label} style={{border:"1px solid var(--border, #dbe3eb)",borderRadius:6,padding:"7px 5px",textAlign:"center"}}><small>{label}</small><div style={{fontWeight:750,fontSize:18}}>{ppkQaSummary.result.counts[label]}</div></div>)}
                </div>
                <div className="ppk-overview-copy">{ppkQaSummary.result.total} QA solutions · PROVISIONAL_SPP · unvalidated{ppkQaSummary.result.limited ? " · limited to 2,000 rows" : ""}. Not operational displacement or alarms.</div>
              </>
            )}
            <button className="ppk-overview-link" onClick={() => nav("/ppk")}>PPK QA details →</button>
          </div>
        </div>
        <div className="wcard">
          <div className="wcard-h"><h3>Technical Status Summary</h3></div>
          <div className="wcard-b">
            <div className="bar">
              {[["bahaya", c.bahaya], ["siaga", c.siaga], ["normal", c.normal]].map(([k, v]) =>
                v > 0 ? <i key={k} style={{ background: k === "normal" ? "var(--ok)" : `var(--${k})`, width: `${(v / total) * 100}%` }} /> : null
              )}
            </div>
            <div className="wcard-legend">
              <span><i style={{ background: "var(--bahaya)" }} />Technical Danger {c.bahaya}</span>
              <span><i style={{ background: "var(--siaga)" }} />Technical Warning {c.siaga}</span>
              <span><i style={{ background: "var(--ok)" }} />Normal {c.normal}</span>
              <span><i style={{ background: "#8b8c96" }} />Not verified {c.unknown || 0}</span>
            </div>
          </div>
        </div>

        {/* External weather: latest persisted PostgreSQL observation per site. */}
        <div className="wcard">
          <div className="wcard-h"><h3>External weather</h3><span className="wgic" title="Open-Meteo; not an on-site sensor">ⓘ</span></div>
          <div className="wcard-b wx-ext">
            {weatherSites.length === 0 && (
              <div className="wx-ext-site">
                <div className="wx-ext-site-name">Latest observation</div>
                <div className="wx-ext-row"><span>Rainfall</span><b>—</b></div>
                <div className="wx-ext-row"><span>24h rainfall</span><b>—</b></div>
                <div className="wx-ext-row"><span>Temperature</span><b>—</b></div>
                <div className="wx-ext-row"><span>Humidity</span><b>—</b></div>
                <div className="wx-ext-stale">{weatherError ? "Failed to load weather data from the API." : weatherLoaded ? "No stored weather observations for this site." : "Loading stored weather observations…"}</div>
              </div>
            )}
            {weatherSites.map((siteId) => {
              const wx = persistedWeather[siteId];
              return (
                <div key={siteId} className="wx-ext-site">
                  <div className="wx-ext-site-name">
                    {siteById[siteId]?.name || siteId}
                    {userPos && Number.isFinite(Number(siteById[siteId]?.lat)) && Number.isFinite(Number(siteById[siteId]?.lon)) && (
                      <span className="wx-ext-dist"> · {haversineKm(userPos.lat, userPos.lon, siteById[siteId].lat, siteById[siteId].lon).toFixed(1)} km from you</span>
                    )}
                  </div>
                  <div className="wx-ext-stale">{weatherAgeLabel(wx.observed_at)} · {weatherObservedAt(wx.observed_at)}{weatherError ? " · OFFLINE (last received)" : ""}</div>
                  <div className="wx-ext-row"><span>Rainfall</span><b>{wxNumber(wx.rainfall_mm)} mm</b></div>
                  <div className="wx-ext-row"><span>24h rainfall</span><b>{wxNumber(wx.rainfall_24h_mm)} mm</b></div>
                  <div className="wx-ext-row"><span>Temperature</span><b>{wxNumber(wx.temperature_c)} °C</b></div>
                  <div className="wx-ext-row"><span>Humidity</span><b>{wxNumber(wx.humidity_pct)} %</b></div>
                </div>
              );
            })}
            <div className="wx-ext-attr">Open-Meteo · latest stored database observation; API checked every 60 seconds. Historical data does not represent live conditions.</div>
            {weatherSiteIds.length > weatherSites.length && (
              <div className="wx-ext-more">+{weatherSiteIds.length - weatherSites.length} other sites have weather observations — see slope details.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
