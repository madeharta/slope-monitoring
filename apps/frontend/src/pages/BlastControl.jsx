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
  const [triggerStatus, setTriggerStatus] = useState(null);
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
      setTriggerStatus(null);
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

  async function refreshTriggerStatus(targetBaseId = baseId) {
    if (!targetBaseId) return;
    const response = await authFetch(
      `/api/v1/blast/trigger-status?base_id=${encodeURIComponent(targetBaseId)}`
    );
    if (!response.ok) throw new Error(`Trigger status HTTP ${response.status}`);
    const body = await response.json();
    if (targetBaseId === baseId) setTriggerStatus(body);
  }

  useEffect(() => {
    if (!baseId) return;
    setTriggerStatus(null);
    let active = true;
    async function update() {
      try {
        const response = await authFetch(
          `/api/v1/blast/trigger-status?base_id=${encodeURIComponent(baseId)}`
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (active) setTriggerStatus(body);
      } catch (err) {
        if (active) setTriggerStatus({ error: err.message });
      }
    }
    update();
    const timer = window.setInterval(update, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [baseId, authFetch]);

  useEffect(() => {
    if (!baseId) return;

    refreshConfig(baseId).catch((err) => {
      setError(err?.message || "Failed to read BASE configuration.");
    });
  }, [baseId]);

  async function startBlast() {
    if (!canOperate || !baseId || busy) return;

    const timeout = Number(timeoutMinutes);

    if (!Number.isInteger(timeout) || timeout <= 0) {
      setError("TimeOutTrigger must be an integer greater than zero minutes.");
      return;
    }

    const confirmed = window.confirm(
      `Kirim blast trigger request ke ${baseId}?\n\n` +
      `TimeOutTrigger: ${timeout} menit\n\n` +
      "Catatan: ini hanya menyatakan server menyimpan command. " +
      "This is not evidence that the rover is ARMED."
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
        "BASE receives configuration from its next upload response or GET /api/config."
      );

      await refreshConfig();
      await refreshTriggerStatus();
    } catch (err) {
      setError(err?.message || "Failed to create blast trigger request.");
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
      await refreshTriggerStatus();
    } catch (err) {
      setError(err?.message || "Failed to reset TriggerStart.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="l2 pgdoc2-page blast-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>
          ← Back
        </button>

        <div>
          <h1 style={{ fontSize: 18, fontWeight: 650 }}>
            Blast Control — LoRa v1.6
          </h1>
          <div className="sub">
            The web/server is responsible until BASE receives the configuration.
            Trigger distribution from BASE to rovers over LoRa is managed by ITB.
          </div>
        </div>
      </div>

      <div className="blast-warning">
        <strong>COMMAND STATE ≠ FIELD ACKNOWLEDGEMENT</strong>
        <span>
          TriggerStart=1 means the command has been stored on the server.
          This does not prove that the rover has received the trigger or is ARMED,
          detected a blast, or completed recording.
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
              <option value="">— select site —</option>

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
            <span>TimeOutTrigger · minutes</span>
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
                setError(err?.message || "Failed to read BASE configuration.")
              )
            }
          >
            Refresh config
          </button>
        </div>

        {!canOperate && (
          <div className="blast-note">
            Users with the viewer role can only view the configuration.
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

      <section className="panel blast-card" aria-label="Trigger delivery and ACK">
        <div className="blast-section-head"><div><h2>TriggerStart · Konfirmasi perangkat</h2>
          <span>Status server dipisahkan dari pengakuan perangkat.</span></div></div>
        <div className="blast-config-grid">
          <div><span>Server TriggerStart</span><strong>
            {triggerStatus?.server?.trigger_start == null ? "—" :
              `${triggerStatus.server.trigger_start} · ${triggerStatus.server.trigger_start === 0 ? "RESET" : "START"}`}
          </strong><small>{triggerStatus?.server?.reset_reason === "AUTO_TIMEOUT" ? "RESET otomatis karena timeout" : "Status konfigurasi server"}</small></div>
          <div><span>ACK perangkat</span><strong>
            {triggerStatus?.delivery?.acked ? `ACK ${triggerStatus.delivery.trigger_start} diterima` :
              triggerStatus?.delivery?.pending ? "Menunggu ACK" : "Belum terkonfirmasi"}
          </strong><small>{triggerStatus?.delivery?.ack_server_at ?
            `Server menerima: ${new Date(triggerStatus.delivery.ack_server_at).toLocaleString()}` :
            "Tidak ada ACK yang cocok untuk pending command terbaru"}</small></div>
        </div>
        {triggerStatus?.delivery?.ack_device_utc &&
          <div className="blast-delivery-note">Waktu perangkat (UTC): <strong>{triggerStatus.delivery.ack_device_utc}</strong></div>}
        {triggerStatus?.error && <div className="admin-error" role="alert">Status ACK belum tersedia: {triggerStatus.error}</div>}
        <h3>Riwayat TriggerStart</h3>
        {triggerStatus?.events?.length ? (
          <div style={{ display: "grid", gap: 8 }}>
            {triggerStatus.events.map((item, index) => (
              <div className="blast-delivery-note" key={`${item.kind}-${item.occurred_at}-${index}`}>
                <strong>{item.kind === "DEVICE_ACK" ? `ACK perangkat · ${item.trigger_start}` : "RESET otomatis · timeout"}</strong>
                <span> · {new Date(item.occurred_at).toLocaleString()}</span>
              </div>
            ))}
          </div>
        ) : <p>Belum ada riwayat ACK atau timeout.</p>}
        <div className="blast-delivery-note">ACK menyatakan perangkat melaporkan penyimpanan konfigurasi. Bukan bukti peledakan atau ACK spesifik command bila firmware tidak mengirim command ID.</div>
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
from the next upload response / GET /api/config
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
