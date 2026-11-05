// Halaman Devices — GET/POST/PUT/DELETE /api/v1/devices (2026-09-20:
// Create/Update/Delete ditambahkan — sebelumnya cuma Read, dan bahkan
// TIDAK ADA cara mendaftarkan device sama sekali lewat aplikasi).

import { useEffect, useState, useMemo, useRef } from "react";
import * as echarts from "echarts";
import "./weatherStation.css";
import "./devicesTelemetry.css";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

const wibDate = value => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit' }).format(value);
const wibTime = value => new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', hour12: false }).format(value);
const wibTimestamp = value => value ? new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
}).format(new Date(value)) : '—';

function BatteryPlot({ points }) {
  const node = useRef(null);
  useEffect(() => {
    if (!node.current) return undefined;
    const chart = echarts.init(node.current);
    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis', valueFormatter: v => v == null ? '—' : `${Number(v).toFixed(2)} V` },
      grid: { left: 65, right: 28, top: 28, bottom: 56 },
      xAxis: { type: 'time', name: 'Time (WIB)', axisLabel: { hideOverlap: true, formatter: t => wibTimestamp(t).slice(0, 17) }, splitLine: { show: false } },
      yAxis: { type: 'value', name: 'Voltage (V)', scale: true, splitLine: { lineStyle: { color: '#edf1f5' } } },
      series: [{ name: 'Battery Voltage', type: 'line', showSymbol: points.length < 30,
        connectNulls: false, lineStyle: { width: 2 }, itemStyle: { color: '#3c8eae' },
        data: points.map(p => [p.time, p.voltage_v]) }],
    });
    const resize = () => chart.resize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(node.current);
    window.addEventListener('resize', resize);
    return () => { observer?.disconnect(); window.removeEventListener('resize', resize); chart.dispose(); };
  }, [points]);
  return <div ref={node} className="weather-chart" style={{ height: 340 }} role="img" aria-label="Battery voltage over time" />;
}

// The selected card is the sole authority for the detail device_id.
// Each overview request is scoped to one exact ID and aborts when the range changes.
function BatteryMiniChart({ points, deviceId }) {
  const node = useRef(null);
  useEffect(() => {
    if (!node.current || !points.length) return undefined;
    const chart = echarts.init(node.current);
    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis', valueFormatter: v => v == null ? '—' : `${Number(v).toFixed(2)} V` },
      grid: { left: 8, right: 8, top: 9, bottom: 9 },
      xAxis: { type: 'time', show: false }, yAxis: { type: 'value', scale: true, show: false },
      series: [{ name: 'Battery Voltage', type: 'line', showSymbol: false, smooth: false,
        lineStyle: { width: 2, color: '#3c8eae' }, areaStyle: { color: 'rgba(60,142,174,0.13)' },
        data: points.map(p => [p.time, p.voltage_v]) }],
    });
    const resize = () => chart.resize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(node.current);
    window.addEventListener('resize', resize);
    return () => { observer?.disconnect(); window.removeEventListener('resize', resize); chart.dispose(); };
  }, [points, deviceId]);
  return <div ref={node} className="device-battery-sparkline" role="img" aria-label={`Battery trend for ${deviceId}`} />;
}

