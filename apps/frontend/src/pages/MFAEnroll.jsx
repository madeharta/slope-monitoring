import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
export default function MFAEnroll() {
  const { authFetch } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [secret, setSecret] = useState(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  async function startEnroll() {
    setBusy(true);
    setError(null);
    try {
      const r = await authFetch("/api/v1/auth/mfa/enroll", { method: "POST" });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Gagal memulai enrollment MFA");
      setSecret(body.secret);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function confirmCode(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await authFetch("/api/v1/auth/mfa/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Kode salah");
      setStep(3);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  function copySecret() {
    navigator.clipboard?.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  return (
    <div className="l2 pg-page">
      <div className="pg-header">
        <button className="pg-back" onClick={() => navigate(-1)} aria-label="Kembali">←</button>
        <h1>Aktifkan Verifikasi Dua Langkah (MFA)</h1>
      </div>
      {step === 1 && (
        <div className="panel pg-card" style={{ maxWidth: 480 }}>
          <p className="pg-body">
            Wajib untuk aksi berisiko tinggi seperti memicu ledakan dari dashboard.
            Butuh aplikasi authenticator di HP Anda (Google Authenticator, Authy, atau sejenisnya — gratis).
          </p>
          {error && <div className="login-error" role="alert" style={{ marginTop: 10 }}>{error}</div>}
          <button className="login-submit" style={{ marginTop: 14 }} onClick={startEnroll} disabled={busy}>
            {busy ? "Memulai…" : "Mulai Aktivasi"}
          </button>
        </div>
      )}
      {step === 2 && (
        <div className="panel pg-card" style={{ maxWidth: 480 }}>
          <h2>Langkah 1 — Masukkan kode ini ke app Anda</h2>
          <p className="pg-body">
            Buka app authenticator → tambah akun baru → pilih <b>"Masukkan kode setup manual"</b> (bukan scan QR)
            → tempel kode di bawah ini:
          </p>
          <div
            style={{
              fontFamily: "var(--mono)", fontSize: 16, letterSpacing: "0.08em", padding: "12px 14px",
              background: "var(--panel-2)", border: "1px solid var(--line)", borderRadius: 8, margin: "12px 0",
              wordBreak: "break-all", userSelect: "all",
            }}
          >
            {secret}
          </div>
          <button className="pg-back" style={{ width: "auto", padding: "6px 12px", fontSize: 12 }} onClick={copySecret}>
            {copied ? "Tersalin ✓" : "Salin kode"}
          </button>
          <h2 style={{ marginTop: 20 }}>Langkah 2 — Masukkan 6 digit dari app</h2>
          <form onSubmit={confirmCode} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
            <input
              type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="000000"
              value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              style={{ fontFamily: "var(--mono)", fontSize: 20, letterSpacing: "0.3em", textAlign: "center" }}
              required
            />
            {error && <div className="login-error" role="alert">{error}</div>}
            <button type="submit" className="login-submit" disabled={busy || code.length !== 6}>
              {busy ? "Memverifikasi…" : "Konfirmasi"}
            </button>
          </form>
        </div>
      )}
      {step === 3 && (
        <div className="panel pg-card" style={{ maxWidth: 480, borderColor: "var(--ok)" }}>
          <h2>MFA aktif ✓</h2>
          <p className="pg-body">
            Login berikutnya akan minta kode dari app Anda untuk aksi berisiko tinggi.
          </p>
          <button className="login-submit" style={{ marginTop: 14 }} onClick={() => navigate("/")}>
            Selesai
          </button>
        </div>
      )}
    </div>
  );
}
