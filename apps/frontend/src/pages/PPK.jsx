import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import "./ppk.css";
import PPKQACharts from "./PPKQACharts.jsx";

const fmtTime = (value) => value ? new Date(value).toLocaleString("id-ID") : "—";
const fmtNum = (value, digits = 3) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
const shortHash = (value) => value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";

const QUALITY_LABEL = {
  1: "FIX",
  2: "FLOAT",
  3: "SBAS",
  4: "DGPS",
  5: "SINGLE",
  6: "PPP",
};

function Stat({ label, value, detail, tone = "" }) {
  return (
    <div className={`ppk-stat ${tone}`.trim()}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function HashRow({ label, value }) {
  return (
    <div className="ppk-hash-row">
      <span>{label}</span>
      <code title={value || ""}>{shortHash(value)}</code>
    </div>
  );
}

export default function PPK() {
  const navigate = useNavigate();
  const { authFetch } = useAuth();
  const [siteId, setSiteId] = useState("ITB-STAGING-01");
  const [roverId, setRoverId] = useState("ROVER-B1-02");
  const [limit, setLimit] = useState(500);
  const [timeRange, setTimeRange] = useState('all');
  const [roverOptions, setRoverOptions] = useState([]);
  const [applied, setApplied] = useState({siteId:'ITB-STAGING-01',roverId:'ROVER-B1-02',timeRange:'all',limit:500,revision:0}); // b12-unified-filter-v1
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const initialLoadDone = useRef(false);

  const load = useCallback(async () => {
    setApplied(p => ({siteId:siteId.trim(),roverId,timeRange,limit,revision:p.revision+1}));
    const params = new URLSearchParams({ limit: String(Math.min(limit, 2000)) });
    if (siteId.trim()) params.set("site_id", siteId.trim());
    if (roverId.trim()) params.set("rover_device_id", roverId.trim());

    setLoading(true);
    setError("");
    try {
      const response = await authFetch(`/api/v1/ppk/solutions?${params}`);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
      setPayload(body);
    } catch (err) {
      setError(err?.message || "Failed to load data PPK");
    } finally {
      setLoading(false);
    }
  }, [authFetch, limit, roverId, siteId, timeRange]);

  useEffect(() => {
    if (initialLoadDone.current) return;
    initialLoadDone.current = true;
    void load();
  }, [load]);

  useEffect(() => {
    let active=true;
    const qs=new URLSearchParams({site_id:siteId.trim()});
    authFetch(`/api/v1/ppk/qa/rovers?${qs}`).then(async r=>{
      if(!r.ok) throw Error(`HTTP ${r.status}`);
      return r.json();
    }).then(body=>{if(active)setRoverOptions(Array.isArray(body.rovers)?body.rovers:[])}).catch(()=>{if(active)setRoverOptions([])});
    return ()=>{active=false};
  }, [authFetch, siteId]);

  const rows = payload?.rows || [];
  const contract = payload?.solution_contract || {};

  const qualityCounts = useMemo(() => {
    const out = {};
    rows.forEach((row) => {
      const q = String(row.rtklib_quality ?? "?");
      out[q] = (out[q] || 0) + 1;
    });
    return out;
  }, [rows]);

  const latest = rows[0] || null;
  const provenanceCompleteCount = rows.filter((row) => row.provenance_complete === true).length;
  const maxHAcc = rows.reduce((max, row) => typeof row.h_acc_m === "number" ? Math.max(max, row.h_acc_m) : max, 0);

  return (
    <div className="l2 pgdoc2-page ppk-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 650 }}>PPK Technical Results</h1>
          <div className="sub">RTKLIB solution contract, quality, and provenance · not production displacement acceptance</div>
        </div>
      </div>

      <div className="ppk-warning" role="status">
        <strong>UNVALIDATED</strong>
        <span>PPK data on this page are for research and QA only. Do not use them for operational alarms, evacuation instructions, or production displacement claims until production geodetic acceptance is complete.</span>
      </div>

      <div className="panel ppk-filter-panel">
        <label>
          <span>Site ID</span>
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="ITB-STAGING-01" />
        </label>
        <label>
          <span>Rover ID</span>
          <select value={roverId} onChange={(e) => setRoverId(e.target.value)} aria-label="Rover ID">
            <option value="" disabled>Select rover</option>
            {[...new Set([...roverOptions, ...(roverId ? [roverId] : [])])].map(id=><option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <label>
          <span>Time Range</span>
          <select value={timeRange} onChange={e=>setTimeRange(e.target.value)}>
            <option value="all">All available</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </select>
        </label>
        <label>
          <span>Limit</span>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[50, 100, 200, 500, 2000].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button className="admin-btn ppk-refresh" disabled={loading} onClick={load}>
          {loading ? "Loading…" : "Refresh"}
        </button>
        <div className="ppk-load-note">No automatic polling. Refresh manually to avoid unnecessary API load.</div>
      </div>

      {error && <div className="admin-error">{error}</div>}

      <PPKQACharts siteId={applied.siteId} roverId={applied.roverId} timeRange={applied.timeRange} limit={applied.limit} revision={applied.revision} />
      <details className={`ppk-legacy-details ${rows.length === 0 ? "ppk-legacy-empty" : ""}`}><summary>Technical details / Operational PPK (separate, unvalidated)</summary>
      <section className="ppk-stat-grid" aria-label="PPK contract summary">
        <Stat label="Schema" value={payload?.schema_version || "—"} detail={contract.locked ? "locked contract" : "contract metadata unavailable"} />
        <Stat label="Validation" value={(payload?.validation_status || "unknown").toUpperCase()} detail="production claim disabled" tone="warn" />
        <Stat label="Operational ready" value={payload?.operational_ready === true ? "YES" : "NO"} detail="fail-closed" tone={payload?.operational_ready === true ? "danger" : ""} />
        <Stat label="Vertical datum" value={contract.vertical_datum || "—"} detail="height semantics" />
        <Stat label="Processing engine" value={contract.processing_engine || "—"} detail="PPK implementation" />
        <Stat label="Production geodetic" value={contract.production_geodetic_validation === true ? "VALIDATED" : "NOT VALIDATED"} detail="surveyed BASE-01 still required" tone="warn" />
      </section>

      <div className="ppk-grid ppk-grid--four">
        <section className="panel ppk-card">
          <div className="ppk-card-head">
            <div><h2>Solution quality</h2><span>{rows.length} epochs from the current query</span></div>
          </div>
          {rows.length === 0 ? (
            <div className="ppk-empty">
              <strong>No persisted PPK solutions available.</strong>
              <span>An empty result is valid. The UI does not fabricate displacement data to populate charts.</span>
            </div>
          ) : (
            <>
              <div className="ppk-quality-grid">
                {Object.entries(qualityCounts).sort(([a], [b]) => Number(a) - Number(b)).map(([q, count]) => (
                  <div key={q} className={`ppk-quality q${q}`}>
                    <span>Q{q} · {QUALITY_LABEL[q] || "OTHER"}</span>
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>
              <div className="ppk-metrics-line">
                <span>Provenance lengkap <b>{provenanceCompleteCount}/{rows.length}</b></span>
                <span>Max h_acc <b>{fmtNum(maxHAcc, 3)} m</b></span>
              </div>
            </>
          )}
        </section>

        <section className="panel ppk-card">
          <div className="ppk-card-head"><div><h2>Latest persisted solution</h2><span>Absolute ellipsoidal position · technical only</span></div></div>
          {!latest ? (
            <div className="ppk-empty"><span>No rows to display.</span></div>
          ) : (
            <div className="ppk-latest">
              <div><span>Time</span><b>{fmtTime(latest.time)}</b></div>
              <div><span>Rover / Base</span><b>{latest.rover_device_id || "—"} / {latest.base_device_id || "—"}</b></div>
              <div><span>Latitude</span><b>{fmtNum(latest.latitude, 8)}</b></div>
              <div><span>Longitude</span><b>{fmtNum(latest.longitude, 8)}</b></div>
              <div><span>Ellipsoid height</span><b>{fmtNum(latest.ellipsoidal_height_m, 3)} m</b></div>
              <div><span>RTKLIB quality</span><b>Q{latest.rtklib_quality ?? "—"} · {QUALITY_LABEL[latest.rtklib_quality] || "—"}</b></div>
              <div><span>Satellites</span><b>{latest.rtklib_ns ?? "—"}</b></div>
              <div><span>Differential age</span><b>{fmtNum(latest.rtklib_age_s, 2)} s</b></div>
              <div><span>Ratio</span><b>{fmtNum(latest.rtklib_ratio, 2)}</b></div>
              <div><span>Validation</span><b>{latest.validation_status || "—"}</b></div>
            </div>
          )}
        </section>

        <section className="panel ppk-card ppk-table-card">
        <div className="ppk-card-head">
          <div><h2>Persisted solution epochs</h2><span>Displacement fields tetap ditampilkan sebagai technical/unvalidated values</span></div>
        </div>
        {rows.length > 0 && (
          <div className="ppk-table-scroll">
            <table className="devtable ppk-table">
              <thead>
                <tr>
                  <th>Time</th><th>Rover</th><th>Quality</th><th>NS</th><th>h_acc</th><th>Age</th><th>Ratio</th>
                  <th>dE</th><th>dN</th><th>dU</th><th>Total</th><th>Validation</th><th>Provenance</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={`${row.rover_device_id}-${row.time}-${idx}`}>
                    <td>{fmtTime(row.time)}</td>
                    <td>{row.rover_device_id || "—"}</td>
                    <td>Q{row.rtklib_quality ?? "—"} {QUALITY_LABEL[row.rtklib_quality] || ""}</td>
                    <td>{row.rtklib_ns ?? "—"}</td>
                    <td>{fmtNum(row.h_acc_m, 3)} m</td>
                    <td>{fmtNum(row.rtklib_age_s, 2)} s</td>
                    <td>{fmtNum(row.rtklib_ratio, 2)}</td>
                    <td>{fmtNum(row.displacement_e_mm, 2)} mm</td>
                    <td>{fmtNum(row.displacement_n_mm, 2)} mm</td>
                    <td>{fmtNum(row.displacement_u_mm, 2)} mm</td>
                    <td>{fmtNum(row.displacement_total_mm, 2)} mm</td>
                    <td><span className="ppk-validation-chip">{row.validation_status || "unvalidated"}</span></td>
                    <td>{row.provenance_complete ? <span className="ppk-prov-ok">complete</span> : <span className="ppk-prov-missing">incomplete</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel ppk-card">
        <div className="ppk-card-head"><div><h2>Reproducibility provenance</h2><span>SHA-256 chain from the latest row</span></div></div>
        {!latest ? (
          <div className="ppk-empty"><span>Provenance akan muncul setelah persisted solution tersedia.</span></div>
        ) : (
          <div className="ppk-hashes">
            {Object.entries(latest.provenance || {}).map(([key, value]) => <HashRow key={key} label={key} value={value} />)}
          </div>
        )}
      </section>
      </div>

      

      </details>
      <details className="panel ppk-card ppk-method-note">
        <summary>Data Limitations &amp; Interpretation</summary>
        <p><b>Base-reference type and source/receiver time integrity are not persisted by endpoint <code>ppk.solution.v1</code> at present.</b> This page deliberately does not infer or fabricate those values. Engine acceptance evidence must be reviewed in the acceptance artifacts, while production acceptance still requires surveyed BASE-01 ellipsoidal coordinates.</p>
      </details>
    </div>
  );

}
