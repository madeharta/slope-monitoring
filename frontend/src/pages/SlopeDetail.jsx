import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useStore } from "../store";
import { getSite } from "../api";
import { getPalette } from "../theme";
import PanelChart from "../components/PanelChart.jsx";
import TimeToFailure, { estimateFailure } from "../components/TimeToFailure.jsx";

const LABEL = { bahaya: "Bahaya", siaga: "Siaga", normal: "Normal" };
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
  tilt_x: "accel", tilt_y: "accel", vibration: "accel",
  rainfall: "rain", pore_pressure: "piezo", suction: "piezo", soil_moisture: "soil",
};
const GROUPS = [
  { key: "gnss", label: "GNSS rover", quantities: ["displacement"] },
  { key: "accel", label: "Accelerometer", quantities: ["tilt_x", "tilt_y"] },
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

export default function SlopeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { overview, recent, variant } = useStore((s) => ({ overview: s.overview, recent: s.recent, variant: s.variant }));
  const pal = getPalette(variant);
  const [hours, setHours] = useState(24);
  const [data, setData] = useState(null);
  const [device, setDevice] = useState(null); // isolated sensor group, or null

  useEffect(() => {
    let alive = true;
    const load = () => getSite(id, hours).then((d) => alive && setData(d)).catch(() => {});
    load();
    const t = setInterval(load, 8000);
    return () => { alive = false; clearInterval(t); };
  }, [id, hours]);

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

  const derived = useMemo(() => {
    const disp = smoothPts(Q("displacement"));
    const velocity = ratePerDay(disp, 0);
    const acceleration = ratePerDay(smoothPts(velocity), null);
    return { disp: Q("displacement"), velocity, acceleration };
  }, [byQ]);

  if (!data) return <div className="loading">Loading {name}…</div>;

  const th = data.thresholds || {};
  const STATUS = pal.marker;      // concrete status colours for the canvas charts
  const BAND = pal.band;          // rgba band fills
  const col = (q) => pal.line[q] || pal.lineDefault;

  // device-isolate opacity: dim series not in the selected group
  const op = (q) => (device === null || GROUP_OF[q] === device ? 1 : 0.14);
  const groupStatus = (g) => {
    const sts = g.quantities.map((q) => statusFor(th[q], last(Q(q))));
    return sts.includes("bahaya") ? "bahaya" : sts.includes("siaga") ? "siaga" : "normal";
  };
  const presentGroups = GROUPS.filter((g) => g.quantities.some((q) => Q(q).length));

  // ---- stat-card scalars ----
  const dispNow = last(Q("displacement"));
  const dispStatus = statusFor(th.displacement, dispNow);
  const tiltNow = last(Q("tilt_x"));
  const velNow = last(derived.velocity);
  const velStatus = statusFor(VEL_TH, velNow);
  const poreNow = last(Q("pore_pressure"));
  const poreStatus = statusFor(th.pore_pressure, poreNow);
  const rain24 = accumulate(Q("rainfall").filter((p) => new Date(p[0]).getTime() >= Date.now() - DAY));
  const disp24 = dispNow != null ? dispNow - (valueAt(Q("displacement"), Date.now() - DAY) ?? dispNow) : null;

  // ---- inverse-velocity estimate (suppressed if the slope is not accelerating) ----
  const est = estimateFailure(Q("displacement"));

  // ---- per-panel dynamic ranges ----
  const dispMax = Math.max(15, Math.ceil(maxOf(Q("displacement"), 12) * 1.1));
  const dispMin = Math.min(-5, Math.floor(minOf(Q("disp_u"), -3)));
  const tiltMax = Math.max(3, Math.ceil(maxOf(Q("tilt_x"), 2.4) * 1.1));
  const rainMax = Math.max(80, Math.ceil(maxOf(Q("rainfall"), 60) / 10) * 10);
  const velMax = Math.max(20, Math.ceil(maxOf(derived.velocity, 12) / 2) * 2);

  // vibration spikes -> anomaly markers (a few most-recent)
  const vlines = Q("vibration").filter((p) => p[1] != null && p[1] > 20).slice(-3)
    .map((p) => ({ x: p[0], color: STATUS.siaga, label: `${p[1].toFixed(1)} Hz` }));

  const readout = (v, unit, status) => (
    <span style={{ color: status === "bahaya" ? "var(--bahaya)" : status === "siaga" ? "var(--siaga)" : "var(--ink)" }}>
      {fmt(v)} {unit}
    </span>
  );

  return (
    <div className="l2 l2detail">
      <div className="l2head">
        <div className="crumb">
          <button onClick={() => navigate("/")}>← Overview</button><span>/</span>
          <span className="cur">{name}</span>
        </div>
        <span className={"badge " + data.status}><span className="pip" />{LABEL[data.status]}</span>
        <span className="action2">{data.action}</span>
        {site && (
          <span className="site-meta">{id} · {site.lat?.toFixed(4)}, {site.lon?.toFixed(4)}</span>
        )}
        <div className="tabs" role="group" aria-label="Time range">
          {HOURS.map(([lbl, h]) => (
            <button key={h} className={h === hours ? "on" : ""} onClick={() => setHours(h)}>{lbl}</button>
          ))}
        </div>
      </div>

      {/* device-isolate row */}
      <div className="dev-row">
        <span className="dev-eyebrow">Devices</span>
        <button className={"dev-pill" + (device === null ? " on" : "")} onClick={() => setDevice(null)}>All series</button>
        {presentGroups.map((g) => {
          const st = groupStatus(g);
          return (
            <button key={g.key} className={"dev-pill" + (device === g.key ? " on" : "")} onClick={() => setDevice((d) => (d === g.key ? null : g.key))}>
              <span className="dev-dot" style={{ background: st === "bahaya" ? "var(--bahaya)" : st === "siaga" ? "var(--siaga)" : "var(--ok)" }} />
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
        <StatCard label="3D resultant displacement" value={fmt(dispNow)} sub="mm · threshold 10.00 mm" status={dispStatus} />
        <StatCard label="Tilt X (ADXL355)" value={fmt(tiltNow)} sub="deg · siaga 1.50 / bahaya 2.25" status={statusFor(th.tilt_x, tiltNow)} />
        <StatCard label="Slope velocity" value={fmt(velNow, 1)} sub={`mm/day · 24 h Δ ${disp24 != null ? (disp24 >= 0 ? "+" : "") + fmt(disp24, 1) : "—"} mm`} status={velStatus} />
        <StatCard label="Pore water pressure" value={fmt(poreNow, 1)} sub="kPa @ 100cm · siaga 20.0" status={poreStatus} />
        <StatCard label="Rainfall, trailing 24 h" value={fmt(rain24, 0)} sub="mm accumulated · rain gauge" status="normal" />
      </div>

      {/* analytics grid */}
      <div className="analytics-grid">
        <Panel title="GNSS 3D Displacement" sub="mm vs time" right={readout(dispNow, "mm", dispStatus)}>
          <div className="panel-body">
            <Legend items={[
              { label: "3D resultant", color: col("displacement") },
              { label: "ΔX east", color: col("disp_e"), dash: "dashed" },
              { label: "ΔY north", color: col("disp_n"), dash: "dotted" },
              { label: "ΔZ vertical", color: col("disp_u"), dash: "dotted" },
              { label: "10.00 mm limit", color: STATUS.bahaya, dash: "dashed" },
            ]} />
            <PanelChart height={232}
              left={{ name: "mm", min: dispMin, max: dispMax }}
              series={[
                { name: "ΔZ vertical", data: Q("disp_u"), color: col("disp_u"), width: 1.4, dash: "dotted", opacity: op("disp_u") },
                { name: "ΔY north", data: Q("disp_n"), color: col("disp_n"), width: 1.4, dash: "dotted", opacity: op("disp_n") },
                { name: "ΔX east", data: Q("disp_e"), color: col("disp_e"), width: 1.6, dash: "dashed", opacity: op("disp_e") },
                { name: "3D resultant", data: Q("displacement"), color: col("displacement"), width: 2.4, z: 3, opacity: op("displacement") },
              ]}
              bands={[{ from: th.displacement?.bahaya ?? 10, to: dispMax, color: BAND.bahaya }]}
              hlines={[{ y: th.displacement?.bahaya ?? 10, color: STATUS.bahaya, label: (th.displacement?.bahaya ?? 10).toFixed(2) }]}
            />
          </div>
        </Panel>

        <Panel title="Accelerometer Tilt & Micro-vibration" sub="ADXL355 / MPU9025" right={readout(tiltNow, "deg", statusFor(th.tilt_x, tiltNow))}>
          <div className="panel-body">
            <Legend items={[
              { label: "Tilt X · deg", color: col("tilt_x") },
              { label: "Tilt Y · deg", color: col("tilt_y"), dash: "dashed" },
              { label: "Vibration · Hz", color: col("vibration"), kind: "bar" },
              { label: "Anomaly", color: STATUS.siaga, dash: "dashed" },
            ]} />
            <PanelChart height={232}
              left={{ name: "deg", min: 0, max: tiltMax }}
              right={{ name: "Hz", min: 0, max: 40 }}
              series={[
                { name: "Vibration", data: Q("vibration"), color: col("vibration"), width: 1, area: true, axis: 1, opacity: op("vibration") },
                { name: "Tilt Y", data: Q("tilt_y"), color: col("tilt_y"), width: 1.6, dash: "dashed", opacity: op("tilt_y") },
                { name: "Tilt X", data: Q("tilt_x"), color: col("tilt_x"), width: 2.4, z: 3, opacity: op("tilt_x") },
              ]}
              bands={[
                { from: th.tilt_x?.siaga ?? 1.5, to: th.tilt_x?.bahaya ?? 2.25, color: BAND.siaga },
                { from: th.tilt_x?.bahaya ?? 2.25, to: tiltMax, color: BAND.bahaya },
              ]}
              vlines={vlines}
            />
          </div>
        </Panel>

        {est ? (
          <Panel title="Time to Failure" tag="estimate" style={{ gridColumn: "3", gridRow: "1" }}>
            <TimeToFailure estimate={est} />
          </Panel>
        ) : (
          <Panel title="Time to Failure" tag="stable" style={{ gridColumn: "3", gridRow: "1" }}>
            <div className="tf-stable">Slope is not accelerating. No failure estimate is shown — an inverse-velocity projection on a stable slope would be misleading.</div>
          </Panel>
        )}

        <Panel title="Rainfall vs Pore Water Pressure" sub="trigger correlation" right={readout(poreNow, "kPa", poreStatus)}>
          <div className="panel-body">
            <Legend items={[
              { label: "Rain gauge · mm/h", color: pal.rainBar, kind: "bar" },
              { label: "Piezometer · kPa", color: col("pore_pressure") },
              { label: "Pore-pressure bands", color: BAND.siaga, kind: "box" },
            ]} />
            <PanelChart height={232}
              left={{ name: "mm/h", min: 0, max: rainMax }}
              right={{ name: "kPa", min: 0, max: 40 }}
              series={[
                { name: "Rainfall", type: "bar", data: Q("rainfall"), color: pal.rainBar, barWidth: "60%", opacity: op("rainfall") },
                { name: "Pore pressure", data: Q("pore_pressure"), color: col("pore_pressure"), width: 2.2, axis: 1, z: 3, opacity: op("pore_pressure") },
              ]}
              bands={[
                { from: th.pore_pressure?.siaga ?? 20, to: th.pore_pressure?.bahaya ?? 30, color: BAND.siaga, axis: 1 },
                { from: th.pore_pressure?.bahaya ?? 30, to: 40, color: BAND.bahaya, axis: 1 },
              ]}
            />
          </div>
        </Panel>

        <Panel title="Slope Velocity & Acceleration" sub="derived from GNSS resultant" right={readout(velNow, "mm/day", velStatus)}>
          <div className="panel-body">
            <Legend items={[
              { label: "Velocity · mm/day", color: col("velocity") },
              { label: "Acceleration · mm/day²", color: col("acceleration"), dash: "dashed" },
              { label: "Tertiary creep", color: BAND.bahaya, kind: "box" },
            ]} />
            <PanelChart height={232}
              left={{ name: "mm/day", min: 0, max: velMax }}
              right={{ name: "mm/day²", min: 0, max: 24 }}
              series={[
                { name: "Acceleration", data: derived.acceleration, color: col("acceleration"), width: 1.6, dash: "dashed", axis: 1, opacity: op("acceleration") },
                { name: "Velocity", data: derived.velocity, color: col("velocity"), width: 2.4, z: 3, opacity: op("velocity") },
              ]}
              bands={[
                { from: VEL_TH.siaga, to: VEL_TH.bahaya, color: BAND.siaga },
                { from: VEL_TH.bahaya, to: velMax, color: BAND.bahaya },
              ]}
            />
          </div>
        </Panel>

        <Panel title="Slope Cross-section" sub="sensors at depth" style={{ gridColumn: "3", gridRow: "2" }}>
          <div style={{ padding: 8, display: "flex", flexDirection: "column", justifyContent: "center", flex: 1 }}>
            <CrossSection sensors={data.sensors} />
          </div>
        </Panel>
      </div>

    </div>
  );
}