function DeviceOverviewCard({ device, authFetch, from, to, fromHour, toHour, onExplore }) {
  const [state, setState] = useState({ status: 'loading', chart: [], total: 0 });
  const [refreshTick, setRefreshTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setRefreshTick(t => t + 1), 60000);
    return () => window.clearInterval(timer);
  }, []);
  const start = `${from}T${fromHour}:00+07:00`;
  const end = `${to}T${toHour}:59+07:00`;
  const valid = Boolean(from && to && fromHour && toHour && Date.parse(start) < Date.parse(end));
  useEffect(() => {
    if (!valid) { setState({ status: 'invalid', chart: [], total: 0 }); return undefined; }
    const controller = new AbortController();
    setState({ status: 'loading', chart: [], total: 0 });
    const params = new URLSearchParams({ from: start, to: end, page: '1', page_size: '1' });
    authFetch(`/api/v1/devices/${encodeURIComponent(device.device_id)}/battery-history?${params}`, { signal: controller.signal })
      .then(async r => { const b = await r.json(); if (!r.ok) throw new Error(b.detail || `HTTP ${r.status}`); return b; })
      .then(b => { if (!controller.signal.aborted) setState({ status: 'ready', chart: b.chart || [], total: b.total || 0 }); })
      .catch(() => { if (!controller.signal.aborted) setState({ status: 'error', chart: [], total: 0 }); });
    return () => controller.abort();
  }, [authFetch, device.device_id, start, end, valid, refreshTick]);
  const voltage = device.battery_voltage_v == null || !Number.isFinite(Number(device.battery_voltage_v))
    ? null : Number(device.battery_voltage_v);
  const latest = voltage == null ? '—' : voltage.toFixed(2);
  return <section className="device-overview-card">
    <div className="device-card-top"><div><h2>{device.label || device.device_id}</h2><p>{device.device_id} · {device.device_type}</p></div>
      <button type="button" className="device-card-explore" onClick={() => onExplore(device.device_id)} aria-label={`Explore battery history for ${device.device_id}`}>Explore ↗</button>
    </div>
    <div className="device-card-voltage"><strong>{latest}</strong> <span>V</span></div>
    <p className="device-card-last">Latest battery observation · {device.battery_recorded_at ? `${wibTimestamp(device.battery_recorded_at)} WIB` : 'Not available'}</p>
    <div className="device-card-trend">
      {state.status === 'ready' && state.chart.length ? <BatteryMiniChart points={state.chart} deviceId={device.device_id} /> :
        <div className="device-card-empty">{state.status === 'loading' ? 'Loading battery trend…' :
          state.status === 'error' ? 'Battery history unavailable' : state.status === 'invalid' ? 'Invalid date/time range' : 'No battery observations in this range'}</div>}
    </div>
    <p className="device-card-caption">{state.status === 'ready' ? `${state.total} observations in selected range` : 'Selected-range observations'}</p>
    <div className="device-card-meta"><span><b>Firmware</b> {device.firmware_version || 'Not reported'}</span>
      <span><b>ICCID</b> {device.iccid || 'N/A'}</span><span><b>Status</b> {device.online ? 'Online' : 'Offline'}</span></div>
  </section>;
}

