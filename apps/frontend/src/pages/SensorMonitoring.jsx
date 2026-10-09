import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import PanelChart from "../components/PanelChart.jsx";
import { getPalette } from "../theme";
import { useStore } from "../store";
import "./sensors.css";

const DEMO_SITE = "SYNTHETIC-DEMO";
const DEMO_DEVICE = "ROVER-DEMO-01";
const pts = (rows, key) => rows.map((r) => [r.timestamp_utc, r[key]]);
const fmt = (v, d = 4) => v == null ? "—" : Number(v).toFixed(d);

function syntheticGnss() {
  const end = Date.UTC(2026, 9, 9, 12, 0, 0);
  return Array.from({ length: 288 }, (_, k) => {
    const phase = k / 34;
    return {
      timestamp_utc: new Date(end - (287 - k) * 300000).toISOString(),
      device_id: DEMO_DEVICE, site_id: DEMO_SITE,
      latitude: -6.8671 + Math.sin(phase) * 0.000004,
      longitude: 107.57875 + Math.cos(phase * 0.87) * 0.000004,
      altitude_m: 904.4 + Math.sin(phase * 0.41) * 0.08,
      gnss_fix_type: 4,
      h_acc_m: 0.03 + (1 + Math.sin(phase * 1.7)) * 0.01,
      source_file: "synthetic://gnss/demo-24h-v1",
      validation_status: "not_applicable",
    };
  });
}

function syntheticWaveform() {
  const start = Date.UTC(2026, 9, 9, 11, 59, 58);
  return Array.from({ length: 240 }, (_, i) => {
    const x = (i - 95) / 18;
    const env = Math.exp(-(x * x));
    const a = Math.sin(i * 0.82) * env;
    const b = Math.sin(i * 1.07 + 0.7) * env;
    return {
      timestamp_utc: new Date(start + i * 10).toISOString(),
      device_id: DEMO_DEVICE, sample_index: i,
      adxl355_x_mps2: 0.08 * Math.sin(i * 0.11) + 7.2 * a,
      adxl355_y_mps2: 0.07 * Math.cos(i * 0.13) + 5.8 * b,
      adxl355_z_mps2: 9.81 + 0.06 * Math.sin(i * 0.09) + 4.4 * a,
      mpu9250_x_mps2: 0.10 * Math.sin(i * 0.12) + 6.7 * b,
      mpu9250_y_mps2: 0.08 * Math.cos(i * 0.10) + 5.1 * a,
      mpu9250_z_mps2: 9.81 + 0.07 * Math.sin(i * 0.08) + 4.0 * b,
      source_file: "synthetic://accel/blast-demo-v1",
    };
  });
}

