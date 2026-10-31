// Halaman admin registrasi site baru — POST /api/v1/sites.
// REVISI 2026-09-20: latar/style ikut dashboard eksis (`.l2`, TopBar
// global) seperti halaman lain — cuma FORM-nya yang dibungkus kartu
// putih. Admin-only, dicek inline (bukan route guard terpisah) supaya
// tetap satu route group dengan Overview/SlopeDetail/Panduan.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function AdminSites() {
  const { authFetch, auth } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ site_id: "", name: "", lat: "", lon: "" });
  const [nearby, setNearby] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  if (auth?.role !== "admin") {
    return (
      <div className="l2 pgdoc2-page">
        <div className="l2head"><button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button></div>
        <div className="pgdoc2-card"><p>This page is restricted to administrators.</p></div>
      </div>
    );
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function checkNearby() {
    if (!form.lat || !form.lon) return;
    const r = await authFetch(`/api/v1/sites/nearby?lat=${form.lat}&lon=${form.lon}`);
    const body = await r.json();
    setNearby(body.nearby || []);
  }

  async function submit(force = false) {
    setSubmitting(true);
    setError(null);
    try {
      const r = await authFetch("/api/v1/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, lat: parseFloat(form.lat), lon: parseFloat(form.lon), force }),
      });
      const body = await r.json();
      if (!r.ok) {
        setError(body.detail);
        return;
      }
      setSuccess(`Site "${form.site_id}" berhasil dibuat.`);
      setForm({ site_id: "", name: "", lat: "", lon: "" });
      setNearby(null);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Register New Site</h1>
      </div>

      <div className="pgdoc2-card">
        <p className="pgdoc-lead">
          A site must be registered manually before devices can be associated with it. Incoming data does not automatically create a site.
        </p>

        <div className="admin-form">
          <label>Site ID<input value={form.site_id} onChange={set("site_id")} placeholder="SITE-B" /></label>
          <label>Name<input value={form.name} onChange={set("name")} placeholder="Slope B" /></label>
          <label>Latitude<input value={form.lat} onChange={set("lat")} onBlur={checkNearby} placeholder="-6.2" /></label>
          <label>Longitude<input value={form.lon} onChange={set("lon")} onBlur={checkNearby} placeholder="106.8" /></label>

          {nearby && nearby.length > 0 && (
            <div className="admin-warn">
              <strong>⚠ Nearby site detected:</strong>
              <ul>{nearby.map((n) => <li key={n.site_id}>{n.name} ({n.site_id}) — {n.distance_m.toFixed(0)}m</li>)}</ul>
              Confirm that this is a separate physical location before continuing.
            </div>
          )}

          {error && (
            <div className="admin-error">
              {error}
              <div style={{ marginTop: 8 }}>
                <button className="admin-btn" onClick={() => submit(true)} disabled={submitting}>Continue anyway</button>
              </div>
            </div>
          )}

          {success && <div className="admin-success">{success}</div>}

          <button className="admin-btn admin-btn-primary" onClick={() => submit(false)} disabled={submitting || !form.site_id || !form.name || !form.lat || !form.lon}>
            {submitting ? "Saving…" : "Create Site"}
          </button>
        </div>
      </div>
    </div>
  );
}