function DeviceBatteryDetail({ device, authFetch, onBack, initialRange }) {
  const [from, setFrom] = useState(() => initialRange.from);
  const [to, setTo] = useState(() => initialRange.to);
  const [fromHour, setFromHour] = useState(() => initialRange.fromHour);
  const [toHour, setToHour] = useState(() => initialRange.toHour);
  const [page, setPage] = useState(1);
  const [history, setHistory] = useState({ chart: [], rows: [], total: 0, total_pages: 1 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshTick, setRefreshTick] = useState(0);
  useEffect(() => { const timer = window.setInterval(() => setRefreshTick(v => v + 1), 60000); return () => window.clearInterval(timer); }, []);
  const start = `${from}T${fromHour}:00+07:00`;
  const end = `${to}T${toHour}:59+07:00`;
  const valid = from && to && fromHour && toHour && Date.parse(start) < Date.parse(end);
  useEffect(() => {
    if (!valid) { setError('Invalid date/time range'); setHistory({ chart: [], rows: [], total: 0, total_pages: 1 }); return; }
    const controller = new AbortController();
    setLoading(true); setError('');
    const params = new URLSearchParams({ from: start, to: end, page: String(page), page_size: '15' });
    authFetch(`/api/v1/devices/${encodeURIComponent(device.device_id)}/battery-history?${params}`, { signal: controller.signal })
      .then(async r => { const b = await r.json(); if (!r.ok) throw new Error(b.detail || `HTTP ${r.status}`); return b; })
      .then(b => { if (!controller.signal.aborted) { setHistory(b); setLoading(false); } })
      .catch(e => { if (!controller.signal.aborted) { setError(e.message); setLoading(false); } });
    return () => controller.abort();
  }, [authFetch, device.device_id, start, end, page, refreshTick, valid]);
  const totalPages = Math.max(1, history.total_pages || 1);
  return <main className="weather-page">
    <div className="weather-heading"><div><p className="weather-eyebrow">Devices · Device telemetry</p><h1>{device.label || device.device_id} — Battery History</h1><p>Device ID: {device.device_id} · Site: {device.site_id}</p></div></div>
    <nav className="weather-detail-nav"><button type="button" onClick={onBack}>← Back to Devices</button><span>Historical chart and observation table</span></nav>
    <div className="weather-station-meta"><span><strong>Firmware:</strong> {device.firmware_version || 'Not reported'}</span><span><strong>ICCID:</strong> {device.iccid || 'Not reported'}</span><span><strong>Latest Battery:</strong> {Number.isFinite(Number(device.battery_voltage_v)) && device.battery_voltage_v != null ? `${Number(device.battery_voltage_v).toFixed(2)} V` : '—'}</span></div>
    <div className="weather-controls" role="group" aria-label="Battery observation range">
      <label>From (WIB)<input type="date" value={from} onChange={e => { setFrom(e.target.value); setPage(1); }} /></label>
      <label>From time (WIB)<input type="time" value={fromHour} onChange={e => { setFromHour(e.target.value); setPage(1); }} /></label>
      <label>To (WIB)<input type="date" value={to} onChange={e => { setTo(e.target.value); setPage(1); }} /></label>
      <label>To time (WIB)<input type="time" value={toHour} onChange={e => { setToHour(e.target.value); setPage(1); }} /></label>
    </div>
    {error && <div className="admin-error" role="alert">Battery data unavailable: {error}</div>}
    {loading && <p>Loading battery observations…</p>}
    <div className="weather-detail-stack">
      <section className="weather-panel"><h2>Battery Voltage History</h2><p>Time (WIB) · Voltage (V)</p>
        {history.chart?.length ? <BatteryPlot points={history.chart} /> : <div className="weather-empty">No battery observations in this range.</div>}
      </section>
      <section className="weather-panel"><div className="weather-table-top"><div><h2>Battery Voltage — Historical Data</h2><p>{history.total || 0} observations in selected range · raw values</p></div></div>
        <div className="weather-table-scroll"><table><thead><tr><th>Timestamp (WIB)</th><th>Voltage (V)</th><th>Source</th><th>Source File</th></tr></thead><tbody>
          {(history.rows || []).map((r, i) => <tr key={`${r.time}-${r.source_file}-${i}`}><td>{wibTimestamp(r.time)}</td><td>{Number(r.voltage_v).toFixed(2)}</td><td>{(r.source || 'unknown').toUpperCase()}</td><td>{r.source_file || '—'}</td></tr>)}
        </tbody></table>{!(history.rows || []).length && <div className="weather-empty">No observations in this range.</div>}</div>
        <div className="weather-pagination"><span>Page {Math.min(page, totalPages)} / {totalPages}</span>
          <button type="button" disabled={page <= 1 || loading} onClick={() => setPage(p => Math.max(1, p - 1))}>Previous</button>
          <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next</button>
        </div>
      </section>
    </div>
  </main>;
}

export default function Devices() {
  const { authFetch, auth } = useAuth();
  const navigate = useNavigate();
  const [devices, setDevices] = useState(null);
  const [error, setError] = useState(null);
  const [siteFilter, setSiteFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [editDraft, setEditDraft] = useState({ device_type: "", site_id: "", label: "" });
  const [newDevice, setNewDevice] = useState({ device_id: "", device_type: "", site_id: "", label: "" });
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState(null);
  const [selectedDeviceId, setSelectedDeviceId] = useState(null);
  const [from, setFrom] = useState(() => wibDate(new Date(Date.now() - 7 * 86400000)));
  const [to, setTo] = useState(() => wibDate(new Date()));
  const [fromHour, setFromHour] = useState('00:00');
  const [toHour, setToHour] = useState('23:59');

  const isAdmin = auth?.role === "admin";

  function reload() {
    authFetch("/api/v1/devices").then((r) => r.json()).then((body) => setDevices(body.devices || [])).catch((e) => setError(String(e)));
  }
  useEffect(() => { reload(); }, [authFetch]);

  const sites = useMemo(() => [...new Set((devices || []).map((d) => d.site_id))], [devices]);

  const filtered = useMemo(() => {
    if (!devices) return null;
    return devices.filter((d) => {
      if (siteFilter && d.site_id !== siteFilter) return false;
      if (statusFilter === "online" && !d.online) return false;
      if (statusFilter === "offline" && d.online) return false;
      if (search && !d.device_id.toLowerCase().includes(search.toLowerCase()) && !(d.label || "").toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [devices, siteFilter, statusFilter, search]);

  async function createDevice() {
    setBusy("__new__");
    setError(null);
    try {
      const r = await authFetch("/api/v1/devices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newDevice),
      });
      const body = await r.json();
      if (!r.ok) { setError(body.detail); return; }
      setNewDevice({ device_id: "", device_type: "", site_id: "" });
      setShowCreate(false);
      reload();
    } finally {
      setBusy(null);
    }
  }

  function startEdit(d) {
    setEditing(d.device_id);
    setEditDraft({ device_type: d.device_type, site_id: d.site_id, label: d.label || "" });
    setError(null);
  }

  async function saveEdit(device_id) {
    setBusy(device_id);
    setError(null);
    try {
      const r = await authFetch(`/api/v1/devices/${device_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        // label_given selalu true saat submit dari form edit ini — beda
        // dari device_type/site_id (None = "jangan diubah"), untuk label
        // string kosong TETAP harus dikirim (artinya "kosongkan label").
        body: JSON.stringify({ ...editDraft, label_given: true }),
      });
      const body = await r.json();
      if (!r.ok) { setError(body.detail); return; } // pesan trigger migrasi 011 kalau device sudah punya riwayat data
      setEditing(null);
      reload();
    } finally {
      setBusy(null);
    }
  }

  async function del(device_id, force = false, purge = false) {
    if (!force && !window.confirm(`Delete device "${device_id}"?`)) return;
    setBusy(device_id);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (force) params.set("force", "true");
      if (purge) params.set("purge", "true");
      const r = await authFetch(`/api/v1/devices/${device_id}${params.toString() ? "?" + params : ""}`, { method: "DELETE" });
      const body = await r.json();
      if (!r.ok) {
        // Backend cuma MEMPERINGATKAN kalau device punya riwayat data
        // (bukan blokir keras seperti site). Sekarang ada 2 pilihan
        // (2026-09-21, baru): hapus device SAJA (riwayat measurements
        // dibiarkan, bisa jadi noise) atau hapus device + riwayatnya
        // sekalian (purge, buat data test/sintetis yang memang mau
        // dibuang total).
        const choice = window.prompt(
          body.detail + "\n\nKetik salah satu:\n" +
          "  'device' = hapus device saja, riwayat data DIBIARKAN\n" +
          "  'semua'  = hapus device + SEMUA riwayat measurements-nya\n" +
          "  (leave blank or select Cancel to abort)"
        );
        if (choice === "device") return del(device_id, true, false);
        if (choice === "semua") return del(device_id, true, true);
        return;
      }
      if (body.purged_measurements > 0) {
        alert(`Device dihapus, ${body.purged_measurements} baris measurements ikut dibuang.`);
      }
      reload();
    } finally {
      setBusy(null);
    }
  }

  if (selectedDeviceId) {
    const detailDevice = devices?.find(d => d.device_id === selectedDeviceId);
    if (detailDevice) return <DeviceBatteryDetail key={selectedDeviceId} device={detailDevice} authFetch={authFetch}
      initialRange={{ from, to, fromHour, toHour }} onBack={() => setSelectedDeviceId(null)} />;
  }

  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Devices</h1>
        {isAdmin && <button className="admin-btn admin-btn-primary" style={{ marginLeft: "auto" }} onClick={() => setShowCreate((v) => !v)}>+ New Device</button>}
      </div>

      <div className="device-overview-filters">
        <div className="table-filters">
          <input placeholder="Search device ID…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
            <option value="">All sites</option>
            {sites.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All statuses</option>
            <option value="online">Online only</option>
            <option value="offline">Offline only</option>
          </select>
          <span className="table-total">{filtered ? filtered.length : 0} / {devices ? devices.length : 0} device</span>
        </div>
      </div>

      <section className="device-overview" aria-label="Battery overview by device">
        <div className="device-overview-heading"><div><h2>Battery Overview</h2><p>One card per registered device · Timezone: WIB (Asia/Jakarta)</p></div>
          <span>{filtered?.length ?? 0} devices</span></div>
        <div className="weather-controls" role="group" aria-label="Battery overview observation range">
          <label>From (WIB)<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label>
          <label>From time (WIB)<input type="time" value={fromHour} onChange={e => setFromHour(e.target.value)} /></label>
          <label>To (WIB)<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
          <label>To time (WIB)<input type="time" value={toHour} onChange={e => setToHour(e.target.value)} /></label>
        </div>
        <div className="device-overview-grid">
          {(filtered || []).map(d => <DeviceOverviewCard key={d.device_id} device={d} authFetch={authFetch}
            from={from} to={to} fromHour={fromHour} toHour={toHour} onExplore={setSelectedDeviceId} />)}
        </div>
        {filtered && !filtered.length && <p className="device-overview-no-data">No devices match the filters.</p>}
      </section>

      <div className="panel" style={{ maxWidth: 1000, margin: "0 auto", padding: 20 }}>
        {isAdmin && showCreate && (
          <div className="admin-warn" style={{ marginBottom: 16, background: "var(--panel-2)", color: "var(--ink-2)", borderColor: "var(--line)" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input placeholder="Device ID (BASE-02)" value={newDevice.device_id} onChange={(e) => setNewDevice((d) => ({ ...d, device_id: e.target.value }))} />
              <input placeholder="Display name (optional)" value={newDevice.label} onChange={(e) => setNewDevice((d) => ({ ...d, label: e.target.value }))} />
              <input placeholder="Tipe (gnss_base/gnss_rover)" value={newDevice.device_type} onChange={(e) => setNewDevice((d) => ({ ...d, device_type: e.target.value }))} />
              <select value={newDevice.site_id} onChange={(e) => setNewDevice((d) => ({ ...d, site_id: e.target.value }))}>
                <option value="">Select site…</option>
                {sites.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="admin-btn admin-btn-primary" disabled={busy === "__new__" || !newDevice.device_id || !newDevice.device_type || !newDevice.site_id} onClick={createDevice}>Create</button>
            </div>
            <span style={{ fontSize: 11 }}>The site must be registered first (see Sites). If missing from the list, enter its site ID manually.</span>
          </div>
        )}



        {error && <div className="admin-error" style={{ marginBottom: 12, whiteSpace: "pre-line" }}>{error}</div>}
        {!devices && !error && <div className="loading">Loading…</div>}
        {filtered && filtered.length === 0 && <div className="sc-row">No devices match the filters.</div>}
        {filtered && filtered.length > 0 && (
          <table className="devtable">
            <thead>
              <tr>
                <th>Device ID</th><th>Name</th><th>Type</th><th>Site</th><th>Status</th><th>Firmware Version</th><th>ICCID</th><th>Battery (V)</th><th>Last seen</th><th>History</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => (
                <tr key={d.device_id}>
                  <td>{d.device_id}</td>
                  {editing === d.device_id ? (
                    <>
                      <td><input value={editDraft.label} onChange={(e) => setEditDraft((v) => ({ ...v, label: e.target.value }))} placeholder="(kosongkan = pakai device ID)" style={{ width: 160 }} /></td>
                      <td><input value={editDraft.device_type} onChange={(e) => setEditDraft((v) => ({ ...v, device_type: e.target.value }))} style={{ width: 100 }} /></td>
                      <td>
                        <select value={editDraft.site_id} onChange={(e) => setEditDraft((v) => ({ ...v, site_id: e.target.value }))}>
                          {sites.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                      <td colSpan={6}>
                        <button className="devlink" disabled={busy === d.device_id} onClick={() => saveEdit(d.device_id)}>Save</button>{" "}
                        <button className="devlink" onClick={() => setEditing(null)}>Cancel</button>
                      </td>
                    </>
                  ) : (
                    <>
                      {/* Label = nama tampilan yang bisa diedit bebas
                          (2026-09-21, baru), terpisah dari device_id yang
                          immutable — fallback tampilkan device_id apa
                          adanya kalau belum ada label diisi. */}
                      <td>{d.label ? d.label : <i style={{ color: "var(--ink-3)" }}>{d.device_id}</i>}</td>
                      <td>{d.device_type}</td>
                      <td><button className="devlink" onClick={() => navigate(`/sites/${d.site_id}`)}>{d.site_id}</button></td>
                      <td>
                        <span className={"sc-dot " + (d.online ? "sc-on" : "sc-off")} style={{ display: "inline-block", marginRight: 6 }} />
                        {d.online ? "Online" : "Offline"}
                      </td>
                      <td>{d.firmware_version || 'Not reported'}</td>
                      <td>{d.iccid || 'N/A'}</td>
                      <td>{d.battery_voltage_v != null && Number.isFinite(Number(d.battery_voltage_v)) ? Number(d.battery_voltage_v).toFixed(2) : '—'}</td>
                      <td>{d.last_seen ? new Date(d.last_seen).toLocaleString("en-GB", { timeZone: 'Asia/Jakarta' }) : "Never"}</td>
                      <td><button className="devlink" onClick={() => setSelectedDeviceId(d.device_id)}>View History</button></td>
                    </>
                  )}
                  {isAdmin && editing !== d.device_id && (
                    <td>
                      <button className="devlink" onClick={() => startEdit(d)}>Edit</button>{" "}
                      <button className="devlink" style={{ color: "var(--bahaya)" }} disabled={busy === d.device_id} onClick={() => del(d.device_id)}>Delete</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