export default function SensorMonitoring() {
  const navigate = useNavigate();
  const { authFetch } = useAuth();
  const variant = useStore((s) => s.variant);
  const pal = getPalette(variant);
  const [mode, setMode] = useState("actual");
  const [devices, setDevices] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [gnss, setGnss] = useState([]);
  const [events, setEvents] = useState([]);
  const [eventFile, setEventFile] = useState("");
  const [wave, setWave] = useState([]);
  const [waveMeta, setWaveMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "actual") return;
    authFetch("/api/v1/devices").then((r) => r.json())
      .then((b) => setDevices(b.devices || [])).catch(() => setDevices([]));
  }, [mode, authFetch]);

  const sites = useMemo(() => [...new Set(devices.map((d) => d.site_id).filter(Boolean))].sort(), [devices]);
  const siteDevices = useMemo(() => devices.filter((d) => d.site_id === siteId), [devices, siteId]);

  async function refreshActual() {
    if (!siteId || !deviceId) return;
    setBusy(true); setError("");
    try {
      const [gr, er] = await Promise.all([
        authFetch(`/api/v1/sensors/gnss?site_id=${encodeURIComponent(siteId)}&device_id=${encodeURIComponent(deviceId)}&limit=2000`),
        authFetch(`/api/v1/sensors/accel/events?site_id=${encodeURIComponent(siteId)}&device_id=${encodeURIComponent(deviceId)}&limit=50`),
      ]);
      const gb = await gr.json().catch(() => ({}));
      const eb = await er.json().catch(() => ({}));
      if (!gr.ok) throw new Error(gb.detail || `GNSS HTTP ${gr.status}`);
      if (!er.ok) throw new Error(eb.detail || `Events HTTP ${er.status}`);
      setGnss(gb.rows || []); setEvents(eb.events || []);
      const f = eb.events?.[0]?.source_file || "";
      setEventFile(f);
      if (!f) { setWave([]); setWaveMeta(null); }
    } catch (e) { setError(e.message || "Gagal memuat sensor data."); }
    finally { setBusy(false); }
  }

  async function loadWave(file) {
    if (!file || mode !== "actual") return;
    setBusy(true); setError("");
    try {
      const r = await authFetch(`/api/v1/sensors/accel/waveform?file_name=${encodeURIComponent(file)}&device_id=${encodeURIComponent(deviceId)}&max_points=2500`);
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || `Waveform HTTP ${r.status}`);
      setWave(b.rows || []); setWaveMeta(b);
    } catch (e) { setError(e.message || "Gagal memuat waveform."); }
    finally { setBusy(false); }
  }

  useEffect(() => { if (eventFile && mode === "actual") loadWave(eventFile); }, [eventFile]);

  function setSource(next) {
    setMode(next); setError("");
    if (next === "synthetic") {
      const w = syntheticWaveform();
      setSiteId(DEMO_SITE); setDeviceId(DEMO_DEVICE); setGnss(syntheticGnss());
      setEvents([{
        event_id: "demo-v1",
        device_id: DEMO_DEVICE,
        source_file: "synthetic://accel/blast-demo-v1",
        observed_sample_rate_hz: 100,
        sample_count: 240,
        duration_ms: 2390,
        median_gap_ms: 10,
        max_gap_ms: 10,
        quality_gate_status: "synthetic_demo",
        validation_status: "not_applicable",
        source_received_at: null,
        adxl355_ppa_g: null,
        adxl355_ppv_mm_s: null,
        mpu9250_ppa_g: null,
        mpu9250_ppv_mm_s: null,
      }]);
      setEventFile("synthetic://accel/blast-demo-v1"); setWave(w);
      setWaveMeta({ total_samples: w.length, returned_samples: w.length,
        downsampling: { method: "none", stride: 1 } });
    } else {
      setSiteId(""); setDeviceId(""); setGnss([]); setEvents([]);
      setEventFile(""); setWave([]); setWaveMeta(null);
    }
  }

  const latest = gnss.at(-1);
  const first = gnss[0];
  const event = events.find((e) => e.source_file === eventFile) || events[0];

  const sourceLabel = mode === "synthetic" ? "synthetic demo" : "actual";
  const validationLabel =
    latest?.validation_status ||
    (mode === "synthetic" ? "not_applicable" : "unvalidated");

  const latestTime = latest?.timestamp_utc
    ? new Date(latest.timestamp_utc).toLocaleString()
    : "—";

  const timeRange =
    first && latest
      ? `${new Date(first.timestamp_utc).toLocaleString()} → ${new Date(latest.timestamp_utc).toLocaleString()}`
      : "—";

  const eventReceived = event?.source_received_at
    ? new Date(event.source_received_at).toLocaleString()
    : mode === "synthetic"
      ? "browser-generated"
      : "—";

  return (
    <div className="l2 pgdoc2-page sensor-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Kembali</button>
        <div><h1 style={{ fontSize: 18, fontWeight: 650 }}>Sensor Monitoring</h1>
          <div className="sub">GNSS periodic telemetry + uploaded blast acceleration. No silent interpolation.</div></div>
      </div>

      <div className="sensor-mode">
        <div className="sensor-mode-copy">
          <strong>Data source</strong>
          <span>
            Actual = persisted telemetry · Synthetic Demo = browser-only visualization.
          </span>
        </div>

        <div className="sensor-mode-actions">
          <button
            className={mode === "actual" ? "admin-btn admin-btn-primary" : "admin-btn"}
            onClick={() => setSource("actual")}
          >
            Actual
          </button>

          <button
            className={mode === "synthetic" ? "admin-btn admin-btn-primary" : "admin-btn"}
            onClick={() => setSource("synthetic")}
          >
            Synthetic Demo
          </button>
        </div>

        {mode === "synthetic" && (
          <strong className="sensor-demo-watermark">
            SYNTHETIC DEMO DATA — NOT FIELD MEASUREMENT
          </strong>
        )}
      </div>

      <section className="panel sensor-controls">
        <label><span>Site</span>{mode === "actual"
          ? <select value={siteId} onChange={(e) => { setSiteId(e.target.value); setDeviceId(""); }}><option value="">— pilih site —</option>{sites.map((s) => <option key={s}>{s}</option>)}</select>
          : <input value={DEMO_SITE} readOnly />}</label>
        <label><span>Device</span>{mode === "actual"
          ? <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} disabled={!siteId}><option value="">— pilih device —</option>{siteDevices.map((d) => <option key={d.device_id}>{d.device_id}</option>)}</select>
          : <input value={DEMO_DEVICE} readOnly />}</label>
        <button className="admin-btn admin-btn-primary" disabled={mode !== "actual" || !siteId || !deviceId || busy} onClick={refreshActual}>{busy ? "Loading…" : "Refresh actual data"}</button>
        <div className="sensor-manual-note">Manual refresh only · no high-frequency auto polling.</div>
      </section>

      {error && <div className="admin-error sensor-error">{error}</div>}

      <div className="sensor-stat-grid">
        <div><span>Latitude</span><strong>{fmt(latest?.latitude, 7)}</strong></div>
        <div><span>Longitude</span><strong>{fmt(latest?.longitude, 7)}</strong></div>
        <div><span>Altitude</span><strong>{latest ? `${fmt(latest.altitude_m, 3)} m` : "—"}</strong></div>
        <div><span>GNSS fix</span><strong>{latest?.gnss_fix_type ?? "—"}</strong></div>
        <div><span>h_acc</span><strong>{latest?.h_acc_m == null ? "—" : `${fmt(latest.h_acc_m, 3)} m`}</strong></div>
        <div><span>Source file</span><strong>{latest?.source_file || "unavailable"}</strong></div>
      </div>

      <section className="panel sensor-context">
        <div className="sensor-section-head">
          <div>
            <h2>GNSS telemetry context</h2>
            <span>
              Query scope, provenance, validation and latest persisted position.
            </span>
          </div>

          <span
            className={`sensor-source-badge ${
              mode === "synthetic" ? "is-demo" : ""
            }`}
          >
            {sourceLabel}
          </span>
        </div>

        <div className="sensor-context-grid">
          <div><span>Site</span><strong>{siteId || "—"}</strong></div>
          <div><span>Device</span><strong>{deviceId || "—"}</strong></div>
          <div><span>Validation</span><strong>{validationLabel}</strong></div>
          <div><span>Interpolation</span><strong>none</strong></div>
          <div><span>Rows</span><strong>{gnss.length}</strong></div>
          <div><span>Latest timestamp</span><strong>{latestTime}</strong></div>

          <div className="sensor-context-wide">
            <span>Time range</span>
            <strong>{timeRange}</strong>
          </div>

          <div className="sensor-context-wide">
            <span>Latest provenance</span>
            <strong>
              {latest?.source_file ||
                "unavailable / historical provenance not persisted"}
            </strong>
          </div>
        </div>
      </section>

      <div className="sensor-grid sensor-gnss-grid">
        <section className="panel sensor-card">
          <div className="sensor-chart-head">
            <div>
              <h2>GNSS latitude / longitude</h2>
              <span>
                Latest: {latest
                  ? `${fmt(latest.latitude, 7)}, ${fmt(latest.longitude, 7)}`
                  : "—"}
              </span>
            </div>
          </div>
          {gnss.length ? <>
            <div className="sensor-chart-legend" aria-label="GNSS coordinate legend">
              <span><i style={{ background: pal.lineDefault }} />Latitude</span>
              <span><i className="is-dashed" style={{ borderColor: pal.line.displacement || pal.lineDefault }} />Longitude</span>
            </div>
            <PanelChart height={300} axisFontSize={11}
            left={{ name: "latitude" }} right={{ name: "longitude" }}
            series={[
              { name: "Latitude", data: pts(gnss, "latitude"), color: pal.lineDefault, width: 1.8 },
              { name: "Longitude", data: pts(gnss, "longitude"), color: pal.line.displacement || pal.lineDefault, width: 1.8, axis: 1, dash: "dashed" },
            ]} />
          </> : <div className="sensor-empty">
              <strong>No GNSS rows</strong>
              <span>
                Pilih site/device lalu Refresh actual data.
                Missing/gap tidak diinterpolasi.
              </span>
            </div>}
        </section>
        <section className="panel sensor-card">
          <div className="sensor-chart-head">
            <div>
              <h2>GNSS altitude / h_acc</h2>
              <span>
                Latest: altitude {latest?.altitude_m == null
                  ? "—"
                  : `${fmt(latest.altitude_m, 3)} m`} · h_acc {latest?.h_acc_m == null
                  ? "—"
                  : `${fmt(latest.h_acc_m, 3)} m`}
              </span>
            </div>
          </div>
          {gnss.length ? <>
            <div className="sensor-chart-legend" aria-label="GNSS altitude accuracy legend">
              <span><i style={{ background: pal.line.disp_u || pal.lineDefault }} />Altitude · m</span>
              <span><i className="is-dashed" style={{ borderColor: pal.lineDefault }} />h_acc · m</span>
            </div>
            <PanelChart height={300} axisFontSize={11}
            left={{ name: "m altitude" }} right={{ name: "m h_acc", min: 0 }}
            series={[
              { name: "Altitude", data: pts(gnss, "altitude_m"), color: pal.line.disp_u || pal.lineDefault, width: 1.8 },
              { name: "h_acc", data: pts(gnss, "h_acc_m"), color: pal.lineDefault, width: 1.6, axis: 1, dash: "dashed" },
            ]} />
          </> : <div className="sensor-empty">
              <strong>No GNSS rows</strong>
              <span>
                Pilih site/device lalu Refresh actual data.
                Missing/gap tidak diinterpolasi.
              </span>
            </div>}
        </section>
      </div>

      <section className="panel sensor-event-panel">
        <div className="sensor-event-controls"><div><h2>Blast waveform</h2><span>Manual-upload acceleration event</span></div>
          <label><span>Event / source file</span><select value={eventFile} onChange={(e) => setEventFile(e.target.value)}><option value="">— no event —</option>{events.map((e) => <option key={String(e.event_id)} value={e.source_file}>{e.source_file}</option>)}</select></label></div>
        {event && (
          <>
            <div className="sensor-event-meta-grid">
              <div><span>Event ID</span><strong>{event.event_id ?? "—"}</strong></div>
              <div><span>Device</span><strong>{event.device_id || deviceId || "—"}</strong></div>
              <div><span>Observed rate</span><strong>{event.observed_sample_rate_hz == null ? "—" : `${event.observed_sample_rate_hz} Hz`}</strong></div>
              <div><span>Samples</span><strong>{event.sample_count ?? "—"}</strong></div>
              <div><span>Duration</span><strong>{event.duration_ms == null ? "—" : `${event.duration_ms} ms`}</strong></div>
              <div><span>Median gap</span><strong>{event.median_gap_ms == null ? "—" : `${event.median_gap_ms} ms`}</strong></div>
              <div><span>Max gap</span><strong>{event.max_gap_ms == null ? "—" : `${event.max_gap_ms} ms`}</strong></div>
              <div><span>Quality gate</span><strong>{event.quality_gate_status ?? "—"}</strong></div>
              <div><span>Validation</span><strong>{event.validation_status ?? "—"}</strong></div>
              <div><span>Received at</span><strong>{eventReceived}</strong></div>

              <div className="sensor-event-wide">
                <span>Source file</span>
                <strong>{event.source_file || "—"}</strong>
              </div>
            </div>

            <div className="sensor-metric-grid">
              <div>
                <span>ADXL355 PPA</span>
                <strong>{event.adxl355_ppa_g == null ? "—" : `${fmt(event.adxl355_ppa_g, 4)} g`}</strong>
              </div>
              <div>
                <span>ADXL355 PPV</span>
                <strong>{event.adxl355_ppv_mm_s == null ? "—" : `${fmt(event.adxl355_ppv_mm_s, 3)} mm/s`}</strong>
              </div>
              <div>
                <span>MPU9250 PPA</span>
                <strong>{event.mpu9250_ppa_g == null ? "—" : `${fmt(event.mpu9250_ppa_g, 4)} g`}</strong>
              </div>
              <div>
                <span>MPU9250 PPV</span>
                <strong>{event.mpu9250_ppv_mm_s == null ? "—" : `${fmt(event.mpu9250_ppv_mm_s, 3)} mm/s`}</strong>
              </div>
            </div>
          </>
        )}

        {waveMeta && (
          <div className="sensor-transport-note">
            <strong>Waveform transport</strong>
            <span>
              {waveMeta.returned_samples}/{waveMeta.total_samples} samples ·
              {" "}{waveMeta.downsampling?.method || "—"} ·
              stride {waveMeta.downsampling?.stride ?? "—"} ·
              interpolation none
            </span>
            <small>
              Raw persisted samples remain authoritative for technical metrics.
            </small>
          </div>
        )}
        <div className="sensor-grid sensor-wave-grid">
          <div className="sensor-wave-card">
            <h3>ADXL355 acceleration XYZ</h3>
            <div className="sensor-chart-legend">
              <span><i style={{ background: pal.line.ppa || pal.lineDefault }} />X</span>
              <span><i className="is-dashed" style={{ borderColor: pal.line.tilt_x || pal.lineDefault }} />Y</span>
              <span><i className="is-dotted" style={{ borderColor: pal.line.displacement || pal.lineDefault }} />Z</span>
              <em>m/s²</em>
            </div>
            {wave.length ? <PanelChart height={320} axisFontSize={11} left={{ name: "m/s²" }} series={[
            { name: "ADXL355 X", data: pts(wave, "adxl355_x_mps2"), color: pal.line.ppa || pal.lineDefault, width: 1.5 },
            { name: "ADXL355 Y", data: pts(wave, "adxl355_y_mps2"), color: pal.line.tilt_x || pal.lineDefault, width: 1.3, dash: "dashed" },
            { name: "ADXL355 Z", data: pts(wave, "adxl355_z_mps2"), color: pal.line.displacement || pal.lineDefault, width: 1.3, dash: "dotted" },
          ]} /> : <div className="sensor-empty">
              <strong>No waveform selected</strong>
              <span>
                Pilih source file/event untuk memuat persisted acceleration samples.
              </span>
            </div>}
          </div>

          <div className="sensor-wave-card">
            <h3>MPU9250 acceleration XYZ</h3>
            <div className="sensor-chart-legend">
              <span><i style={{ background: pal.line.ppa_mpu9250 || pal.lineDefault }} />X</span>
              <span><i className="is-dashed" style={{ borderColor: pal.line.tilt_y || pal.lineDefault }} />Y</span>
              <span><i className="is-dotted" style={{ borderColor: pal.line.disp_u || pal.lineDefault }} />Z</span>
              <em>m/s²</em>
            </div>
            {wave.length ? <PanelChart height={320} axisFontSize={11} left={{ name: "m/s²" }} series={[
            { name: "MPU9250 X", data: pts(wave, "mpu9250_x_mps2"), color: pal.line.ppa_mpu9250 || pal.lineDefault, width: 1.5 },
            { name: "MPU9250 Y", data: pts(wave, "mpu9250_y_mps2"), color: pal.line.tilt_y || pal.lineDefault, width: 1.3, dash: "dashed" },
            { name: "MPU9250 Z", data: pts(wave, "mpu9250_z_mps2"), color: pal.line.disp_u || pal.lineDefault, width: 1.3, dash: "dotted" },
          ]} /> : <div className="sensor-empty">
              <strong>No waveform selected</strong>
              <span>
                Pilih source file/event untuk memuat persisted acceleration samples.
              </span>
            </div>}
          </div>
        </div>
      </section>

      <details className="panel sensor-guard"><summary>Data limitations & interpretation</summary><p>
        GNSS direct position adalah positioning telemetry dan tidak otomatis menjadi production-valid displacement.
        Panel accelerometer menampilkan acceleration XYZ; MPU9250 tidak disebut gyroscope/angular-rate karena field tersebut tidak ada pada kontrak CSV.
        LoRa blast acceleration berasal dari file SD yang di-upload manual, bukan continuous live 1000 Hz stream.
        Synthetic mode generated di browser dan tidak dipersist ke DB, PPK, alarm evaluator, baseline, atau ML ground truth.
      </p></details>
    </div>
  );
}
