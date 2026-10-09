import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import "./blast.css";

export default function BlastControl() {
  const navigate = useNavigate();
  const { authFetch, auth } = useAuth();

  const canOperate = auth?.role === "admin" || auth?.role === "operator";

  const [devices, setDevices] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [baseId, setBaseId] = useState("");
  const [config, setConfig] = useState(null);
  const [timeoutMinutes, setTimeoutMinutes] = useState("");

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;

    authFetch("/api/v1/devices")
      .then((r) => r.json())
      .then((body) => {
        if (alive) setDevices(body.devices || []);
      })
      .catch(() => {
        if (alive) setDevices([]);
      });

    return () => {
      alive = false;
    };
  }, [authFetch]);

  const sites = useMemo(
    () => [...new Set(devices.map((d) => d.site_id).filter(Boolean))].sort(),
    [devices]
  );

  useEffect(() => {
    if (!siteId) {
      setBaseId("");
      setConfig(null);
      return;
    }

    const candidates = devices.filter((d) => d.site_id === siteId);

    const base =
      candidates.find((d) => d.device_id === "BASE-01") ||
      candidates.find(
        (d) => String(d.device_type || "").toLowerCase() === "base"
      );

    setBaseId(base?.device_id || "");
  }, [devices, siteId]);

  async function refreshConfig(targetBaseId = baseId) {
    if (!targetBaseId) return;

    setError("");

    const response = await authFetch("/api/v1/device/config", {
      headers: {
        "X-Device-Id": targetBaseId,
      },
    });

    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    const nextConfig = body.config || {};

    setConfig(nextConfig);
    setTimeoutMinutes(String(nextConfig.TimeOutTrigger ?? ""));
  }

  useEffect(() => {
    if (!baseId) return;

    refreshConfig(baseId).catch((err) => {
      setError(err?.message || "Gagal membaca config BASE.");
    });
  }, [baseId]);

  async function startBlast() {
    if (!canOperate || !baseId || busy) return;

    const timeout = Number(timeoutMinutes);

    if (!Number.isInteger(timeout) || timeout <= 0) {
      setError("TimeOutTrigger harus bilangan bulat lebih dari 0 menit.");
      return;
    }

    const confirmed = window.confirm(
      `Kirim blast trigger request ke ${baseId}?\n\n` +
      `TimeOutTrigger: ${timeout} menit\n\n` +
      "Catatan: ini hanya menyatakan server menyimpan command. " +
      "Bukan bukti rover sudah ARMED."
    );

    if (!confirmed) return;

    setBusy(true);
    setMessage("");
    setError("");

    try {
      const response = await authFetch("/api/v1/blast/trigger", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          base_id: baseId,
          timeout_minutes: timeout,
        }),
      });

      const body = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(body.detail || `HTTP ${response.status}`);
      }

      setMessage(
        `TRIGGER REQUESTED · command #${body.command_id ?? "—"}. ` +
        "TriggerStart dan TimeOutTrigger sekarang tersimpan di server. " +
        "BASE akan menerima config dari response upload berikutnya atau GET /api/config."
      );

      await refreshConfig();
    } catch (err) {
      setError(err?.message || "Gagal membuat blast trigger request.");
    } finally {
      setBusy(false);
    }
  }

  async function resetBlast() {
    if (!canOperate || !baseId || busy) return;

    const confirmed = window.confirm(
      `Reset TriggerStart ${baseId} ke 0?\n\n` +
      "TimeOutTrigger akan tetap dipertahankan."
    );

    if (!confirmed) return;

    setBusy(true);
    setMessage("");
    setError("");

    try {
      const response = await authFetch("/api/v1/blast/reset", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          base_id: baseId,
        }),
      });

      const body = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(body.detail || `HTTP ${response.status}`);
      }

      setMessage(
        "TriggerStart di-reset ke 0. TimeOutTrigger tetap dipertahankan."
      );

      await refreshConfig();
    } catch (err) {
      setError(err?.message || "Gagal reset TriggerStart.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="l2 pgdoc2-page blast-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>
          ← Kembali
        </button>

        <div>
          <h1 style={{ fontSize: 18, fontWeight: 650 }}>
            Blast Control — LoRa v1.6
          </h1>
          <div className="sub">
            Web/server bertanggung jawab sampai BASE menerima config.
            Distribusi trigger dari BASE ke rover melalui LoRa adalah ranah ITB.
          </div>
        </div>
      </div>

      <div className="blast-warning">
        <strong>COMMAND STATE ≠ FIELD ACKNOWLEDGEMENT</strong>
        <span>
          TriggerStart=1 berarti command sudah tersimpan di server.
          Itu belum membuktikan rover sudah menerima trigger, ARMED,
          mendeteksi blast, atau selesai merekam.
        </span>
      </div>

      <section className="panel blast-card">
        <div className="blast-section-head">
          <div>
            <h2>Blast command</h2>
            <span>Site-level request state for the authoritative BASE.</span>
          </div>
          <span className="blast-role-badge">
            {canOperate ? "OPERATOR CONTROL" : "VIEW ONLY"}
          </span>
        </div>

        <div className="blast-fields">
          <label>
            <span>Site</span>
            <select
              value={siteId}
              onChange={(e) => setSiteId(e.target.value)}
            >
              <option value="">— pilih site —</option>

              {sites.map((site) => (
                <option key={site} value={site}>
                  {site}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>BASE authoritative</span>
            <input value={baseId || "—"} readOnly />
          </label>

          <label>
            <span>TimeOutTrigger · menit</span>
            <input
              type="number"
              min="1"
              step="1"
              value={timeoutMinutes}
              onChange={(e) => setTimeoutMinutes(e.target.value)}
              disabled={!canOperate || !baseId || busy}
            />
          </label>
        </div>

        <div className="blast-config-grid">
          <div>
            <span>Command state</span>
            <strong>
              {config?.TriggerStart === 1
                ? "TRIGGER REQUESTED"
                : config
                ? "IDLE"
                : "—"}
            </strong>
          </div>

          <div>
            <span>TriggerStart</span>
            <strong>{config?.TriggerStart ?? "—"}</strong>
          </div>

          <div>
            <span>threshold_g</span>
            <strong>
              {config?.threshold_g == null ? "—" : `${config.threshold_g} g`}
            </strong>
          </div>

          <div>
            <span>time_record_ms</span>
            <strong>
              {config?.time_record_ms == null
                ? "—"
                : `${config.time_record_ms} ms`}
            </strong>
          </div>
        </div>

        <div className="blast-delivery-note">
          Delivery ke BASE:
          <strong> response upload berikutnya / GET /api/config</strong>
        </div>

        <div className="blast-actions">
          <button
            className="admin-btn admin-btn-primary"
            disabled={!canOperate || !baseId || busy}
            onClick={startBlast}
          >
            {busy ? "Processing…" : "START BLAST WINDOW"}
          </button>

          <button
            className="admin-btn"
            disabled={!canOperate || !baseId || busy}
            onClick={resetBlast}
          >
            RESET / CANCEL
          </button>

          <button
            className="admin-btn"
            disabled={!baseId || busy}
            onClick={() =>
              refreshConfig().catch((err) =>
                setError(err?.message || "Gagal membaca config BASE.")
              )
            }
          >
            Refresh config
          </button>
        </div>

        {!canOperate && (
          <div className="blast-note">
            Role viewer hanya dapat melihat konfigurasi.
            START dan RESET memerlukan operator/admin;
            endpoint START juga tetap dijaga MFA oleh backend.
          </div>
        )}

        {message && (
          <div className="settings-message" role="status">
            {message}
          </div>
        )}

        {error && (
          <div className="admin-error" role="alert">
            {error}
          </div>
        )}
      </section>

      <details className="panel blast-flow">
        <summary className="blast-flow-summary">
          <span>
            <strong>LoRa v1.6 command flow</strong>
            <small>Reference flow · expand when needed</small>
          </span>
          <span aria-hidden>⌄</span>
        </summary>

        <div className="blast-flow-body">
          <pre>{`WEB
↓
operator set TimeOutTrigger
↓
operator START / TriggerStart = 1
↓
SERVER simpan config BASE
↓
BASE menerima TriggerStart + TimeOutTrigger
dari response upload berikutnya / GET /api/config
↓
========== START RANAH ITB ==========
BASE kirim trigger via LoRa
+ TimeOutTrigger
+ time_record_ms
↓
ROVER-B1-01 & ROVER-B1-02 menunggu accel > threshold_g
↓
blast terdeteksi → record → simpan file SD
atau
timeout → kembali normal tanpa record
========== END RANAH ITB ==========`}</pre>
        </div>
      </details>
    </div>
  );
}
