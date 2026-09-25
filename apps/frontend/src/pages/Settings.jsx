import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
const DEVICE_KEYS = [
  { key: "periodic_upload_s", label: "Interval upload (detik)", type: "number" },
  { key: "firmware_version", label: "Target firmware version", type: "text" },
  { key: "threshold_g", label: "Threshold accel (g)", type: "number" },
  { key: "time_record_ms", label: "Durasi rekaman ledakan (ms)", type: "number" },
  { key: "TimeOutTrigger", label: "Timeout trigger (menit)", type: "number" },
];
export default function Settings() {
  const { authFetch, auth } = useAuth();
  const navigate = useNavigate();
  const [devices, setDevices] = useState(null);
  const [site, setSite] = useState("");
  const [device, setDevice] = useState("");
  const [config, setConfig] = useState({});
  const [saving, setSaving] = useState(null);
  const [message, setMessage] = useState(null);
  useEffect(() => {
    authFetch("/api/v1/devices").then((r) => r.json()).then((body) => setDevices(body.devices || [])).catch(() => {});
  }, [authFetch]);
  const sites = [...new Set((devices || []).map((d) => d.site_id))];
  const devicesAtSite = (devices || []).filter((d) => d.site_id === site);
  useEffect(() => {
    if (!device) return;
    let alive = true;
    authFetch("/api/v1/device/config", { headers: { "X-Device-Id": device } })
      .then((r) => r.json())
      .then((body) => { if (alive) setConfig(body.config || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [device, authFetch]);
  async function save(key, value) {
    if (auth?.role !== "admin" && auth?.role !== "operator") {
      setMessage("Perlu role operator/admin untuk mengubah config.");
      return;
    }
    setSaving(key);
    setMessage(null);
    try {
      const r = await authFetch(`/api/v1/device/config/${device}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_key: key, config_value: value }),
      });
      const body = await r.json();
      if (!r.ok) { setMessage(body.detail || "Gagal menyimpan."); return; }
      const next = key === "firmware_version" ? value : Number(value);
      setConfig((c) => ({ ...c, [key]: next }));
      setMessage(`"${key}" tersimpan.`);
    } finally {
      setSaving(null);
    }
  }
  async function saveBattery(deviceId, key, value) {
    setSaving(`${deviceId}:${key}`);
    setMessage(null);
    try {
      const r = await authFetch(`/api/v1/device/config/${deviceId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_key: key, config_value: Number(value) }),
      });
      const body = await r.json();
      if (!r.ok) { setMessage(body.detail || "Gagal menyimpan."); return; }
      const field = key === "battery_cal_m" ? "m" : "c";
      setConfig((c) => ({ ...c, battery_cal: { ...(c.battery_cal || {}), [deviceId]: { ...(c.battery_cal?.[deviceId] || {}), [field]: Number(value) } } }));
      setMessage(`Kalibrasi baterai ${deviceId} tersimpan.`);
    } finally {
      setSaving(null);
    }
  }
  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Kembali</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Settings — Konfigurasi Device</h1>
      </div>
      <div className="pgdoc2-card">
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 6 }}>1. Pilih site</label>
          <select value={site} onChange={(e) => { setSite(e.target.value); setDevice(""); }} style={{ minWidth: 240 }}>
            <option value="">— pilih site —</option>
            {sites.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {site && (
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 6 }}>2. Pilih device</label>
            <div style={{ display: "flex", gap: 8 }}>
              {devicesAtSite.map((d) => (
                <button key={d.device_id} className={"admin-btn" + (device === d.device_id ? " admin-btn-primary" : "")} onClick={() => setDevice(d.device_id)}>{d.device_id}</button>
              ))}
            </div>
          </div>
        )}
        {device && (
          <>
            <label style={{ fontSize: 13, fontWeight: 600, display: "block", marginBottom: 6 }}>3. Config — {device}</label>
            <div className="admin-form">
              {DEVICE_KEYS.map(({ key, label, type }) => (
                <SettingRow key={key} label={label} type={type} value={config[key]} onSave={(v) => save(key, v)} saving={saving === key} />
              ))}
            </div>
            <label style={{ fontSize: 13, fontWeight: 600, display: "block", margin: "18px 0 6px" }}>4. Kalibrasi baterai site</label>
            <div className="admin-form">
              {Object.entries(config.battery_cal || {}).map(([deviceId, cal]) => (
                <div key={deviceId} style={{ display: "grid", gridTemplateColumns: "160px 1fr 1fr", gap: 10, alignItems: "center" }}>
                  <strong>{deviceId}</strong>
                  <SettingRow label="m" type="number" value={cal?.m} onSave={(v) => saveBattery(deviceId, "battery_cal_m", v)} saving={saving === `${deviceId}:battery_cal_m`} />
                  <SettingRow label="c" type="number" value={cal?.c} onSave={(v) => saveBattery(deviceId, "battery_cal_c", v)} saving={saving === `${deviceId}:battery_cal_c`} />
                </div>
              ))}
            </div>
            <div style={{ marginTop: 16, fontSize: 13 }}>TriggerStart: <strong>{config.TriggerStart ?? 0}</strong></div>
          </>
        )}
        {message && <div style={{ marginTop: 14, fontSize: 13, color: "#333" }}>{message}</div>}
      </div>
    </div>
  );
}
function SettingRow({ label, value, onSave, saving, type = "number" }) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => setDraft(value ?? ""), [value]);
  return (
    <label style={{ flexDirection: "row", alignItems: "center", gap: 10, display: "flex" }}>
      <span style={{ minWidth: 140 }}>{label}</span>
      <input type={type} value={draft} onChange={(e) => setDraft(e.target.value)} style={{ flex: 1 }} />
      <button className="admin-btn" onClick={() => onSave(draft)} disabled={saving}>{saving ? "…" : "Simpan"}</button>
    </label>
  );
}
