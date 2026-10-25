// Enrollment MFA — SENGAJA tanpa QR code (butuh library tambahan). Cukup
// tampilkan secret sebagai teks yang bisa di-copy, user masukkan manual
// ke authenticator app lewat opsi "Enter a setup key" / "Masukkan kode
// manual" (ada di SEMUA app authenticator standar — Google Authenticator,
// Authy, 1Password, dll, tidak perlu scan kamera).
//
// Alur 2 langkah:
//   1. POST /auth/mfa/enroll -> tampilkan secret, user salin ke app-nya
//   2. User masukkan 6 digit kode dari app -> POST /auth/mfa/verify
//      -> sukses = enrollment selesai

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
      if (!r.ok) throw new Error(body.detail || "Failed to start MFA enrollment");
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
        <button className="pg-back" onClick={() => navigate(-1)} aria-label="Back">←</button>
        <h1>Enable Two-Factor Authentication (MFA)</h1>
      </div>

      {step === 1 && (
        <div className="panel pg-card" style={{ maxWidth: 480 }}>
          <p className="pg-body">
            Required for high-risk actions such as initiating a blast from the dashboard.
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
          <h2>Step 1 — Enter this code in your authenticator app</h2>
          <p className="pg-body">
            Open your authenticator app → add an account → select <b>"Enter a manual setup key"</b> (do not scan a QR code)
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

          <h2 style={{ marginTop: 20 }}>Step 2 — Enter the six-digit code from your app</h2>
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
          <h2>MFA enabled ✓</h2>
          <p className="pg-body">
            Future high-risk actions will require the authenticator code.
          </p>
          <button className="login-submit" style={{ marginTop: 14 }} onClick={() => navigate("/")}>
            Selesai
          </button>
        </div>
      )}
    </div>
  );
}
