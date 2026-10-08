import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";
const PAGE_SIZE = 100;
const fmtValue = (v) => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return v.toFixed(2);
  return Number(v).toPrecision(7).replace(/0+$/, "").replace(/\.$/, "");
};
export default function MeasurementTable({ siteId, devices = [], fromTime = null, toTime = null }) {
  const { authFetch } = useAuth();
  const [deviceId, setDeviceId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [sourceKind, setSourceKind] = useState("");
  const [validationStatus, setValidationStatus] = useState("");
  const [sortBy, setSortBy] = useState("time");
  const [sortDir, setSortDir] = useState("desc");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ rows: [], total: 0 });
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setOffset(0); }, [deviceId, quantity, sourceKind, validationStatus, sortBy, sortDir, fromTime, toTime, siteId]);
  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({ site_id: siteId, limit: String(PAGE_SIZE), offset: String(offset) });
    if (deviceId) params.set("device_id", deviceId);
    if (quantity) params.set("quantity", quantity);
    if (sourceKind) params.set("source_kind", sourceKind);
    if (validationStatus) params.set("validation_status", validationStatus);
    if (fromTime) params.set("from", fromTime);
    if (toTime) params.set("to", toTime);
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    if (data.rows.length === 0) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError("");
    authFetch(`/api/v1/measurements?${params}`)
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body?.error?.message || `HTTP ${r.status}`);
        return body;
      })
      .then((body) => { if (alive) setData({ rows: body.rows || [], total: body.total || 0 }); })
      .catch((e) => { if (alive) setError(e.message || "Gagal memuat data"); })
      .finally(() => {
        if (alive) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => { alive = false; };
  }, [authFetch, siteId, deviceId, quantity, sourceKind, validationStatus, sortBy, sortDir, fromTime, toTime, offset]);
  const quantities = useMemo(() => [...new Set((data.rows || []).map((r) => r.quantity))].sort(), [data.rows]);
  const start = data.total ? offset + 1 : 0;
  const end = Math.min(offset + PAGE_SIZE, data.total);
  const toggleSort = (column) => {
    if (sortBy === column) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortBy(column);
      setSortDir("desc");
    }
  };
  const sortMark = (column) => (sortBy === column ? (sortDir === "desc" ? " ↓" : " ↑") : "");
  return (
    <section className="panel measurement-table-panel">
      <div className="phead">
        <h2>Data Table</h2>
        <span className="sub">raw measurement viewer · server-side time filter & sorting</span>
        <span
          className="sub mt-refresh-status"
          style={{ visibility: refreshing ? "visible" : "hidden" }}
        >
          memperbarui…
        </span>
      </div>
      <div className="mt-toolbar">
        <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
          <option value="">Semua device</option>
          {devices.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
        </select>
        <select value={sourceKind} onChange={(e) => setSourceKind(e.target.value)}>
          <option value="">Semua source</option>
          <option value="device">Device</option>
          <option value="external">External</option>
          <option value="derived">Derived</option>
        </select>
        <select value={validationStatus} onChange={(e) => setValidationStatus(e.target.value)}>
          <option value="">Semua validasi</option>
          <option value="unverified">Unverified</option>
          <option value="provisional">Provisional</option>
          <option value="validated">Validated</option>
          <option value="not_applicable">N/A</option>
        </select>
        <input value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="Filter quantity…" list="measurement-quantities" />
        <datalist id="measurement-quantities">{quantities.map((q) => <option key={q} value={q} />)}</datalist>
        <button onClick={() => { setDeviceId(""); setSourceKind(""); setValidationStatus(""); setQuantity(""); setOffset(0); }}>Reset</button>
      </div>
      {error && <div className="mt-error">{error}</div>}
      <div className="mt-scroll">
        <table className="measurement-table">
          <thead><tr>
            <th>
              <button className="mt-sort" type="button" onClick={() => toggleSort("time")}>
                Timestamp UTC{sortMark("time")}
              </button>
            </th>
            <th>Device</th><th>Source</th><th>Source File</th><th>Validation</th><th>Quantity</th><th>Value</th><th>Unit</th><th>Quality</th><th>Latency</th>
            <th>
              <button className="mt-sort" type="button" onClick={() => toggleSort("received_at")}>
                Received{sortMark("received_at")}
              </button>
            </th>
          </tr></thead>
          <tbody>
            {loading && data.rows.length === 0 && (
              <tr>
                <td colSpan="11">Memuat…</td>
              </tr>
            )}
            {!loading && !data.rows.length && (
              <tr>
                <td colSpan="11">Belum ada measurement untuk filter ini.</td>
              </tr>
            )}
            {data.rows.map((r, i) => (
              <tr key={`${r.time}-${r.device_id}-${r.quantity}-${i}`}>
                <td className="num">{r.time}</td>
                <td>{r.source_kind === "external" ? "—" : r.device_id}</td>
                <td>
                  <span className={`mt-source mt-source-${r.source_kind || "device"}`}>
                    {r.source_kind || "device"}
                  </span>
                  {r.source_kind === "external" && <span className="mt-source-label">{r.device_id}</span>}
                </td>
                <td title={r.source_file || ""}>{r.source_file || "—"}</td>
                <td>
                  <span className={`mt-validation mt-validation-${r.validation_status || "unverified"}`}>
                    {r.validation_status || "unverified"}
                  </span>
                </td>
                <td>{r.quantity}</td>
                <td className="num">{fmtValue(r.value)}</td><td>{r.unit}</td>
                <td><span className={`mt-q mt-q-${r.quality_flag || "unknown"}`}>{r.quality_flag || "—"}</span></td>
                <td className="num">{r.latency_ms == null ? "—" : `${Math.round(r.latency_ms)} ms`}</td>
                <td className="num">{r.received_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-pager">
        <button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>← Sebelumnya</button>
        <button disabled={offset + PAGE_SIZE >= data.total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Berikutnya →</button>
      </div>
    </section>
  );
}
