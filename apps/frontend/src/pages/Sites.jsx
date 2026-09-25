import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { getOverview } from "../api";
import { useAuth } from "../context/AuthContext.jsx";
export default function Sites() {
  const navigate = useNavigate();
  const { authFetch, auth } = useAuth();
  const [slopes, setSlopes] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [editDraft, setEditDraft] = useState({ name: "", lat: "", lon: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const isAdmin = auth?.role === "admin";
  function reload() {
    getOverview().then((o) => setSlopes(o.slopes || [])).catch(() => {});
  }
  useEffect(() => { reload(); }, []);
  const filtered = useMemo(() => {
    if (!slopes) return null;
    return slopes.filter((s) => {
      if (statusFilter !== "all" && s.status !== statusFilter) return false;
      if (search && !(s.name || "").toLowerCase().includes(search.toLowerCase()) && !s.site_id.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [slopes, statusFilter, search]);
  function startEdit(s) {
    setEditing(s.site_id);
    setEditDraft({ name: s.name, lat: s.lat, lon: s.lon });
    setError(null);
  }
  async function saveEdit(site_id) {
    setBusy(site_id);
    setError(null);
    try {
      const r = await authFetch(`/api/v1/sites/${site_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editDraft.name, lat: parseFloat(editDraft.lat), lon: parseFloat(editDraft.lon) }),
      });
      const body = await r.json();
      if (!r.ok) { setError(body.detail); return; }
      setEditing(null);
      reload();
    } finally {
      setBusy(null);
    }
  }
  async function del(site_id) {
    if (!window.confirm(`Hapus site "${site_id}"? Tindakan ini tidak bisa dibatalkan.`)) return;
    setBusy(site_id);
    setError(null);
    try {
      const r = await authFetch(`/api/v1/sites/${site_id}`, { method: "DELETE" });
      const body = await r.json();
      if (!r.ok) { setError(body.detail); return; }
      reload();
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Kembali</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Sites</h1>
        {isAdmin && <button className="admin-btn admin-btn-primary" style={{ marginLeft: "auto" }} onClick={() => navigate("/admin/sites")}>+ Site Baru</button>}
      </div>
      <div className="panel" style={{ maxWidth: 1050, margin: "0 auto", padding: 20 }}>
        <div className="table-filters">
          <input placeholder="Cari nama/site ID…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">Semua status</option>
            <option value="normal">Normal</option>
            <option value="siaga">Siaga</option>
            <option value="bahaya">Bahaya</option>
          </select>
          <span className="table-total">{filtered ? filtered.length : 0} / {slopes ? slopes.length : 0} site</span>
        </div>
        {error && <div className="admin-error" style={{ marginBottom: 12 }}>{error}</div>}
        {!slopes && <div className="loading">Memuat…</div>}
        {filtered && filtered.length === 0 && <div className="sc-row">Tidak ada site yang cocok filter.</div>}
        {filtered && filtered.length > 0 && (
          <table className="devtable">
            <thead>
              <tr>
                <th>Site ID</th><th>Nama</th><th>Status</th><th>Lat/Lon</th><th>Reading terakhir</th>
                {isAdmin && <th>Aksi</th>}
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.site_id}>
                  <td><button className="devlink" onClick={() => navigate(`/sites/${s.site_id}`)}>{s.site_id}</button></td>
                  {editing === s.site_id ? (
                    <>
                      <td><input value={editDraft.name} onChange={(e) => setEditDraft((d) => ({ ...d, name: e.target.value }))} style={{ width: 110 }} /></td>
                      <td>
                        <span className={"sc-dot " + (s.status === "bahaya" ? "sc-off" : "sc-on")} style={{ display: "inline-block", marginRight: 6, background: s.status === "bahaya" ? "var(--bahaya)" : s.status === "siaga" ? "var(--siaga)" : "var(--ok)" }} />
                        {s.status}
                      </td>
                      <td>
                        <input value={editDraft.lat} onChange={(e) => setEditDraft((d) => ({ ...d, lat: e.target.value }))} style={{ width: 70 }} />{" "}
                        <input value={editDraft.lon} onChange={(e) => setEditDraft((d) => ({ ...d, lon: e.target.value }))} style={{ width: 70 }} />
                      </td>
                      <td>{s.reading ? `${s.reading.value} ${s.reading.unit}` : "—"}</td>
                      <td>
                        <button className="devlink" disabled={busy === s.site_id} onClick={() => saveEdit(s.site_id)}>Simpan</button>{" "}
                        <button className="devlink" onClick={() => setEditing(null)}>Batal</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{s.name}</td>
                      <td>
                        <span className={"sc-dot " + (s.status === "bahaya" ? "sc-off" : "sc-on")} style={{ display: "inline-block", marginRight: 6, background: s.status === "bahaya" ? "var(--bahaya)" : s.status === "siaga" ? "var(--siaga)" : "var(--ok)" }} />
                        {s.status}
                      </td>
                      <td>{s.lat?.toFixed(4)}, {s.lon?.toFixed(4)}</td>
                      <td>{s.reading ? `${s.reading.value} ${s.reading.unit} (${s.reading.quantity})` : "—"}</td>
                      {isAdmin && (
                        <td>
                          <button className="devlink" onClick={() => startEdit(s)}>Edit</button>{" "}
                          <button className="devlink" style={{ color: "var(--bahaya)" }} disabled={busy === s.site_id} onClick={() => del(s.site_id)}>Hapus</button>
                        </td>
                      )}
                    </>
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
