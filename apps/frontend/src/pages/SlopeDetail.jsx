import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useStore } from "../store";
import { getSite } from "../api";
import { getPalette } from "../theme";
import { useAuth } from "../context/AuthContext.jsx";
import PanelChart from "../components/PanelChart.jsx";
import TimeToFailure, { estimateFailure } from "../components/TimeToFailure.jsx";
import MeasurementTable from "../components/MeasurementTable.jsx";

const LABEL = { bahaya: "Bahaya", siaga: "Siaga", normal: "Normal", unknown: "Belum terverifikasi" };
const HOURS = [["6h", 6], ["24h", 24], ["3d", 72], ["7d", 168]];
// Derived-quantity thresholds that have no backend entry (velocity is computed
// from the displacement series, so it is not in config.THRESHOLDS).
const VEL_TH = { dir: "high", siaga: 5, bahaya: 10 };
const DAY = 86_400_000;

const fmt = (v, d = 2) => (v == null ? "—" : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(d));

function statusFor(th, v) {
  if (!th || v == null) return "normal";
  if (th.dir === "high") { if (v >= th.bahaya) return "bahaya"; if (v >= th.siaga) return "siaga"; }
  else { if (v <= th.bahaya) return "bahaya"; if (v <= th.siaga) return "siaga"; }
  return "normal";
}

// ---- series helpers (operate on [[isoTime, value], ...] ascending) ----
const vals = (pts) => pts.map((p) => p[1]).filter((v) => v != null);
const last = (pts) => (pts.length ? pts[pts.length - 1][1] : null);
const maxOf = (pts, d = 1) => (vals(pts).length ? Math.max(...vals(pts)) : d);
const minOf = (pts, d = 0) => (vals(pts).length ? Math.min(...vals(pts)) : d);

function smoothPts(pts, k = 2) {
  const v = pts.map((p) => p[1]);
  return pts.map((p, i) => {
    let s = 0, n = 0;
    for (let j = Math.max(0, i - k); j <= Math.min(v.length - 1, i + k); j++) {
      if (v[j] != null) { s += v[j]; n++; }
    }
    return [p[0], n ? s / n : null];
  });
}

// first difference per day: displacement -> velocity (mm/day), velocity -> accel
function ratePerDay(pts, clampMin = null) {
  const out = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    if (a[1] == null || b[1] == null) continue;
    const dt = (new Date(b[0]) - new Date(a[0])) / DAY;
    if (dt <= 0) continue;
    let r = (b[1] - a[1]) / dt;
    if (clampMin != null) r = Math.max(clampMin, r);
    out.push([b[0], r]);
  }
  return out;
}

function valueAt(pts, tMs) {
  let best = null;
  for (const p of pts) { if (p[1] == null) continue; if (new Date(p[0]).getTime() <= tMs) best = p[1]; }
  return best;
}

function gapAware(pts, expectedMs = null, gapFactor = 2.5) {
  if (pts.length < 3) return pts;
  const deltas = [];
  for (let i = 1; i < pts.length; i++) {
    const a = new Date(pts[i - 1][0]).getTime();
    const b = new Date(pts[i][0]).getTime();
    if (Number.isFinite(a) && Number.isFinite(b) && b > a) deltas.push(b - a);
  }
  if (!deltas.length) return pts;
  const sorted = [...deltas].sort((a, b) => a - b);
  const inferredMs = sorted[Math.floor(sorted.length / 2)];
  const cadenceMs = expectedMs ?? inferredMs;
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const prevMs = new Date(pts[i - 1][0]).getTime();
    const nextMs = new Date(pts[i][0]).getTime();
    if (Number.isFinite(prevMs) && Number.isFinite(nextMs) && nextMs - prevMs > cadenceMs * gapFactor) {
      out.push([new Date(prevMs + Math.min(cadenceMs, (nextMs - prevMs) / 2)).toISOString(), null]);
    }
    out.push(pts[i]);
  }
  return out;
}

// integrate an mm/h series over its span -> accumulated mm
function accumulate(pts) {
  let acc = 0;
  for (let i = 1; i < pts.length; i++) {
    if (pts[i][1] == null) continue;
    const dt = (new Date(pts[i][0]) - new Date(pts[i - 1][0])) / 3_600_000;
    acc += pts[i][1] * dt;
  }
  return acc;
}

// which sensor group each quantity belongs to (for the device-isolate pills)
const GROUP_OF = {
  displacement: "gnss", disp_e: "gnss", disp_n: "gnss", disp_u: "gnss",
  velocity: "gnss", acceleration: "gnss",
  tilt_x: "accel", tilt_y: "accel", ppa: "accel", ppv: "accel", ppa_mpu9250: "accel", ppv_mpu9250: "accel",
  rainfall: "rain", pore_pressure: "piezo", suction: "piezo", soil_moisture: "soil",
};
const GROUPS = [
  { key: "gnss", label: "GNSS rover", quantities: ["displacement"] },
  { key: "accel", label: "Accelerometer", quantities: ["tilt_x", "tilt_y", "ppa", "ppv"] },
  { key: "rain", label: "Rain gauge", quantities: ["rainfall"] },
  { key: "piezo", label: "Piezometer", quantities: ["pore_pressure", "suction"] },
  { key: "soil", label: "Soil moisture", quantities: ["soil_moisture"] },
];

