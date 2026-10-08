import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
const ROLES = ["viewer", "operator", "admin"];
export default function Users() {
  const { authFetch, auth } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState(null);
  const [error, setError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newUser, setNewUser] = useState({ email: "", password: "", role: "viewer" });
  const [busy, setBusy] = useState(null);
  if (auth?.role !== "admin") {
    return (
      <div className="l2 pgdoc2-page">
        <div className="l2head"><button className="pgdoc-back" onClick={() => navigate("/")}>← Kembali</button></div>
        <div className="pgdoc2-card"><p>Halaman ini khusus role admin.</p></div>
      </div>
    );
  }
  function reload() {
    authFetch("/api/v1/users").then((r) => r.json()).then((body) => setUsers(body.users || [])).catch((e) => setError(String(e)));
  }
  useEffect(() => { reload(); }, []);
  async function createUser() {
    setBusy("__new__");
    setError(null);
    try {
      const r = await authFetch("/api/v1/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newUser),
      });
      const body = await r.json();
      if (!r.ok) { setError(body.detail); return; }
      setNewUser({ email: "", password: "", role: "viewer" });
      setShowCreate(false);
      reload();
    } finally {
      setBusy(null);
    }
  }
  async function changeRole(user_id, role) {
    setBusy(user_id);
    setError(null);
    try {
      const r = await authFetch(`/api/v1/users/${user_id}/role`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      const body = await r.json();
      if (!r.ok) { setError(body.detail); return; }
      reload();
    } finally {
      setBusy(null);
    }
  }
  async function toggleDisable(u) {
    setBusy(u.user_id);
    setError(null);
    try {
      const url = `/api/v1/users/${u.user_id}${u.disabled_at ? "/enable" : ""}`;
      const r = await authFetch(url, { method: u.disabled_at ? "POST" : "DELETE" });
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
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Users</h1>
        <button className="admin-btn admin-btn-primary" style={{ marginLeft: "auto" }} onClick={() => setShowCreate((v) => !v)}>+ User Baru</button>
      </div>
      <div className="panel" style={{ maxWidth: 950, margin: "0 auto", padding: 20 }}>
        {showCreate && (
          <div className="admin-warn" style={{ marginBottom: 16, background: "var(--panel-2)", color: "var(--ink-2)", borderColor: "var(--line)" }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input placeholder="Email" value={newUser.email} onChange={(e) => setNewUser((u) => ({ ...u, email: e.target.value }))} />
              <input placeholder="Password (min 8 karakter)" type="password" value={newUser.password} onChange={(e) => setNewUser((u) => ({ ...u, password: e.target.value }))} />
              <select value={newUser.role} onChange={(e) => setNewUser((u) => ({ ...u, role: e.target.value }))}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
              <button className="admin-btn admin-btn-primary" disabled={busy === "__new__" || !newUser.email || newUser.password.length < 8} onClick={createUser}>Buat</button>
            </div>
          </div>
        )}
        {error && <div className="admin-error" style={{ marginBottom: 12 }}>{error}</div>}
        {!users && !error && <div className="loading">Memuat…</div>}
        {users && (
          <table className="devtable">
            <thead>
              <tr><th>Email</th><th>Role</th><th>MFA</th><th>Status</th><th>Dibuat</th><th>Aksi</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id}>
                  <td>{u.email}</td>
                  <td>
                    <select value={u.role} disabled={busy === u.user_id} onChange={(e) => changeRole(u.user_id, e.target.value)}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>{u.mfa_enabled ? "Aktif" : "—"}</td>
                  <td>
                    <span className={"sc-dot " + (u.disabled_at ? "sc-off" : "sc-on")} style={{ display: "inline-block", marginRight: 6 }} />
                    {u.disabled_at ? "Nonaktif" : "Aktif"}
                  </td>
                  <td>{u.created_at ? new Date(u.created_at).toLocaleDateString("id-ID") : "—"}</td>
                  <td>
                    <button className="devlink" style={{ color: u.disabled_at ? "var(--ok)" : "var(--bahaya)" }} disabled={busy === u.user_id} onClick={() => toggleDisable(u)}>
                      {u.disabled_at ? "Aktifkan" : "Nonaktifkan"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
