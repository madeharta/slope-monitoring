// Halaman Devices — GET/POST/PUT/DELETE /api/v1/devices (2026-09-20:
// Create/Update/Delete ditambahkan — sebelumnya cuma Read, dan bahkan
// TIDAK ADA cara mendaftarkan device sama sekali lewat aplikasi).

import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

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
          "  (kosongkan/Cancel untuk batal)"
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

  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Devices</h1>
        {isAdmin && <button className="admin-btn admin-btn-primary" style={{ marginLeft: "auto" }} onClick={() => setShowCreate((v) => !v)}>+ New Device</button>}
      </div>

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
              <button className="admin-btn admin-btn-primary" disabled={busy === "__new__" || !newDevice.device_id || !newDevice.device_type || !newDevice.site_id} onClick={createDevice}>Buat</button>
            </div>
            <span style={{ fontSize: 11 }}>The site must be registered first (see Sites). If missing from the list, enter its site ID manually.</span>
          </div>
        )}

        <div className="table-filters">
          <input placeholder="Search device ID…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
            <option value="">All sites</option>
            {sites.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All statuses</option>
            <option value="online">Online saja</option>
            <option value="offline">Offline saja</option>
          </select>
          <span className="table-total">{filtered ? filtered.length : 0} / {devices ? devices.length : 0} device</span>
        </div>

        {error && <div className="admin-error" style={{ marginBottom: 12, whiteSpace: "pre-line" }}>{error}</div>}
        {!devices && !error && <div className="loading">Loading…</div>}
        {filtered && filtered.length === 0 && <div className="sc-row">No devices match the filters.</div>}
        {filtered && filtered.length > 0 && (
          <table className="devtable">
            <thead>
              <tr>
                <th>Device ID</th><th>Name</th><th>Type</th><th>Site</th><th>Status</th><th>Last seen</th>
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
                      <td colSpan={2}>
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
                      <td>{d.last_seen ? new Date(d.last_seen).toLocaleString("id-ID") : "never"}</td>
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
