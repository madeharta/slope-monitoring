import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import "./blast.css";

export default function BlastControl() {
  const navigate = useNavigate();
  const [historyPage, setHistoryPage] = useState(1);
  const [historyData, setHistoryData] = useState({ events: [], total: 0, total_pages: 1 });
  const [historyError, setHistoryError] = useState("");
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

    setHistoryPage(1);
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
    if (!baseId) { setHistoryData({ events: [], total: 0, total_pages: 1 }); return; }
    let active = true;
    async function loadHistory() {
      try {
        const res = await authFetch(
          `/api/v1/blast/trigger-history?base_id=${encodeURIComponent(baseId)}&page=${historyPage}&page_size=10`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        if (active) { setHistoryData(body); setHistoryError(""); }
      } catch (err) {
        if (active) setHistoryError(err?.message || "Failed to load history");
      }
    }
    loadHistory();
    const timer = window.setInterval(loadHistory, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [baseId, historyPage, authFetch]);

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
      `Send a blast trigger request to ${baseId}?\n\n` +
      `TimeOutTrigger: ${timeout} minutes\n\n` +
      "Note: this only confirms that the server stored the command. " +
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
        "TriggerStart and TimeOutTrigger are now stored on the server. " +
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
      `Reset TriggerStart for ${baseId} to 0?\n\n` +
      "TimeOutTrigger will be preserved."
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
        "TriggerStart has been reset to 0. TimeOutTrigger remains unchanged."
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

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 520px), 1fr))",
        gap: 24,
        alignItems: "stretch",
        width: "100%",
        maxWidth: 1440,
        margin: "24px auto 0",
      }}>
      <section className="panel blast-card" style={{ minWidth: 0, width: "100%", maxWidth: "none" }}>
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
          Delivery to BASE:
          <strong> next upload response / GET /api/config</strong>
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
            START and RESET require operator/admin access;
            the START endpoint also requires MFA.
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

      <section className="panel blast-card" aria-label="TriggerStart delivery and ACK" style={{ minWidth: 0, width: "100%", maxWidth: "none" }}>
        <div className="blast-section-head"><div><h2>TriggerStart · Device acknowledgment</h2></div></div>
        <div className="blast-config-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 210px), 1fr))" }}>
          <div><span>Server TriggerStart</span><strong>
            {triggerStatus?.server?.trigger_start == null ? "—" :
              `${triggerStatus.server.trigger_start} · ${triggerStatus.server.trigger_start === 0 ? "RESET" : "START"}`}
          </strong><small>{triggerStatus?.server?.reset_reason === "AUTO_TIMEOUT" ? "Automatically reset due to timeout" : "Server configuration status"}</small></div>
          <div><span>Device ACK</span><strong>
            {triggerStatus?.delivery?.acked ? `ACK ${triggerStatus.delivery.trigger_start} received` :
              triggerStatus?.delivery?.pending ? "Awaiting ACK" : "Not confirmed"}
          </strong><small>{triggerStatus?.delivery?.ack_server_at ?
            `Server received: ${new Date(triggerStatus.delivery.ack_server_at).toLocaleString()}` :
            "No matching ACK for the latest pending command"}</small></div>
        </div>
        {triggerStatus?.delivery?.ack_device_utc &&
          <div className="blast-delivery-note">Device time (UTC): <strong>{triggerStatus.delivery.ack_device_utc}</strong></div>}
        {triggerStatus?.error && <div className="admin-error" role="alert">ACK status unavailable: {triggerStatus.error}</div>}
      </section>
      </div>

      <section className="panel blast-card blast-history-v2" aria-label="TriggerStart History" style={{ width: "100%", maxWidth: 1440, margin: "24px auto 0" }}>
        <div className="blast-section-head">
          <div>
            <h3>TriggerStart History</h3>
          </div>
        </div>
        {(() => {
          const events = Array.isArray(historyData.events) ? historyData.events : [];
          const pageSize = 10;
          const totalPages = Math.max(1, historyData.total_pages || 1);
          const currentPage = Math.min(historyPage, totalPages);
          const visible = events;
          const formatServer = (value) => {
            if (!value) return "—";
            const date = new Date(value);
            if (Number.isNaN(date.valueOf())) return "—";
            return new Intl.DateTimeFormat("en-GB", {
              timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit",
              hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
            }).format(date);
          };
          if (!events.length) return <p>{historyError ? `Failed to load history: ${historyError}` : "No history for the selected BASE."}</p>;
          return <>
            <div style={{ width: "100%", overflowX: "auto", border: "1px solid #d8e2eb", borderRadius: 8 }}>
              <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 940, textAlign: "left", fontSize: 13 }}>
                <thead style={{ background: "#f3f6fa" }}><tr>
                  {["Server time (WIB)", "Device ID", "Event type", "TriggerStart", "Status", "Pending ID", "Device time (raw)", "Details"].map(label =>
                    <th key={label} scope="col" style={{ padding: "12px 10px", borderBottom: "1px solid #d8e2eb", whiteSpace: "nowrap" }}>{label}</th>)}
                </tr></thead>
                <tbody>{visible.map((item, idx) => {
                  const ack = item.kind === "DEVICE_ACK";
                  const rejected = item.kind === "ACK_REJECTED";
                  const timeout = item.kind === "AUTO_TIMEOUT_RESET";
                  const label = ack ? "Accepted" : rejected ? "Rejected" : timeout ? "Timeout" : "Other";
                  const tone = ack ? "#16764d" : rejected ? "#b42318" : timeout ? "#946200" : "#526579";
                  const cell = { padding: "10px", borderBottom: "1px solid #e7edf3" };
                  return <tr key={`${item.kind}-${item.id ?? item.pending_config_id ?? "x"}-${item.occurred_at ?? "x"}-${idx}`}>
                    <td style={{ ...cell, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{formatServer(item.occurred_at)}</td>
                    <td style={cell}>{item.device_id || (timeout ? "System" : "—")}</td>
                    <td style={cell}>{ack ? "Device ACK" : rejected ? "ACK rejected" : timeout ? "Automatic reset" : (item.kind || "—")}</td>
                    <td style={cell}>{item.trigger_start ?? "—"}</td>
                    <td style={cell}><span style={{ color: tone, fontWeight: 700 }}>{label}</span></td>
                    <td style={cell}>{item.pending_config_id ?? "—"}</td>
                    <td style={{ ...cell, whiteSpace: "nowrap" }}>{item.device_timestamp_utc || "—"}</td>
                    <td style={cell}>{rejected ? (item.reason_code || "Rejected by server") : timeout ? "Command timed out" : ack ? "ACK recorded" : "—"}</td>
                  </tr>;
                })}</tbody>
              </table>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
              <small>Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, historyData.total)} of {historyData.total} events.</small>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="admin-btn" type="button" disabled={currentPage <= 1} onClick={() => setHistoryPage(p => Math.max(1, p - 1))}>Previous</button>
                <span aria-live="polite">{currentPage} / {totalPages}</span>
                <button className="admin-btn" type="button" disabled={currentPage >= totalPages} onClick={() => setHistoryPage(p => Math.min(totalPages, p + 1))}>Next</button>
              </div>
            </div>
          </>;
        })()}
      </section>
    </div>
  );
}
