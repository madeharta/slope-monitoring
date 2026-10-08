import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { roleSatisfies, useAuth } from "../context/AuthContext.jsx";

const PAGE_SIZE = 50;

const formatBytes = (value) => {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MiB`;
};

const formatTime = (value) => value ? new Date(value).toLocaleString("id-ID") : "—";

export default function Uploads() {
  const { auth, authFetch } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [deviceId, setDeviceId] = useState("");
  const [dataType, setDataType] = useState("");
  const [mode, setMode] = useState("");
  const [status, setStatus] = useState("");
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState("");
  const [error, setError] = useState("");
  const canDownloadOriginal = roleSatisfies(auth?.role, "operator");

  useEffect(() => { setOffset(0); }, [deviceId, dataType, mode, status, fileName]);

  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (deviceId) params.set("device_id", deviceId);
    if (dataType) params.set("data_type", dataType);
    if (mode) params.set("communication_mode", mode);
    if (status) params.set("processing_status", status);
    if (fileName) params.set("file_name", fileName);
    setLoading(true);
    setError("");
    authFetch(`/api/v1/uploads?${params}`)
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body?.detail || `HTTP ${r.status}`);
        return body;
      })
      .then((body) => {
        if (!alive) return;
        setRows(body.uploads || []);
        setTotal(body.total || 0);
      })
      .catch((e) => alive && setError(e.message || "Gagal memuat upload history"))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [authFetch, deviceId, dataType, mode, status, fileName, offset]);

  const devices = useMemo(() => [...new Set(rows.map((r) => r.device_id).filter(Boolean))].sort(), [rows]);

  const downloadOriginal = async (row) => {
    setDownloading(row.file_name);
    setError("");
    try {
      const r = await authFetch(`/api/v1/uploads/${encodeURIComponent(row.file_name)}/download`);
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${r.status}`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = row.file_name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message || "Gagal mengunduh original CSV");
    } finally {
      setDownloading("");
    }
  };

  const end = Math.min(offset + PAGE_SIZE, total);
  const start = total ? offset + 1 : 0;

  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Kembali</button>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 650 }}>Upload History</h1>
          <div className="sub">QA file yang diterima server · original CSV hanya tersedia untuk upload setelah raw-retention aktif</div>
        </div>
      </div>

      <div className="panel uploads-panel">
        <div className="table-filters">
          <input placeholder="Cari file name" value={fileName} onChange={(e) => setFileName(e.target.value)} />
          <input list="upload-devices" placeholder="Device ID" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} />
          <datalist id="upload-devices">{devices.map((id) => <option key={id} value={id} />)}</datalist>
          <select value={dataType} onChange={(e) => setDataType(e.target.value)}>
            <option value="">Semua tipe</option>
            <option value="gnss">GNSS</option>
            <option value="accel">Accel</option>
          </select>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">Semua mode</option>
            <option value="4g">4G</option>
            <option value="lora">LoRa</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Semua status</option>
            <option value="processed">Processed</option>
            <option value="processing">Processing</option>
            <option value="failed">Failed</option>
          </select>
          <button className="admin-btn upload-reset-btn" onClick={() => { setFileName(""); setDeviceId(""); setDataType(""); setMode(""); setStatus(""); setOffset(0); }}>Reset</button>
          <span className="table-total">{start}–{end} / {total}</span>
        </div>

        {error && <div className="admin-error">{error}</div>}
        {loading && !rows.length && <div className="loading">Memuat…</div>}
        {!loading && rows.length === 0 && <div className="sc-row">Belum ada upload yang cocok.</div>}

        {rows.length > 0 && (
          <div className="uploads-scroll">
            <table className="devtable uploads-table">
              <thead>
                <tr>
                  <th>Diterima</th><th>File</th><th>Device / Site</th><th>Mode</th><th>Tipe</th>
                  <th>Records</th><th>Status</th><th>Original</th><th>SHA256</th><th>Aksi</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.file_name}>
                    <td>{formatTime(row.received_at)}</td>
                    <td><code>{row.file_name}</code></td>
                    <td>{row.device_id}<div className="sub">{row.site_id || "—"}</div></td>
                    <td>{row.communication_mode || "—"}</td>
                    <td>{row.data_type}</td>
                    <td>{row.record_count ?? "—"}</td>
                    <td>
                      <span className={`upload-status upload-status-${row.processing_status}`}>
                        {row.processing_status}
                      </span>
                      {row.last_error && <div className="upload-error" title={row.last_error}>{row.last_error}</div>}
                    </td>
                    <td>{row.original_available ? formatBytes(row.byte_length) : <span className="sub">legacy / tidak tersimpan</span>}</td>
                    <td title={row.sha256 || ""}><code>{row.sha256 ? `${row.sha256.slice(0, 12)}…` : "—"}</code></td>
                    <td>
                      <button
                        className="admin-btn upload-download-btn"
                        disabled={!row.original_available || !canDownloadOriginal || downloading === row.file_name}
                        title={!row.original_available ? "Original CSV belum disimpan untuk upload lama" : (!canDownloadOriginal ? "Butuh role operator/admin" : "Download exact original CSV")}
                        onClick={() => downloadOriginal(row)}
                      >
                        {downloading === row.file_name ? "Mengunduh…" : "Download CSV"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="table-pager">
          <button className="admin-btn upload-pager-btn" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>← Sebelumnya</button>
          <button className="admin-btn upload-pager-btn" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Berikutnya →</button>
        </div>
      </div>
    </div>
  );
}
