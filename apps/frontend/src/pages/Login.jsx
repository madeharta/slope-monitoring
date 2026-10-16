// MFA belum ditangani di sini — backend belum punya endpoint
// /auth/mfa/verify. Field MFA ditampilkan disabled+bercatatan (bukan
// dihilangkan), supaya jelas ini memang belum terpasang, bukan lupa dibuat.
//
// Styling (2026-09-19, revisi): sebelumnya elemen HTML polos tanpa CSS
// sama sekali. Sekarang pakai variabel desain yang SUDAH ADA di
// index.css (--bg/--panel/--ink/--accent/--line dst.) — TIDAK menambah
// warna/token baru, murni pakai yang sudah didefinisikan untuk
// Overview/TopBar, supaya halaman login terasa satu sistem dengan
// dashboard, bukan halaman asing yang ditempel.

import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      // Item 10 (2026-09-19): redirect BALIK ke halaman asal kalau
      // RequireAuth.jsx menyimpannya di location.state.from (mis. user
      // buka link /sites/lereng-a langsung tanpa login dulu) — sebelumnya
      // selalu redirect ke "/" apa pun asalnya.
      const dest = location.state?.from?.pathname || "/";
      navigate(dest, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-brand">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 20 L8.5 7 L12.5 14 L15.5 9 L22 20 Z" /></svg>
        <b>MAGRIS</b><span>LEWS</span>
      </div>

      <form onSubmit={handleSubmit} className="login-card">
        <h1>Masuk</h1>
        <p className="login-sub">Slope &amp; Blast Monitoring Console</p>

        <label className="login-field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="username"
            placeholder="operator@namadomain.id"
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            placeholder="••••••••"
          />
        </label>

        {/* REVISI 2026-09-20: field kode MFA di SINI (saat login) dihapus
            — field disabled sebelumnya menyiratkan MFA "belum aktif"
            secara keseluruhan, padahal fiturnya SEKARANG SUDAH BERFUNGSI
            (lihat MFAEnroll.jsx, /mfa/enroll setelah login). Yang BELUM
            terhubung spesifik cuma alur TANTANGAN MFA di titik LOGIN ini
            (untuk user yang sudah mengaktifkan MFA, form login perlu
            minta kode juga) — item terpisah, dicatat di
            GAPS_AND_PENDING_ITEMS.md, bukan disamarkan sebagai field mati. */}

        {error && <div className="login-error" role="alert">{error}</div>}

        <button type="submit" className="login-submit" disabled={submitting}>
          {submitting ? "Masuk…" : "Masuk"}
        </button>
      </form>
    </div>
  );
}