// ---- small presentational pieces ----
function Panel({ title, sub, right, tag, children, style }) {
  return (
    <section className="panel" style={{ display: "flex", flexDirection: "column", minHeight: 0, ...style }}>
      <div className="phead">
        <h2>{title}</h2>
        {tag && <span className="tag">{tag}</span>}
        {sub && <span className="sub">{sub}</span>}
        {right && <span className="phead-right num">{right}</span>}
      </div>
      {children}
    </section>
  );
}

function Legend({ items }) {
  return (
    <div className="chart-legend">
      {items.map((it, i) => (
        <span key={i}>
          <i className={"lg-" + (it.kind || "line")} style={legendSample(it)} />
          {it.label}
        </span>
      ))}
    </div>
  );
}
function legendSample(it) {
  if (it.kind === "box") return { background: it.color };
  if (it.kind === "bar") return { background: it.color, height: 8 };
  const dash = it.dash === "dashed" ? "dashed" : it.dash === "dotted" ? "dotted" : "solid";
  return { borderTop: `2px ${dash} ${it.color}` };
}

function StatCard({ label, value, sub, status }) {
  const col = status === "bahaya" ? "var(--bahaya)" : status === "siaga" ? "var(--siaga)" : "var(--ink)";
  return (
    <div className="statcard2">
      <div className="sc-label">{label}</div>
      <div className="sc-val num" style={{ color: col }}>{value}</div>
      <div className="sc-sub">{sub}</div>
    </div>
  );
}

