import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";

const NAMES = { 0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou", 5: "QZSS", 6: "GLONASS", 7: "NavIC" };
const colors = ["#117C89", "#CA913D", "#788DA1", "#6674A0", "#8C6C65", "#4B9482", "#AA809B"];

function fmtUtcLabel(ts) {
  const d = new Date(ts);
  if (!Number.isFinite(d.getTime())) return "Invalid time";
  return `${d.toISOString().slice(0, 16)} UTC`;
}

function MiniScatter({ rows, field, label, unit, yLabel, helper }) {
  const [hover, setHover] = useState(null);
  const points = rows.map((r) => ({ t: Date.parse(r.timestamp_utc), v: Number(r[field]) }))
    .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.v));
  if (!points.length) return null;
  const minT = Math.min(...points.map((p) => p.t));
  const maxT = Math.max(...points.map((p) => p.t));
  const minV = Math.min(...points.map((p) => p.v));
  const maxV = Math.max(...points.map((p) => p.v));
  const width = 700, height = 196, left = 60, right = 20, top = 28, bottom = 41;
  const iw = width - left - right, ih = height - top - bottom;
  const py = (v) => top + ih - ((v - minV) / (maxV - minV || 1)) * ih;
  const px = (t) => left + ((t - minT) / (maxT - minT || 1)) * iw;
  const labelUtc = (v) => new Date(v).toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
  const ticks = Array.from({ length: 3 }, (_, i) => minV + ((maxV - minV) * i) / 2);
  const decimals = maxV - minV < 10 ? 1 : 0;
  return <div className="satellite-qa-card-item">
    <div className="satellite-qa-card-head"><strong>{label}</strong><span>{helper}</span></div>
    <div className="satellite-rich-chart" onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}: ${points.length} epochs`} className="satellite-qa-svg">
        {ticks.map((v, i) => <g key={i}>
          <line x1={left} x2={left + iw} y1={py(v)} y2={py(v)} stroke="#e7edf3" strokeDasharray="4 4" />
          <text x={left - 9} y={py(v) + 4} textAnchor="end" fill="currentColor" fontSize="11">{v.toFixed(decimals)}</text>
        </g>)}
        <path d={`M${left} ${top}V${top+ih}H${left+iw}`} fill="none" stroke="#aabacb"/>
        {points.map((p, i) => <g key={i} onMouseEnter={() => setHover({ ...p, x: px(p.t), y: py(p.v) })} onFocus={() => setHover({ ...p, x: px(p.t), y: py(p.v) })}>
          <circle cx={px(p.t)} cy={py(p.v)} r="9" fill="transparent" tabIndex="0" aria-label={`${labelUtc(p.t)}: ${p.v.toFixed(1)} ${unit}`} />
          <circle cx={px(p.t)} cy={py(p.v)} r="3.2" fill="#117C89" pointerEvents="none" />
        </g>)}
        <text x={left} y={height-19} fontSize="10" fill="currentColor">{labelUtc(minT)}</text>
        <text x={left+iw} y={height-19} textAnchor="end" fontSize="10" fill="currentColor">{labelUtc(maxT)}</text>
        <text x={left+iw/2} y={height-2} textAnchor="middle" fontSize="11" fill="currentColor">Epoch time (UTC)</text>
        <text x="16" y={top+ih/2} transform={`rotate(-90 16 ${top+ih/2})`} textAnchor="middle" fontSize="11" fill="currentColor">{yLabel}</text>
      </svg>
      {hover && <div className="satellite-rich-tooltip" role="status" style={{ left: `${Math.min(76, Math.max(17, 100*hover.x/width))}%`, top: `${Math.max(4, 100*hover.y/height - 8)}%` }}>
        <strong>{label}</strong><span>{labelUtc(hover.t)}</span><b>{hover.v.toFixed(1)} {unit}</b>
      </div>}
    </div>
    <div className="satellite-qa-footnote">Hover or focus a point to inspect its epoch and value.</div>
  </div>;
}

export default function SatelliteQualityQA({ siteId, deviceId, window }) {
  const { authFetch } = useAuth();
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const from = window?.from || "", to = window?.to || "";

  useEffect(() => {
    if (!siteId || !deviceId || deviceId === "ROVER-01" || !from || !to) {
      setResult(null); setError(""); return;
    }
    let live = true; const controller = new AbortController();
    setBusy(true); setError(""); setResult(null);
    const q = new URLSearchParams({ site_id: siteId, device_id: deviceId, from, to });
    authFetch(`/api/v1/sensors/gnss/rawx/satellite-quality?${q}`, { signal: controller.signal })
      .then(async (r) => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`); return j; })
      .then((j) => { if (live) setResult(j); })
      .catch((e) => { if (live && e.name !== "AbortError") setError(e.message || "Satellite API failed"); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; controller.abort(); };
  }, [authFetch, siteId, deviceId, from, to]);

  const epochs = result?.epochs || [];
  const histogram = result?.cn0_histogram || [];
  const constellations = result?.constellations || {};
  const values = useMemo(() => Object.entries(constellations).filter(([, n]) => n > 0), [result]);
  const nonzeroBins = histogram.filter((b) => b.count > 0);
  const maxBin = Math.max(1, ...histogram.map((x) => x.count || 0));
  if (deviceId === "ROVER-01" || !siteId || !deviceId) return null;

  return (
    <section className="panel sensor-card satellite-quality-qa" aria-label="RAWX satellite signal quality" style={{ minWidth: 0, boxSizing: "border-box", padding: "24px 24px 18px" }}>
      <div style={{ fontSize: 10, letterSpacing: 1.1, fontWeight: 700, opacity: .68 }}>ACTUAL RAWX · SATELLITE SIGNAL QA</div>
      <h2 style={{ margin: "6px 0 10px", fontSize: 16 }}>Satellite count &amp; C/N0 · {deviceId}</h2>
      {busy && <div role="status">Loading verified RAWX satellite metrics…</div>}
      {error && <div role="alert">Failed to load satellite metrics: {error}</div>}
      {!busy && !error && result && !epochs.length && <p>No valid RAWX satellite measurements in the selected window.</p>}
      {!busy && !error && epochs.length > 0 && <>
        <p style={{ fontSize: 12, opacity: .78, margin: "6px 0 22px", lineHeight: 1.5 }}>
          {epochs.length} verified epochs · {result.cn0_sample_count} C/N0 measurements · source = GNSS RAWX payload yang tersimpan di database · no interpolation · measured signal quality, not position accuracy
        </p>
        <div className="satellite-quality-qa-grid">
          <MiniScatter rows={epochs} field="unique_satellites" label="Unique satellites per epoch" unit="SV" yLabel="Unique satellites (SV)" helper="X = epoch time (UTC) · Y = jumlah satelit unik" />
          <MiniScatter rows={epochs} field="median_cn0_dbhz" label="Median C/N0 per epoch" unit="dB-Hz" yLabel="Median C/N0 (dB-Hz)" helper="X = epoch time (UTC) · Y = median C/N0" />

          <div className="satellite-qa-card-item">
            <div className="satellite-qa-card-head">
              <strong>C/N0 distribution (5 dB-Hz bins)</strong>
              <span>X = bin C/N0 · Y = jumlah measurement</span>
            </div>
            <div className="satellite-histogram" aria-label="C/N0 distribution histogram">
              {nonzeroBins.map((b) => (
                <div key={b.start_dbhz} className="satellite-histogram-col">
                  <div
                    className="satellite-histogram-bar"
                    title={`${b.start_dbhz}–${b.start_dbhz + 4} dB-Hz · ${b.count} measurements`}
                    style={{ height: `${Math.max(4, (100 * b.count) / maxBin)}%` }}
                  />
                  <span>{b.start_dbhz}</span>
                </div>
              ))}
            </div>
            <div className="satellite-qa-footnote">Hover over a bar to inspect its C/N0 range and observation count.</div>
          </div>

          <div className="satellite-qa-card-item">
            <div className="satellite-qa-card-head">
              <strong>Constellation measurement breakdown</strong>
              <span>X = jumlah signal measurements per constellation</span>
            </div>
            <div className="satellite-constellation-list">
              {values.map(([id, count], i) => (
                <div key={id} className="satellite-constellation-row" title={`${NAMES[id] || `GNSS ${id}`} · ${count} signal measurements`}>
                  <span>{NAMES[id] || `GNSS ${id}`}</span>
                  <div className="satellite-constellation-track">
                    <div className="satellite-constellation-fill" style={{ background: colors[i % colors.length], width: `${(100 * count) / Math.max(...values.map((x) => x[1]))}%` }} />
                  </div>
                  <span style={{ textAlign: "right" }}>{count}</span>
                </div>
              ))}
            </div>
            <div className="satellite-qa-footnote">Hover over a row to inspect the constellation and exact observation count.</div>
          </div>
        </div>
        <small style={{ display: "block", marginTop: 16, opacity: .74, lineHeight: 1.5 }}>
          Unique SV = distinct (gnssId, svId); numMeas = signal observations. C/N0 hanya dari measured value valid nonzero. Invalid RAWX/time excluded. QA only; not PPK FIX, displacement, atau safety evidence.
        </small>
      </>}
    </section>
  );
}