function CrossSection({ sensors }) {
  const W = 300, H = 250;
  const withDepth = sensors.filter((s) => s.depth_cm != null).sort((a, b) => a.depth_cm - b.depth_cm);
  const maxD = Math.max(100, ...withDepth.map((s) => s.depth_cm));
  const col = (st) => (st === "bahaya" ? "#ef4d54" : st === "siaga" ? "#eea23c" : "#8b8c96");
  const bx = 92, surfaceY = 78, labelX = 148;      // borehole x, surface y, label column
  const nodeY = (d) => surfaceY + (d / maxD) * 140; // dot sits at true depth
  const n = Math.max(withDepth.length, 1);
  const rowY = (i) => 90 + (i + 0.5) * (152 / n);   // labels evenly spaced — never overlap
  return (
    <svg className="xsvg" viewBox={`0 0 ${W} ${H}`}>
      <rect width={W} height={H} fill="#0c0c10" />
      <path d={`M0 52 L ${bx} ${surfaceY} L ${W} 150 L ${W} ${H} L 0 ${H} Z`} fill="#141419" stroke="#26262d" />
      <path d={`M0 52 L ${bx} ${surfaceY} L ${W} 150`} fill="none" stroke="#3a3a46" strokeWidth="1.5" />
      <line x1={bx} y1={surfaceY} x2={bx} y2={nodeY(maxD) + 6} stroke="#26262d" strokeWidth="2" />
      <text x="12" y="26" fill="#8a8b95" fontSize="10.5" fontFamily="ui-sans-serif,system-ui">shallow sensors respond before deep ones</text>
      {withDepth.map((s, i) => {
        const ny = nodeY(s.depth_cm), ry = rowY(i), c = col(s.status);
        return (
          <g key={i}>
            <line x1={bx} y1={ny} x2={labelX - 8} y2={ry - 4} stroke="#26262d" />
            {s.status !== "normal" && <circle cx={bx} cy={ny} r="10" fill={c} opacity="0.16" />}
            <circle cx={bx} cy={ny} r="5" fill={c} stroke="#0c0c10" strokeWidth="1.5" />
            <text x={labelX} y={ry - 3} fill="#a7a8b2" fontSize="10.5" fontFamily="ui-sans-serif,system-ui">{s.quantity} · {s.depth_cm}cm</text>
            <text x={labelX} y={ry + 11} fill={s.status === "normal" ? "#e9e9ee" : c} fontSize="11.5" fontFamily="ui-monospace,monospace">{s.value?.toFixed(2)} {s.unit}</text>
          </g>
        );
      })}
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

export default function SlopeDetail() {
  const { id } = useParams();
  const { authFetch } = useAuth();
  const [siteDevices, setSiteDevices] = useState(null);

  // B12_PPK_CROSSPAGE_AUTO: technical rover QA, not an operational slope measurement.
  const [ppkQaSummary, setPpkQaSummary] = useState({state: "loading", result: null});
  useEffect(() => {
    if (id !== "ITB-STAGING-01") { setPpkQaSummary({state: "empty", result: null}); return; }
    let alive = true;
    const params = new URLSearchParams({site_id: id, rover_device_id: "ROVER-B1-02", limit: "2000"});
    authFetch(`/api/v1/ppk/qa/solutions?${params}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`PPK QA HTTP ${response.status}`);
        return summarizeExperimentalPpkQa(await response.json());
      })
      .then((result) => { if (alive) setPpkQaSummary({state: "ok", result}); })
      .catch(() => { if (alive) setPpkQaSummary({state: "error", result: null}); });
    return () => { alive = false; };
  }, [id, authFetch]);


  // Daftar device di site ini (2026-09-20, baru — sebelumnya halaman
  // detail tidak pernah menampilkan device fisik apa yang ada di lokasi
  // ini). Reuse /api/v1/devices (endpoint yang sama dipakai halaman
  // Devices), difilter client-side by site_id.
  useEffect(() => {
    let alive = true;
    authFetch("/api/v1/devices")
      .then((r) => r.json())
      .then((body) => { if (alive) setSiteDevices((body.devices || []).filter((d) => d.site_id === id)); })
      .catch(() => {});
    return () => { alive = false; };
  }, [id, authFetch]);

  const navigate = useNavigate();
  const { overview, recent, variant } = useStore((s) => ({ overview: s.overview, recent: s.recent, variant: s.variant }));
  const pal = getPalette(variant);
  const operationalReady = overview?.validation?.operational_ready === true;
  const [hours, setHours] = useState(24);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [data, setData] = useState(null);
  const [device, setDevice] = useState(null); // isolated sensor group, or null
  const [selectedRover, setSelectedRover] = useState(null);
  const [detailView, setDetailView] = useState("charts");
  const [tableNow, setTableNow] = useState(() => Date.now());

  useEffect(() => {
    let alive = true;
    let timer = null;
    let controller = null;
    let retryCount = 0;

    const POLL_MS = 8000;
    const MAX_BACKOFF_MS = 60000;

    // Kalau customFrom DAN customTo keduanya diisi -> kirim rentang eksplisit.
    // Kalau tidak -> preset/live range dan polling completion-scheduled.
    const fromIso = customFrom ? new Date(customFrom).toISOString() : null;
    const toIso = customTo ? new Date(customTo).toISOString() : null;
    const shouldPoll = !(fromIso && toIso);

    const schedule = (delayMs) => {
      if (!alive || !shouldPoll) return;

      if (timer !== null) {
        clearTimeout(timer);
      }

      timer = setTimeout(() => {
        timer = null;
        load();
      }, Math.max(0, delayMs));
    };

    const fallbackBackoff = () => {
      const base = Math.min(
        MAX_BACKOFF_MS,
        POLL_MS * (2 ** retryCount),
      );

      retryCount = Math.min(retryCount + 1, 3);

      return base + Math.floor(Math.random() * 1000);
    };

    const load = async () => {
      if (!alive || controller !== null) return;

      controller = new AbortController();

      try {
        const d = await getSite(
          id,
          hours,
          fromIso,
          toIso,
          { signal: controller.signal, authFetch },
        );

        if (!alive) return;

        setData(d);
        setTableNow(Date.now());

        retryCount = 0;
        schedule(POLL_MS);
      } catch (error) {
        if (!alive || error?.name === "AbortError") return;

        // Historical custom ranges intentionally remain one-shot.
        if (!shouldPoll) return;

        if (
          error?.status === 429 &&
          Number.isFinite(error?.retryAfterMs)
        ) {
          schedule(error.retryAfterMs);
          return;
        }

        // 429 tanpa Retry-After, network failure, dan transient error lain
        // memakai bounded exponential backoff + jitter.
        schedule(fallbackBackoff());
      } finally {
        controller = null;
      }
    };

    // Immediate first request.
    load();

    return () => {
      alive = false;

      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }

      if (controller) {
        controller.abort();
        controller = null;
      }
    };
  }, [id, hours, customFrom, customTo, authFetch]);

  const name = overview?.slopes.find((s) => s.site_id === id)?.name || id;
  const site = overview?.slopes.find((s) => s.site_id === id);
  const live = useMemo(
    () => (recent[id] || []).filter((e) => new Date(e.t) > new Date(Date.now() - hours * 3_600_000)),
    [recent, id, hours],
  );

  // merge historical series + live tail into one point-array per quantity
  const byQ = useMemo(() => {
    const m = {};
    for (const s of data?.series || []) m[s.quantity] = { unit: s.unit, pts: s.points.map((p) => [p[0], p[1]]) };
    for (const ev of live) {
      if (ev.value == null) continue;
      if (!m[ev.quantity]) m[ev.quantity] = { unit: ev.unit, pts: [] };
      m[ev.quantity].pts.push([ev.t, ev.value]);
    }
    for (const q in m) m[q].pts.sort((a, b) => new Date(a[0]) - new Date(b[0]));
    return m;
  }, [data, live]);

  const Q = (q) => (byQ[q] ? byQ[q].pts : []);
  const roverIds = useMemo(
    () => [...new Set((data?.device_series || [])
      .filter((s) => ["displacement", "disp_e", "disp_n", "disp_u"].includes(s.quantity))
      .map((s) => s.device_id))].sort(),
    [data],
  );
  useEffect(() => {
    if (!roverIds.length) { setSelectedRover(null); return; }
    if (!selectedRover || !roverIds.includes(selectedRover)) setSelectedRover(roverIds[0]);
  }, [roverIds, selectedRover]);
  const QD = (q) => {
    if (!selectedRover) return Q(q);
    const series = (data?.device_series || []).find((s) => s.device_id === selectedRover && s.quantity === q);
    return series?.points || [];
  };

  const derived = useMemo(() => {
    const displacement = selectedRover
      ? ((data?.device_series || []).find((s) => s.device_id === selectedRover && s.quantity === "displacement")?.points || [])
      : Q("displacement");
    const disp = smoothPts(displacement);
    const velocity = ratePerDay(disp, 0);
    const acceleration = ratePerDay(smoothPts(velocity), null);
    return { disp: displacement, velocity, acceleration };
  }, [byQ, data, selectedRover]);

  if (!data) return <div className="loading">Loading {name}…</div>;

  const th = data.thresholds || {};
  const STATUS = pal.marker;      // concrete status colours for the canvas charts
  const BAND = pal.band;          // rgba band fills
  const col = (q) => pal.line[q] || pal.lineDefault;

  // device-isolate opacity: dim series not in the selected group
  const op = (q) => (device === null || GROUP_OF[q] === device ? 1 : 0.14);
  const groupStatus = (g) => {
    if (!operationalReady && g.key === "gnss") return "unknown";
    const sts = g.quantities.map((q) => statusFor(th[q], last(Q(q))));
    return sts.includes("bahaya") ? "bahaya" : sts.includes("siaga") ? "siaga" : "normal";
  };
  const presentGroups = GROUPS.filter((g) => g.quantities.some((q) => Q(q).length));

  // ---- stat-card scalars ----
  const dispNow = last(QD("displacement"));
  const dispStatus = operationalReady ? statusFor(th.displacement, dispNow) : "unknown";
  const tiltNow = last(Q("tilt_x"));
  const velNow = last(derived.velocity);
  const velStatus = operationalReady ? statusFor(VEL_TH, velNow) : "unknown";
  // FIX (2026-09-20): pore_pressure dihapus — tidak ada piezometer di
  // hardware sistem ini (cuma GNSS + accelerometer). Stat card + panel
  // "Rainfall vs Pore Water Pressure" yang memakainya juga dihapus di
  // bawah, bukan cuma dibiarkan menampilkan "—" selamanya.
  // FIX (2026-09-20): rainfall trailing-24h dulu diintegrasikan dari
  // quantity "rainfall" (rain gauge fisik) — sensor itu TIDAK ADA di
  // hardware sistem ini (dikonfirmasi baca langsung API Spec, cuma GNSS +
  // accelerometer). Diganti pakai rainfall_24h_external (Open-Meteo,
  // sudah kumulatif dari server, tidak perlu diintegrasikan ulang di sini).
  const rain24 = last(Q("rainfall_24h_external"));
  const rain72 = last(Q("rainfall_72h_external"));
  const weatherRain = gapAware(Q("rainfall_external"));
  const weatherRain24 = gapAware(Q("rainfall_24h_external"));
  const weatherRain72 = gapAware(Q("rainfall_72h_external"));
  const weatherTemp = gapAware(Q("temperature_external"));
  const weatherHumidity = gapAware(Q("humidity_external"));
  const weatherRainMax = Math.max(10, Math.ceil(Math.max(
    maxOf(weatherRain, 0), maxOf(weatherRain24, 0), maxOf(weatherRain72, 0),
  ) / 10) * 10);
  const tempVals = vals(weatherTemp);
  const weatherTempMin = tempVals.length ? Math.floor(Math.min(...tempVals) - 2) : 15;
  const weatherTempMax = tempVals.length ? Math.ceil(Math.max(...tempVals) + 2) : 40;
  const disp24 = dispNow != null ? dispNow - (valueAt(QD("displacement"), Date.now() - DAY) ?? dispNow) : null;

  // ---- inverse-velocity estimate (suppressed if the slope is not accelerating) ----
  const est = operationalReady ? estimateFailure(QD("displacement")) : null;

  // ---- per-panel dynamic ranges ----
  const dispMax = Math.max(15, Math.ceil(maxOf(QD("displacement"), 12) * 1.1));
  const dispMin = Math.min(-5, Math.floor(minOf(QD("disp_u"), -3)));
  const tiltMax = Math.max(3, Math.ceil(maxOf(Q("tilt_x"), 2.4) * 1.1));
  const rainMax = Math.max(80, Math.ceil(maxOf(Q("rainfall"), 60) / 10) * 10);
  const velMax = Math.max(20, Math.ceil(maxOf(derived.velocity, 12) / 2) * 2);
  const ppaMax = Math.max(1, Math.ceil(Math.max(maxOf(Q("ppa"), 0), maxOf(Q("ppa_mpu9250"), 0)) * 1.2 * 10) / 10);
  const ppvMax = Math.max(10, Math.ceil(Math.max(maxOf(Q("ppv"), 0), maxOf(Q("ppv_mpu9250"), 0)) * 1.2 / 10) * 10);

  const readout = (v, unit, status) => (
    <span style={{ color: status === "bahaya" ? "var(--bahaya)" : status === "siaga" ? "var(--siaga)" : "var(--ink)" }}>
      {fmt(v)} {unit}
    </span>
  );

  const hasDisplacementSeries = ["displacement", "disp_e", "disp_n", "disp_u"].some((q) => QD(q).length > 0);
  const hasTiltSeries = ["tilt_x", "tilt_y"].some((q) => Q(q).length > 0);
  const hasBlastSeries = ["ppa", "ppa_mpu9250", "ppv", "ppv_mpu9250"].some((q) => Q(q).length > 0);
  const hasVelocitySeries = operationalReady && (derived.velocity.length > 0 || derived.acceleration.length > 0);

  const formatWeather = (value, digits = 1) => {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    return Number.isFinite(n) ? new Intl.NumberFormat("id-ID", { maximumFractionDigits: digits }).format(n) : "—";
  };

  return (
    <div className="l2 l2detail">
      <div role="status" style={{background:"#35240c",color:"#ffe7ac",padding:"8px 12px",border:"1px solid #b88b43"}}>DATA BELUM TERVALIDASI LAPANGAN. Seri displacement historis sebelum persetujuan baseline tidak ditampilkan; status bukan jaminan keselamatan.</div>
      {id === "ITB-STAGING-01" && ppkQaSummary.state === "ok" && ppkQaSummary.result?.total > 0 && (
        <section aria-label="Experimental PPK QA summary" style={{border:"1px solid #dbe3eb",borderRadius:10,padding:"12px 16px",margin:"12px 0",background:"var(--surface,#fff)"}}>
          <strong>PPK experimental QA · ROVER-B1-02</strong>
          <div style={{display:"flex",flexWrap:"wrap",gap:16,marginTop:8}}>
            <span>FIX <b>{ppkQaSummary.result.counts.FIX}</b></span>
            <span>FLOAT <b>{ppkQaSummary.result.counts.FLOAT}</b></span>
            <span>SINGLE <b>{ppkQaSummary.result.counts.SINGLE}</b></span>
            <span>Total <b>{ppkQaSummary.result.total}</b></span>
          </div>
          <small>PROVISIONAL_SPP · unvalidated · hasil riset, bukan displacement atau dasar alarm.</small>
          <button style={{marginLeft:12}} onClick={() => navigate("/ppk")}>Detail QA →</button>
        </section>
      )}
      <div className="l2head">
        <div className="crumb">
          <button onClick={() => navigate("/")}>← Overview</button><span>/</span>
          <span className="cur">{name}</span>
        </div>
        <span className={"badge " + (operationalReady ? data.status : "unknown")}>
          <span className="pip" />
          {operationalReady ? LABEL[data.status] : LABEL.unknown}
        </span>
        <span className="action2">
          {operationalReady ? data.action : "Technical telemetry only · production validation pending"}
        </span>
        {site && (
          <span className="site-meta">{id} · {site.lat?.toFixed(4)}, {site.lon?.toFixed(4)}</span>
        )}
        <div className="tabs" role="group" aria-label="Time range">
          {HOURS.map(([lbl, h]) => (
            <button key={h} className={h === hours ? "on" : ""} onClick={() => { setHours(h); setCustomFrom(""); setCustomTo(""); }}>{lbl}</button>
          ))}
          {/* Rentang kustom (2026-09-22, revisi — start SAJA sebelumnya,
              sekarang start+end penuh sesuai permintaan). Tidak perlu
              polling 8s untuk rentang ini (lihat useEffect) karena data
              masa lalu tidak berubah. */}
          <span className="tabs-custom-range">
            <input
              type="datetime-local"
              className={"tabs-custom" + (customFrom ? " on" : "")}
              value={customFrom}
              max={customTo || undefined}
              onChange={(e) => setCustomFrom(e.target.value)}
              title="Dari"
            />
            <span className="tabs-custom-sep">–</span>
            <input
              type="datetime-local"
              className={"tabs-custom" + (customTo ? " on" : "")}
              value={customTo}
              min={customFrom || undefined}
              max={new Date(Date.now() - Date.now() % 60000).toISOString().slice(0, 16)}
              onChange={(e) => setCustomTo(e.target.value)}
              title="Sampai"
            />
          </span>
        </div>
      </div>

      <div className="detail-view-switch" role="group" aria-label="Detail view">
        <button className={detailView === "charts" ? "on" : ""} onClick={() => setDetailView("charts")}>Grafik</button>
        <button className={detailView === "table" ? "on" : ""} onClick={() => setDetailView("table")}>Data Table</button>
      </div>

      {detailView === "table" ? (
        <MeasurementTable
          siteId={id}
          devices={siteDevices || []}
          fromTime={
            customFrom && customTo
              ? new Date(customFrom).toISOString()
              : new Date(tableNow - hours * 60 * 60 * 1000).toISOString()
          }
          toTime={
            customFrom && customTo
              ? new Date(customTo).toISOString()
              : new Date(tableNow).toISOString()
          }
        />
      ) : (<>

      {/* device-isolate row */}
      <div className="dev-row">
        <span className="dev-eyebrow">Devices</span>
        <button className={"dev-pill" + (device === null ? " on" : "")} onClick={() => setDevice(null)}>All series</button>
        {presentGroups.map((g) => {
          const st = groupStatus(g);
          return (
            <button key={g.key} className={"dev-pill" + (device === g.key ? " on" : "")} onClick={() => setDevice((d) => (d === g.key ? null : g.key))}>
              <span
                className="dev-dot"
                style={{
                  background:
                    st === "bahaya"
                      ? "var(--bahaya)"
                      : st === "siaga"
                        ? "var(--siaga)"
                        : st === "unknown"
                          ? "var(--ink-3)"
                          : "var(--ok)",
                }}
              />
              {g.label}
            </button>
          );
        })}
        <span className="dev-hint">
          {device === null ? "Select a device to isolate its series."
            : device === "soil" ? "Soil-moisture probe — shown in the cross-section, no time-series on this grid."
              : ""}
        </span>
      </div>

      {/* stat cards */}
      <div className="statcard-row">
        {hasDisplacementSeries && <StatCard label={`3D resultant displacement${selectedRover ? ` · ${selectedRover}` : ""}`} value={fmt(dispNow)} sub="mm · technical PPK · UNVALIDATED" status={dispStatus} />}
        {hasTiltSeries && <StatCard label="Tilt X (ADXL355)" value={fmt(tiltNow)} sub="deg · saat ledakan terakhir (bukan real-time)" status={statusFor(th.tilt_x, tiltNow)} />}
        {hasVelocitySeries && <StatCard
          label="Slope velocity"
          value={fmt(velNow, 1)}
          sub={`mm/day · derived QA only · 24 h Δ ${disp24 != null ? (disp24 >= 0 ? "+" : "") + fmt(disp24, 1) : "—"} mm`}
          status={velStatus}
        />}
        <StatCard label="Rainfall, trailing 24 h" value={fmt(rain24, 0)} sub="mm · Open-Meteo (bukan sensor lapangan)" status="normal" />
      </div>

      {/* analytics grid */}
      <div className="analytics-grid">
        {hasDisplacementSeries && (
        <Panel title="GNSS 3D Displacement" sub="technical PPK · UNVALIDATED" right={readout(dispNow, "mm", dispStatus)}>
          <div className="panel-body">
            {roverIds.length > 1 && (
              <div className="ppk-rover-switch" role="group" aria-label="PPK rover series">
                {roverIds.map((roverId) => (
                  <button key={roverId} className={selectedRover === roverId ? "on" : ""} onClick={() => setSelectedRover(roverId)}>{roverId}</button>
                ))}
              </div>
            )}
            <Legend items={[
              { label: "3D resultant", color: col("displacement") },
              { label: "ΔX east", color: col("disp_e"), dash: "dashed" },
              { label: "ΔY north", color: col("disp_n"), dash: "dotted" },
              { label: "ΔZ vertical", color: col("disp_u"), dash: "dotted" },
              ...(operationalReady
                ? [{ label: "10.00 mm limit", color: STATUS.bahaya, dash: "dashed" }]
                : []),
            ]} />
            <PanelChart height={232}
              left={{ name: "mm", min: dispMin, max: dispMax }}
              series={[
                { name: "ΔZ vertical", data: QD("disp_u"), color: col("disp_u"), width: 1.4, dash: "dotted", opacity: op("disp_u") },
                { name: "ΔY north", data: QD("disp_n"), color: col("disp_n"), width: 1.4, dash: "dotted", opacity: op("disp_n") },
                { name: "ΔX east", data: QD("disp_e"), color: col("disp_e"), width: 1.6, dash: "dashed", opacity: op("disp_e") },
                { name: "3D resultant", data: QD("displacement"), color: col("displacement"), width: 2.4, z: 3, opacity: op("displacement") },
              ]}
              bands={operationalReady
                ? [{ from: th.displacement?.bahaya ?? 10, to: dispMax, color: BAND.bahaya }]
                : []}
              hlines={operationalReady
                ? [{ y: th.displacement?.bahaya ?? 10, color: STATUS.bahaya, label: (th.displacement?.bahaya ?? 10).toFixed(2) }]
                : []}
            />
          </div>
        </Panel>
        )}

        {hasTiltSeries && (
        <Panel title="Accelerometer Tilt" sub="ADXL355 · derived · UNVERIFIED" right={readout(tiltNow, "deg", statusFor(th.tilt_x, tiltNow))}>
          <div className="panel-body">
            <Legend items={[
              { label: "Tilt X · deg", color: col("tilt_x") },
              { label: "Tilt Y · deg", color: col("tilt_y"), dash: "dashed" },
            ]} />
            <PanelChart height={232}
              left={{ name: "deg", min: 0, max: tiltMax }}
              series={[
                { name: "Tilt Y", data: Q("tilt_y"), color: col("tilt_y"), width: 1.6, dash: "dashed", opacity: op("tilt_y") },
                { name: "Tilt X", data: Q("tilt_x"), color: col("tilt_x"), width: 2.4, z: 3, opacity: op("tilt_x") },
              ]}
              bands={[
                { from: th.tilt_x?.siaga ?? 1.5, to: th.tilt_x?.bahaya ?? 2.25, color: BAND.siaga },
                { from: th.tilt_x?.bahaya ?? 2.25, to: tiltMax, color: BAND.bahaya },
              ]}
            />
            <div className="wx-chart-note">Tilt is derived from acceleration; it is not gyroscope/angular-rate data.</div>
          </div>
        </Panel>
        )}

        {hasBlastSeries && (
        <Panel title="Blast Vibration Metrics" sub="technical event features · UNVALIDATED" right={readout(last(Q("ppv")), "mm/s", "normal")}>
          <div className="panel-body">
            <Legend items={[
              { label: "ADXL355 PPA · g", color: col("ppa") },
              { label: "MPU9250 PPA · g", color: col("ppa_mpu9250"), dash: "dashed" },
              { label: "ADXL355 PPV · mm/s", color: col("ppv") },
              { label: "MPU9250 PPV · mm/s", color: col("ppv_mpu9250"), dash: "dashed" },
            ]} />
            <PanelChart height={232}
              left={{ name: "g", min: 0, max: ppaMax }}
              right={{ name: "mm/s", min: 0, max: ppvMax }}
              series={[
                { name: "MPU9250 PPA", data: Q("ppa_mpu9250"), color: col("ppa_mpu9250"), width: 1.5, dash: "dashed", opacity: op("ppa_mpu9250") },
                { name: "ADXL355 PPA", data: Q("ppa"), color: col("ppa"), width: 2.2, z: 3, opacity: op("ppa") },
                { name: "MPU9250 PPV", data: Q("ppv_mpu9250"), color: col("ppv_mpu9250"), width: 1.5, dash: "dashed", axis: 1, opacity: op("ppv_mpu9250") },
                { name: "ADXL355 PPV", data: Q("ppv"), color: col("ppv"), width: 2.2, axis: 1, z: 3, opacity: op("ppv") },
              ]}
            />
            <div className="wx-chart-note">PPA/PPV are technical features from uploaded acceleration windows. No regulatory/compliance threshold or field-safety claim is applied.</div>
          </div>
        </Panel>
        )}

        {!operationalReady ? null : est ? (
          <Panel title="Time to Failure" tag="estimate">
            <TimeToFailure estimate={est} />
          </Panel>
        ) : (
          <Panel title="Time to Failure" tag="stable">
            <div className="tf-stable">Slope is not accelerating. No failure estimate is shown — an inverse-velocity projection on a stable slope would be misleading.</div>
          </Panel>
        )}

        {hasVelocitySeries && (
        <Panel
          title="Slope Velocity & Acceleration"
          sub={operationalReady ? "derived from GNSS resultant" : "derived QA telemetry · UNVALIDATED"}
          right={readout(velNow, "mm/day", velStatus)}
        >
          <div className="panel-body">
            <Legend items={[
              { label: "Velocity · mm/day", color: col("velocity") },
              { label: "Acceleration · mm/day²", color: col("acceleration"), dash: "dashed" },
              ...(operationalReady
                ? [{ label: "Tertiary creep", color: BAND.bahaya, kind: "box" }]
                : []),
            ]} />
            <PanelChart height={232}
              left={{ name: "mm/day", min: 0, max: velMax }}
              right={{ name: "mm/day²", min: 0, max: 24 }}
              series={[
                { name: "Acceleration", data: derived.acceleration, color: col("acceleration"), width: 1.6, dash: "dashed", axis: 1, opacity: op("acceleration") },
                { name: "Velocity", data: derived.velocity, color: col("velocity"), width: 2.4, z: 3, opacity: op("velocity") },
              ]}
              bands={operationalReady
                ? [
                    { from: VEL_TH.siaga, to: VEL_TH.bahaya, color: BAND.siaga },
                    { from: VEL_TH.bahaya, to: velMax, color: BAND.bahaya },
                  ]
                : []}
            />
          </div>
        </Panel>
        )}

        {(weatherRain.length > 0 || weatherTemp.length > 0) && (
          <>
            <Panel title="External Precipitation" sub="Open-Meteo · interval bars + rolling accumulation">
              <div className="panel-body">
                <Legend items={[
                  { label: "Precipitation · mm", color: col("rainfall_external"), kind: "bar" },
                  { label: "Rolling 24h · mm", color: col("rainfall_24h_external") },
                  { label: "Rolling 72h · mm", color: col("rainfall_72h_external"), dash: "dashed" },
                ]} />
                <PanelChart
                  height={232}
                  left={{ name: "mm", min: 0, max: weatherRainMax }}
                  series={[
                    { name: "Precipitation", type: "bar", data: weatherRain, color: col("rainfall_external"), barWidth: 10, barMaxWidth: 12, opacity: 0.82, z: 1 },
                    { name: "Rolling 24h", data: weatherRain24, color: col("rainfall_24h_external"), width: 2.4, showSymbol: true, symbolSize: 5, z: 3 },
                    { name: "Rolling 72h", data: weatherRain72, color: col("rainfall_72h_external"), width: 2.0, dash: "dashed", showSymbol: true, symbolSize: 5, z: 2 },
                  ]}
                />
                <div className="wx-chart-note">Missing/incomplete windows are unavailable; chart gaps are not interpolated. Source: Open-Meteo (external) · validation: not_applicable · CC BY 4.0.</div>
              </div>
            </Panel>

            <Panel title="External Temperature & Humidity" sub="Open-Meteo">
              <div className="panel-body">
                <Legend items={[
                  { label: "Temperature · °C", color: col("temperature_external") },
                  { label: "Humidity · %", color: col("humidity_external"), dash: "dashed" },
                ]} />
                <PanelChart
                  height={232}
                  left={{ name: "°C", min: weatherTempMin, max: weatherTempMax }}
                  right={{ name: "%", min: 0, max: 100 }}
                  series={[
                    { name: "Temperature", data: weatherTemp, color: col("temperature_external"), width: 2.2 },
                    { name: "Humidity", data: weatherHumidity, color: col("humidity_external"), width: 1.8, dash: "dashed", axis: 1 },
                  ]}
                />
              </div>
            </Panel>
          </>
        )}

        {/* FIX (2026-09-20): panel ini dulu "Slope Cross-section" (diagram
            sensor bawah tanah) — data.sensors SELALU [] (tidak ada
            piezometer/soil-moisture berkedalaman di hardware sistem ini),
            jadi panelnya selalu kosong tanpa penjelasan. Diganti jadi
            panel jujur yang menyatakan sensor apa yang BENAR-BENAR ada. */}
        <Panel title="Sensor Coverage" sub="hardware terpasang">
          <div className="sensor-coverage" style={{ padding: "12px 18px 14px" }}>
            <div className="sc-row"><span className="sc-dot sc-on" />GNSS RTK (ZED-F9P-15B) — displacement</div>
            <div className="sc-row"><span className="sc-dot sc-on" />Accelerometer (ADXL355 / MPU9250) — tilt &amp; vibrasi</div>
            <div className="sc-row"><span className="sc-dot sc-off" />Piezometer / soil moisture — tidak terpasang</div>
            <div className="sc-row"><span className="sc-dot sc-off" />Rain gauge lapangan — tidak terpasang (curah hujan dari Open-Meteo)</div>
          </div>
        </Panel>

        {/* Devices di site ini (2026-09-20, baru) */}
        <Panel title="Devices" sub={id}>
          <div className="sensor-coverage" style={{ padding: "12px 18px 14px" }}>
            {!siteDevices && <div className="sc-row">Memuat…</div>}
            {siteDevices && siteDevices.length === 0 && <div className="sc-row">Belum ada device terdaftar di site ini.</div>}
            {siteDevices && siteDevices.map((d) => (
              <div key={d.device_id} className="sc-row">
                <span className={"sc-dot " + (d.online ? "sc-on" : "sc-off")} />
                {d.device_id} ({d.device_type}) — {d.online ? "online" : "offline"}
              </div>
            ))}
          </div>
        </Panel>

        {/* External Weather (2026-09-20, baru) — Overview.jsx sekarang
            cuma tampilkan maks 2 site terdekat dari lokasi browser
            pengguna; site LAINNYA (termasuk mungkin site ini) datanya
            tetap ada, ditampilkan di sini. Data mengalir lewat query yang
            sama (`series`, semua quantity, tidak difilter) — tidak perlu
            fetch tambahan. */}
        {(Q("rainfall_external").length > 0 || Q("temperature_external").length > 0) && (
          <div data-b12="B12_SLOPE_DETAIL_WEATHER_FULL_SPAN" style={{ gridColumn: "1 / -1", minWidth: 0 }}>
          <Panel title="External Weather" sub="Open-Meteo">
            <div className="sensor-coverage" style={{ padding: "14px 18px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: "8px 22px", alignItems: "center" }} data-b12="B12_SLOPE_BOTTOM_COMPACT_V1">
              <div className="sc-row">Rainfall: <b>{formatWeather(last(Q("rainfall_external")))} mm</b></div>
              <div className="sc-row">24h rainfall: <b>{formatWeather(rain24)} mm</b></div>
              <div className="sc-row">72h rainfall: <b>{formatWeather(rain72)} mm</b></div>
              <div className="sc-row">Temperature: <b>{formatWeather(last(Q("temperature_external")))} °C</b></div>
              <div className="sc-row">Humidity: <b>{formatWeather(last(Q("humidity_external")), 0)} %</b></div>
              <div className="sc-row" style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 4 }}>Weather data by Open-Meteo.com (CC BY 4.0)</div>
            </div>
          </Panel>
          </div>
        )}
      </div>
      </>)}

    </div>
  );
}
