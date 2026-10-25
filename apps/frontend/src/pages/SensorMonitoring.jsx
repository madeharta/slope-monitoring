import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import PanelChart from "../components/PanelChart.jsx";
import { estimateAccelVelocity } from "./accelVelocity.js";
import { getPalette } from "../theme";
import { useStore } from "../store";
import {
  ITB_REFERENCE_EVENTS,
  ITB_REFERENCE_GNSS,
  ITB_REFERENCE_META,
  ITB_REFERENCE_SITE,
  ITB_REFERENCE_WAVEFORMS,
} from "../data/sensorReferenceData.js";
import "./sensors.css";
import GnssSynchronizationQA from "./GnssSynchronizationQA.jsx";
import SatelliteQualityQA from "./SatelliteQualityQA.jsx";

const SOURCE_ACTUAL = "actual";
const SOURCE_REFERENCE = "reference";
const SOURCE_SYNTHETIC = "synthetic";
const DEMO_SITE = "SYNTHETIC-DEMO";
const DEMO_DEVICE = "ROVER-DEMO-01";

const pts = (rows, key) => rows.map((r) => [r.timestamp_utc, r[key]]);
const fmt = (v, d = 4) => v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);
const fmtMaybe = (v, suffix = "", d = 2) => v == null || Number.isNaN(Number(v)) ? "—" : `${Number(v).toFixed(d)}${suffix}`;
const median = (values) => {
  const xs = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const m = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
};
const clampString = (v) => String(v ?? "").trim();

function syntheticGnss() {
  const end = Date.UTC(2026, 9, 9, 12, 0, 0);
  return Array.from({ length: 288 }, (_, k) => {
    const phase = k / 34;
    return {
      timestamp_utc: new Date(end - (287 - k) * 300000).toISOString(),
      device_id: DEMO_DEVICE,
      site_id: DEMO_SITE,
      latitude: -6.8671 + Math.sin(phase) * 0.000004,
      longitude: 107.57875 + Math.cos(phase * 0.87) * 0.000004,
      altitude_m: 904.4 + Math.sin(phase * 0.41) * 0.08,
      gnss_fix_type: 4,
      h_acc_m: 0.03 + (1 + Math.sin(phase * 1.7)) * 0.01,
      source_file: "synthetic://gnss/demo-24h-v2",
      validation_status: "not_applicable",
      quality_flag: "synthetic_demo",
    };
  });
}

function syntheticWaveform() {
  const start = Date.UTC(2026, 9, 9, 11, 59, 58);
  return Array.from({ length: 600 }, (_, i) => {
    const t = i / 100;
    const burstA = Math.exp(-Math.pow((t - 2.15) / 0.38, 2));
    const burstB = Math.exp(-Math.pow((t - 2.55) / 0.72, 2));
    const a = Math.sin(i * 0.82) * burstA + 0.34 * Math.sin(i * 0.29) * burstB;
    const b = Math.sin(i * 1.07 + 0.7) * burstA + 0.22 * Math.sin(i * 0.36) * burstB;
    return {
      timestamp_utc: new Date(start + i * 10).toISOString(),
      device_id: DEMO_DEVICE,
      sample_index: i,
      adxl355_x_mps2: 0.08 * Math.sin(i * 0.11) + 7.2 * a,
      adxl355_y_mps2: 0.07 * Math.cos(i * 0.13) + 5.8 * b,
      adxl355_z_mps2: 9.81 + 0.06 * Math.sin(i * 0.09) + 4.4 * a,
      mpu9250_x_mps2: 0.10 * Math.sin(i * 0.12) + 6.7 * b,
      mpu9250_y_mps2: 0.08 * Math.cos(i * 0.10) + 5.1 * a,
      mpu9250_z_mps2: 9.81 + 0.07 * Math.sin(i * 0.08) + 4.0 * b,
      source_file: "synthetic://accel/blast-demo-v2",
    };
  });
}

function syntheticEvents() {
  return [{
    event_id: "synthetic-blast-v2",
    device_id: DEMO_DEVICE,
    source_file: "synthetic://accel/blast-demo-v2",
    observed_sample_rate_hz: 100,
    sample_count: 600,
    duration_ms: 5990,
    median_gap_ms: 10,
    max_gap_ms: 10,
    quality_gate_status: "synthetic_demo",
    validation_status: "not_applicable",
    source_received_at: null,
    adxl355_ppa_g: null,
    adxl355_ppv_mm_s: null,
    mpu9250_ppa_g: null,
    mpu9250_ppv_mm_s: null,
  }];
}

function sourceDefaults(source) {
  if (source === SOURCE_REFERENCE) {
    return {
      source,
      siteId: ITB_REFERENCE_SITE,
      deviceId: "ROVER-01",
      range: "all",
      from: "",
      to: "",
      dataType: "all",
      fixType: "all",
      validation: "all",
      quality: "all",
    };
  }
  if (source === SOURCE_SYNTHETIC) {
    return {
      source,
      siteId: DEMO_SITE,
      deviceId: DEMO_DEVICE,
      range: "24h",
      from: "",
      to: "",
      dataType: "all",
      fixType: "all",
      validation: "all",
      quality: "all",
    };
  }
  return {
    source,
    siteId: "",
    deviceId: "",
    range: "24h",
    from: "",
    to: "",
    dataType: "all",
    fixType: "all",
    validation: "all",
    quality: "all",
  };
}

function actualApiWindow(f) {
  if (f.range === "all") return { from: null, to: null };

  if (f.range === "custom") {
    const fromDate = f.from ? new Date(f.from) : null;
    const toDate = f.to ? new Date(f.to) : null;

    return {
      from: fromDate && Number.isFinite(fromDate.getTime()) ? fromDate.toISOString() : null,
      to: toDate && Number.isFinite(toDate.getTime()) ? toDate.toISOString() : null,
    };
  }

  const hours = { "1h": 1, "6h": 6, "24h": 24, "7d": 168 }[f.range];
  if (!hours) return { from: null, to: null };

  const toDate = new Date();
  const fromDate = new Date(toDate.getTime() - hours * 3600000);

  return {
    from: fromDate.toISOString(),
    to: toDate.toISOString(),
  };
}

function rangeBounds(rows, f) {
  if (!rows.length) return [null, null];
  if (f.range === "custom") {
    const from = f.from ? new Date(f.from).getTime() : null;
    const to = f.to ? new Date(f.to).getTime() : null;
    return [Number.isFinite(from) ? from : null, Number.isFinite(to) ? to : null];
  }
  if (f.range === "all") return [null, null];

  const newest = Math.max(...rows.map((r) => new Date(r.timestamp_utc).getTime()).filter(Number.isFinite));
  const hours = { "1h": 1, "6h": 6, "24h": 24, "7d": 168 }[f.range];
  return hours ? [newest - hours * 3600000, newest] : [null, null];
}

function filterGnss(rows, f) {
  const deviceRows = rows.filter((r) => !f.deviceId || r.device_id === f.deviceId);
  const [from, to] = rangeBounds(deviceRows, f);
  return deviceRows.filter((r) => {
    const t = new Date(r.timestamp_utc).getTime();
    if (from != null && t < from) return false;
    if (to != null && t > to) return false;
    if (f.fixType !== "all" && String(r.gnss_fix_type) !== f.fixType) return false;
    if (f.validation !== "all" && String(r.validation_status || "unvalidated") !== f.validation) return false;
    if (
      f.quality !== "all" &&
      r.quality_flag != null &&
      String(r.quality_flag) !== f.quality
    ) return false;
    return true;
  });
}

function filterEvents(rows, f) {
  return rows.filter((e) => {
    if (f.deviceId && e.device_id && e.device_id !== f.deviceId) return false;
    if (f.validation !== "all" && String(e.validation_status || "unvalidated") !== f.validation) return false;
    if (f.quality !== "all" && String(e.quality_gate_status || "unavailable") !== f.quality) return false;
    return true;
  });
}

function gnssStats(rows) {
  if (!rows.length) {
    return {
      latest: null, first: null, medianHAcc: null,
      medianGapMs: null, maxGapMs: null, spanMs: null, fixCounts: {},
    };
  }
  const ordered = [...rows].sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  const diffs = [];
  for (let i = 1; i < ordered.length; i += 1) {
    const d = new Date(ordered[i].timestamp_utc) - new Date(ordered[i - 1].timestamp_utc);
    if (Number.isFinite(d) && d >= 0) diffs.push(d);
  }
  const fixCounts = {};
  for (const r of ordered) {
    const k = r.gnss_fix_type == null ? "missing" : String(r.gnss_fix_type);
    fixCounts[k] = (fixCounts[k] || 0) + 1;
  }
  return {
    first: ordered[0],
    latest: ordered.at(-1),
    medianHAcc: median(ordered.map((r) => r.h_acc_m == null || r.h_acc_m === "" ? NaN : Number(r.h_acc_m))),
    medianGapMs: median(diffs),
    maxGapMs: diffs.length ? Math.max(...diffs) : null,
    spanMs: new Date(ordered.at(-1).timestamp_utc) - new Date(ordered[0].timestamp_utc),
    fixCounts,
  };
}

function waveformStats(rows, prefix) {
  if (!rows.length) return { peak: null, rms: null };
  const mags = rows.map((r) => {
    const x = Number(r[`${prefix}_x_mps2`]);
    const y = Number(r[`${prefix}_y_mps2`]);
    const z = Number(r[`${prefix}_z_mps2`]);
    return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)
      ? Math.sqrt(x * x + y * y + z * z)
      : null;
  }).filter(Number.isFinite);
  if (!mags.length) return { peak: null, rms: null };
  return {
    peak: Math.max(...mags),
    rms: Math.sqrt(mags.reduce((a, v) => a + v * v, 0) / mags.length),
  };
}

function formatDuration(ms) {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 3600000) return `${(ms / 60000).toFixed(1)} min`;
  return `${(ms / 3600000).toFixed(1)} h`;
}

export default function SensorMonitoring() {
  const navigate = useNavigate();
  const { authFetch } = useAuth();
  const variant = useStore((s) => s.variant);
  const pal = getPalette(variant);

  const [devices, setDevices] = useState([]);
  const [draft, setDraft] = useState(() => sourceDefaults(SOURCE_ACTUAL));
  const [applied, setApplied] = useState(() => sourceDefaults(SOURCE_ACTUAL));
  const [rawGnss, setRawGnss] = useState([]);
  /* BATCH12_RAWX_OBSERVATIONS_V1 */
  const [rawxSummary, setRawxSummary] = useState(null);
  const [gnssWindow, setGnssWindow] = useState(null);
  const [rawEvents, setRawEvents] = useState([]);
  const [eventFile, setEventFile] = useState("");
  const [wave, setWave] = useState([]);
  const [waveMeta, setWaveMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [waveBusy, setWaveBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastAppliedAt, setLastAppliedAt] = useState(null);

  useEffect(() => {
    authFetch("/api/v1/devices")
      .then((r) => r.json())
      .then((b) => setDevices(b.devices || []))
      .catch(() => setDevices([]));
  }, [authFetch]);

  const actualSites = useMemo(
    () => [...new Set(devices.map((d) => d.site_id).filter(Boolean))].sort(),
    [devices],
  );

  const actualDevices = useMemo(
    () => devices.filter((d) => d.site_id === draft.siteId),
    [devices, draft.siteId],
  );

  const referenceDevices = useMemo(() => {
    const ids = new Set([
      ...ITB_REFERENCE_GNSS.map((r) => r.device_id),
      ...ITB_REFERENCE_EVENTS.map((e) => e.device_id),
    ].filter(Boolean));
    return [...ids].sort();
  }, []);

  const gnss = useMemo(
    () => filterGnss(rawGnss, applied),
    [rawGnss, applied],
  );

  const events = useMemo(
    () => filterEvents(rawEvents, applied),
    [rawEvents, applied],
  );

  const stats = useMemo(() => gnssStats(gnss), [gnss]);

  const continuity = useMemo(() => {
    if (applied.source === SOURCE_ACTUAL && gnssWindow) {
      const first = gnssWindow.raw_first_timestamp
        ? new Date(gnssWindow.raw_first_timestamp)
        : null;
      const last = gnssWindow.raw_last_timestamp
        ? new Date(gnssWindow.raw_last_timestamp)
        : null;

      return {
        medianHAcc: gnssWindow.median_h_acc_m,
        medianGapMs: gnssWindow.median_gap_ms,
        maxGapMs: gnssWindow.max_gap_ms,
        spanMs: first && last ? last - first : null,
        firstTimestamp: gnssWindow.raw_first_timestamp,
        lastTimestamp: gnssWindow.raw_last_timestamp,
        totalRows: Number(gnssWindow.total_rows || 0),
        returnedRows: Number(gnssWindow.returned_rows || 0),
      };
    }

    return {
      medianHAcc: stats.medianHAcc,
      medianGapMs: stats.medianGapMs,
      maxGapMs: stats.maxGapMs,
      spanMs: stats.spanMs,
      firstTimestamp: stats.first?.timestamp_utc || null,
      lastTimestamp: stats.latest?.timestamp_utc || null,
      totalRows: gnss.length,
      returnedRows: gnss.length,
    };
  }, [applied.source, gnssWindow, stats, gnss.length]);

  const adxlStats = useMemo(() => waveformStats(wave, "adxl355"), [wave]);
  const mpuStats = useMemo(() => waveformStats(wave, "mpu9250"), [wave]);
  const adxlVelocity = useMemo(() => estimateAccelVelocity(wave, "adxl355", waveMeta || {}), [wave, waveMeta]);
  const mpuVelocity = useMemo(() => estimateAccelVelocity(wave, "mpu9250", waveMeta || {}), [wave, waveMeta]);

  const latest = stats.latest;
  const event = events.find((e) => e.source_file === eventFile) || null;

  const fixOptions = useMemo(
    () => [...new Set(rawGnss.map((r) => r.gnss_fix_type).filter((v) => v != null).map(String))].sort(),
    [rawGnss],
  );
  const validationOptions = useMemo(
    () => [...new Set([
      ...rawGnss.map((r) => r.validation_status),
      ...rawEvents.map((e) => e.validation_status),
    ].filter(Boolean))].sort(),
    [rawGnss, rawEvents],
  );
  const qualityOptions = useMemo(
    () => [...new Set([
      ...rawGnss.map((r) => r.quality_flag),
      ...rawEvents.map((e) => e.quality_gate_status),
    ].filter(Boolean))].sort(),
    [rawGnss, rawEvents],
  );

  const dirty = JSON.stringify(draft) !== JSON.stringify(applied);

  const setDraftField = (key, value) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const chooseSource = (source) => {
    setDraft(sourceDefaults(source));
    setError("");
  };

  async function applyFilters() {
    const next = { ...draft };
    if (next.source === SOURCE_ACTUAL && (!next.siteId || !next.deviceId)) {
      setError("Select a site and device before applying filters.");
      return;
    }

    if (next.range === "custom") {
      const apiWindow = actualApiWindow(next);
      if (!apiWindow.from || !apiWindow.to) {
        setError("A custom time range requires valid From and To timestamps.");
        return;
      }
      if (new Date(apiWindow.from) >= new Date(apiWindow.to)) {
        setError("Custom time range: From must precede To.");
        return;
      }
    }

    setBusy(true);
    setError("");
    setWave([]);
    setWaveMeta(null);
    setGnssWindow(null);
    setRawxSummary(null);
    setEventFile("");

    try {
      let nextGnss = [];
      let nextEvents = [];

      if (next.source === SOURCE_ACTUAL) {
        const wantsGnss = next.dataType !== "accel";
        const wantsAccel = next.dataType !== "gnss";
        const requests = [];

        if (wantsGnss) {
          // RAWX presence is independent of PPK position availability.
          const rawxParams = new URLSearchParams({ site_id: next.siteId });
          const rawxWindow = actualApiWindow(next);
          if (rawxWindow.from) rawxParams.set("from", rawxWindow.from);
          if (rawxWindow.to) rawxParams.set("to", rawxWindow.to);
          requests.push(authFetch(`/api/v1/sensors/gnss/rawx/availability?${rawxParams}`)
            .then(async (r) => {
              const b = await r.json().catch(() => ({}));
              if (!r.ok) throw new Error(b.detail || `RAWX HTTP ${r.status}`);
              setRawxSummary(b);
            }));
          const params = new URLSearchParams({
            site_id: next.siteId,
            device_id: next.deviceId,
            max_points: "5000",
          });

          const apiWindow = actualApiWindow(next);
          if (apiWindow.from) params.set("from", apiWindow.from);
          if (apiWindow.to) params.set("to", apiWindow.to);

          if (next.fixType !== "all") {
            params.set("gnss_fix_type", next.fixType);
          }

          if (next.validation !== "all") {
            params.set("validation_status", next.validation);
          }

          requests.push(
            authFetch(`/api/v1/sensors/gnss?${params.toString()}`)
              .then(async (r) => {
                const b = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(b.detail || `GNSS HTTP ${r.status}`);

                nextGnss = b.rows || [];
                setGnssWindow(b.window_summary || null);
              }),
          );
        }

        if (wantsAccel) {
          requests.push(
            authFetch(
              `/api/v1/sensors/accel/events?site_id=${encodeURIComponent(next.siteId)}&device_id=${encodeURIComponent(next.deviceId)}&limit=50`,
            ).then(async (r) => {
              const b = await r.json().catch(() => ({}));
              if (!r.ok) throw new Error(b.detail || `Events HTTP ${r.status}`);
              nextEvents = b.events || [];
            }),
          );
        }

        await Promise.all(requests);
      } else if (next.source === SOURCE_REFERENCE) {
        nextGnss = next.dataType === "accel" ? [] : ITB_REFERENCE_GNSS;
        nextEvents = next.dataType === "gnss" ? [] : ITB_REFERENCE_EVENTS;
      } else {
        nextGnss = next.dataType === "accel" ? [] : syntheticGnss();
        nextEvents = next.dataType === "gnss" ? [] : syntheticEvents();
      }

      setRawGnss(nextGnss);
      setRawEvents(nextEvents);
      setApplied(next);
      setLastAppliedAt(new Date());
    } catch (e) {
      setError(e.message || "Failed to load sensor data.");
    } finally {
      setBusy(false);
    }
  }

  function resetFilters() {
    const next = sourceDefaults(draft.source);
    setDraft(next);
    setError("");
  }

  async function loadWaveform() {
    if (!eventFile) return;
    setWaveBusy(true);
    setError("");
    try {
      if (applied.source === SOURCE_ACTUAL) {
        const r = await authFetch(
          `/api/v1/sensors/accel/waveform?file_name=${encodeURIComponent(eventFile)}&device_id=${encodeURIComponent(applied.deviceId)}&max_points=2500`,
        );
        const b = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(b.detail || `Waveform HTTP ${r.status}`);
        setWave(b.rows || []);
        setWaveMeta(b);
      } else if (applied.source === SOURCE_REFERENCE) {
        const rows = ITB_REFERENCE_WAVEFORMS[eventFile] || [];
        setWave(rows);
        setWaveMeta({
          total_samples: rows.length,
          returned_samples: rows.length,
          downsampling: { method: "none", stride: 1 },
        });
      } else {
        const rows = syntheticWaveform();
        setWave(rows);
        setWaveMeta({
          total_samples: rows.length,
          returned_samples: rows.length,
          downsampling: { method: "none", stride: 1 },
        });
      }
    } catch (e) {
      setError(e.message || "Failed to load waveform.");
    } finally {
      setWaveBusy(false);
    }
  }

  const sourceLabel = {
    [SOURCE_ACTUAL]: "Actual persisted",
    [SOURCE_REFERENCE]: "ITB reference sample",
    [SOURCE_SYNTHETIC]: "Synthetic demo",
  }[applied.source];

  const sourceNote = {
    [SOURCE_ACTUAL]: "Persisted telemetry from the current API/database window.",
    [SOURCE_REFERENCE]: "Real sample supplied by ITB; not live operational telemetry.",
    [SOURCE_SYNTHETIC]: "Deterministic browser-only data for UI/QA.",
  }[applied.source];

  const latestTime = latest?.timestamp_utc
    ? new Date(latest.timestamp_utc).toLocaleString()
    : "—";

  const timeRange = continuity.firstTimestamp && continuity.lastTimestamp
    ? `${new Date(continuity.firstTimestamp).toLocaleString()} → ${new Date(continuity.lastTimestamp).toLocaleString()}`
    : "—";

  const eventReceived = event?.source_received_at
    ? new Date(event.source_received_at).toLocaleString()
    : applied.source === SOURCE_REFERENCE
      ? "reference sample"
      : applied.source === SOURCE_SYNTHETIC
        ? "browser-generated"
        : "—";

  const sourceFile = latest?.source_file || event?.source_file || "unavailable";

  return (
    <div className="l2 pgdoc2-page sensor-page sensor-v2">
      <div className="l2head sensor-v2-head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button>
        <div>
          <h1>Sensor Monitoring</h1>
          <div className="sub">
            Persisted GNSS analytics + event-based blast acceleration. Missing data remains missing.
          </div>
        </div>
        <div className="sensor-v2-head-meta">
          <span>{sourceLabel}</span>
          <strong>{applied.siteId || "No site"} · {applied.deviceId || "No device"}</strong>
        </div>
      </div>

      <section className="panel sensor-v2-source" style={{ padding: "12px 16px", minHeight: 0, marginBottom: 12 }}>
        <div>
          <span className="sensor-v2-eyebrow">DATA SOURCE</span>
          <h2>Actual persisted measurements</h2>
          <small>Verified GNSS RAWX / persisted acceleration · experimental, not operational displacement</small>
        </div>
      </section>

      <section className="panel sensor-v2-filter">
        <div className="sensor-v2-filter-head">
          <div>
            <span className="sensor-v2-eyebrow">Filters</span>
            <h2>Query scope</h2>
          </div>
          <div className={"sensor-v2-dirty" + (dirty ? " is-dirty" : "")}>
            {dirty ? "Pending changes" : "Applied"}
          </div>
        </div>

        <div className="sensor-v2-filter-grid">
          <label>
            <span>Site</span>
            {draft.source === SOURCE_ACTUAL ? (
              <select
                value={draft.siteId}
                onChange={(e) => setDraft((prev) => ({
                  ...prev,
                  siteId: e.target.value,
                  deviceId: "",
                }))}
              >
                <option value="">— select site —</option>
                {actualSites.map((s) => <option key={s}>{s}</option>)}
              </select>
            ) : (
              <input value={draft.siteId} readOnly />
            )}
          </label>

          <label>
            <span>Device</span>
            {draft.source === SOURCE_ACTUAL ? (
              <select
                value={draft.deviceId}
                onChange={(e) => setDraftField("deviceId", e.target.value)}
                disabled={!draft.siteId}
              >
                <option value="">— pilih device —</option>
                {actualDevices.map((d) => (
                  <option key={d.device_id} value={d.device_id}>{d.device_id}</option>
                ))}
              </select>
            ) : draft.source === SOURCE_REFERENCE ? (
              <select value={draft.deviceId} onChange={(e) => setDraftField("deviceId", e.target.value)}>
                {referenceDevices.map((id) => <option key={id}>{id}</option>)}
              </select>
            ) : (
              <input value={DEMO_DEVICE} readOnly />
            )}
          </label>

          <label>
            <span>Time range</span>
            <select value={draft.range} onChange={(e) => setDraftField("range", e.target.value)}>
              <option value="1h">Last 1 hour</option>
              <option value="6h">Last 6 hours</option>
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="all">Fetched window / all reference rows</option>
              <option value="custom">Custom</option>
            </select>
          </label>

          <label>
            <span>Data type</span>
            <select value={draft.dataType} onChange={(e) => setDraftField("dataType", e.target.value)}>
              <option value="all">GNSS + Acceleration</option>
              <option value="gnss">GNSS only</option>
              <option value="accel">Acceleration only</option>
            </select>
          </label>

          {/* B12_FINAL_FILTER_CLEANUP */}
          {(fixOptions.length > 0 || draft.fixType !== "all") && (
          <label>
            <span>GNSS fix</span>
            <select value={draft.fixType} onChange={(e) => setDraftField("fixType", e.target.value)}>
              <option value="all">All fix types</option>
              {fixOptions.map((v) => <option key={v} value={v}>Fix {v}</option>)}
            </select>
          </label>
          )}

          {/* B12_FINAL_FILTER_CLEANUP */}
          {(validationOptions.length > 0 || draft.validation !== "all") && (
          <label>
            <span>Validation</span>
            <select value={draft.validation} onChange={(e) => setDraftField("validation", e.target.value)}>
              <option value="all">All validation states</option>
              {validationOptions.map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
          )}

          {/* B12_FINAL_FILTER_CLEANUP */}
          {(qualityOptions.length > 0 || draft.quality !== "all") && (
          <label>
            <span>Quality</span>
            <select value={draft.quality} onChange={(e) => setDraftField("quality", e.target.value)}>
              <option value="all">All quality states</option>
              {qualityOptions.map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
          )}

          {draft.range === "custom" && (
            <>
              <label>
                <span>From</span>
                <input type="datetime-local" value={draft.from} onChange={(e) => setDraftField("from", e.target.value)} />
              </label>
              <label>
                <span>To</span>
                <input type="datetime-local" value={draft.to} onChange={(e) => setDraftField("to", e.target.value)} />
              </label>
            </>
          )}
        </div>

        <div className="sensor-v2-filter-actions">
          <button
            className="admin-btn admin-btn-primary"
            disabled={busy}
            onClick={applyFilters}
          >
            {busy ? "Applying…" : "Apply filters"}
          </button>
          <button className="admin-btn" disabled={busy} onClick={resetFilters}>Reset</button>
          <span>Filters apply on click · Times follow the selected window</span>
        </div>
      </section>

      {error && <div className="admin-error sensor-error">{error}</div>}

      {gnss.length > 0 && <div className="sensor-v2-kpis">
        <div>
          <span>GNSS rows</span>
          <strong>{continuity.totalRows.toLocaleString()}</strong>
          <small>{applied.dataType === "accel" ? "GNSS hidden by filter" : `${continuity.returnedRows.toLocaleString()} display rows`}</small>
        </div>
        <div>
          <span>Time span</span>
          <strong>{formatDuration(continuity.spanMs)}</strong>
          <small>{timeRange}</small>
        </div>
        <div>
          <span>Latest fix</span>
          <strong>{latest?.gnss_fix_type ?? "—"}</strong>
          <small>{latestTime}</small>
        </div>
        <div>
          <span>Median h_acc</span>
          <strong>{fmtMaybe(continuity.medianHAcc, " m", 3)}</strong>
          <small>receiver-reported horizontal accuracy</small>
        </div>
        <div>
          <span>Median interval</span>
          <strong>{fmtMaybe(continuity.medianGapMs, " ms", 0)}</strong>
          <small>based on persisted row timestamps</small>
        </div>
        <div>
          <span>Max gap</span>
          <strong>{fmtMaybe(continuity.maxGapMs, " ms", 0)}</strong>
          <small>no interpolation applied</small>
        </div>
      </div>}

      {applied.source === SOURCE_ACTUAL && gnss.length > 0 && gnssWindow && (
        <section className="panel sensor-v2-gnss-transport">
          <div className="sensor-v2-section-head">
            <div>
              <span className="sensor-v2-eyebrow">Historical transport</span>
              <h2>GNSS window representation</h2>
            </div>
          </div>

          <div className="sensor-v2-transport-grid">
            <div>
              <span>Raw window rows</span>
              <strong>{gnssWindow.total_rows?.toLocaleString?.() ?? "—"}</strong>
            </div>
            <div>
              <span>Display rows</span>
              <strong>{gnssWindow.returned_rows?.toLocaleString?.() ?? "—"}</strong>
            </div>
            <div>
              <span>Method</span>
              <strong>{gnssWindow.downsampling?.method || "—"}</strong>
            </div>
            <div>
              <span>Stride</span>
              <strong>{gnssWindow.downsampling?.stride ?? "—"}</strong>
            </div>
          </div>

          <p>
            Display sampling spans the requested window. Median interval and max gap are derived from raw persisted timestamps,
            not from downsampled display points. Interpolation remains disabled.
          </p>
        </section>
      )}

      {applied.source === SOURCE_ACTUAL && applied.dataType !== "accel" && Array.isArray(rawxSummary?.devices) && rawxSummary.devices.length > 0 && (() => {
        // The availability v3 API returns points (not files/buckets). A bucket only
        // represents actual observation coverage when its count is positive.
        const rows = Array.isArray(rawxSummary.points) ? rawxSummary.points : [];
        const countOf = (p) => {
          const value = p.epochs ?? p.epoch_count ?? p.observation_count ?? p.observations ?? p.count ?? p.sample_count;
          if (value == null || value === "") return null;
          const n = Number(value);
          return Number.isFinite(n) ? n : null;
        };
        const valid = rows.filter((p) => p.device_id && Number.isFinite(Date.parse(p.bucket_utc)) && countOf(p) !== null);
        const covered = valid.filter((p) => countOf(p) > 0);
        const bucketMs = Math.max(1000, Number(rawxSummary.bucket_seconds || 3600) * 1000);
        const from = Date.parse(rawxSummary.requested_window?.from);
        const to = Date.parse(rawxSummary.requested_window?.to);
        const observedStart = covered.length ? Math.min(...covered.map((p) => Date.parse(p.bucket_utc))) : NaN;
        const observedEnd = covered.length ? Math.max(...covered.map((p) => Date.parse(p.bucket_utc) + bucketMs)) : NaN;
        const start = Number.isFinite(from) ? from : observedStart;
        const end = Number.isFinite(to) && to > start ? to : observedEnd;
        const canDraw = covered.length > 0 && Number.isFinite(start) && Number.isFinite(end) && end > start;
        const span = canDraw ? end - start : 1;
        const ids = [...new Set(rawxSummary.devices.map((d) => d.device_id))].sort();
        const selectedRawxDevice = rawxSummary.devices.find((d) => d.device_id === applied.deviceId && Number(d.epochs) > 0);
        const formatDate = (ms) => new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
        return (
          <section className="panel sensor-card sensor-rawx-unified" aria-label="GNSS observation quality and timeline">
            {selectedRawxDevice && <div className="sensor-v2-section-head"><div>
              <span className="sensor-v2-eyebrow">Actual RAWX · verified UTC</span>
              <h2>GNSS observation quality</h2>
            </div></div>}
            {selectedRawxDevice && rawxSummary.devices.filter((d) => d.device_id === applied.deviceId).map((d) => (
              <div key={d.device_id}>
                <div className="sensor-rawx-selected-device">{d.device_id}</div>
                <div className="sensor-rawx-kpi-grid">
                  {[
                    ["Observed epochs", Number(d.epochs).toLocaleString()],
                    ["Median interval", d.median_interval_s == null ? "—" : `${Number(d.median_interval_s).toFixed(1)} s`],
                    ["Maximum gap", d.max_gap_s == null ? "—" : `${Number(d.max_gap_s).toFixed(1)} s`],
                  ].map(([label, value]) => (
                    <div key={label} className="sensor-rawx-kpi"><small>{label}</small><strong>{value}</strong></div>
                  ))}
                </div>
              </div>
            ))}
            {selectedRawxDevice && <div className="sensor-rawx-unified-divider" />}
            {!selectedRawxDevice && (
              <p className="sensor-v2-note" role="status">GNSS RAWX is unavailable for the selected device and time range. Timeline berikut membandingkan perangkat lain di site yang sama; coba pilih rentang waktu lebih panjang.</p>
            )}
            <div className="sensor-v2-section-head"><div>
              <span className="sensor-v2-eyebrow">Availability · site-wide comparison</span>
              <h2>GNSS observation timeline</h2>
            </div><small>{Math.round(bucketMs / 60000)}-minute buckets</small></div>
            {canDraw ? <>
              <div className="sensor-rawx-timeline-axes"><span>{formatDate(start)}</span><span>{formatDate(end)}</span></div>
              {ids.map((id) => {
                const own = covered.filter((p) => p.device_id === id);
                return <div className="sensor-rawx-timeline-lane" key={id}>
                  <strong title={id}>{id}</strong>
                  <div className="sensor-rawx-timeline-track" aria-label={`${id} actual RAWX availability`}>
                    {own.map((p, idx) => {
                      const t = Date.parse(p.bucket_utc);
                      const clippedStart = Math.max(start, t);
                      const clippedEnd = Math.min(end, t + bucketMs);
                      if (clippedEnd <= clippedStart) return null;
                      const left = 100 * (clippedStart - start) / span;
                      const width = 100 * (clippedEnd - clippedStart) / span;
                      return <span key={`${id}-${p.bucket_utc}-${idx}`} className="sensor-rawx-timeline-segment"
                        style={{ left: `${left}%`, width: `${width}%` }}
                        title={`${id} · ${p.bucket_utc} · ${countOf(p)} epochs · verified RAWX UTC`} />;
                    })}
                  </div>
                  <small>{own.length} active buckets</small>
                </div>;
              })}
            </> : <p className="sensor-v2-note">No positive-count observation buckets available for this window; the timeline is not inferred.</p>}
            {rows.length > 0 && valid.length === 0 && <p className="sensor-v2-note">API point records lack per-bucket counts. Timeline suppressed to avoid falsely showing continuous observations.</p>}
            <small className="sensor-v2-note">Gaps remain empty; segments are positioned by UTC timestamp and true bucket duration. This is availability, not displacement or safety status.</small>
          </section>
        );
      })()}

      {gnss.length > 0 && <section className="panel sensor-v2-quality">
        <div className="sensor-v2-section-head">
          <div>
            <span className="sensor-v2-eyebrow">GNSS quality</span>
            <h2>Continuity & fix distribution</h2>
          </div>
          <span className="sensor-source-badge">{sourceLabel}</span>
        </div>

        <div className="sensor-v2-quality-grid">
          <div>
            <span>Fix distribution</span>
            <div className="sensor-v2-fix-chips">
              {Object.entries(stats.fixCounts).length ? Object.entries(stats.fixCounts).map(([k, v]) => (
                <span key={k}>Fix {k}: <strong>{v}</strong></span>
              )) : <span>No GNSS rows</span>}
            </div>
          </div>
          <div>
            <span>Latest provenance</span>
            <strong>{sourceFile}</strong>
          </div>
          <div>
            <span>Applied at</span>
            <strong>{lastAppliedAt ? lastAppliedAt.toLocaleString() : "—"}</strong>
          </div>
        </div>
      </section>}

      {applied.source === SOURCE_ACTUAL && applied.dataType !== "accel" && rawxSummary?.requested_window && (
        <GnssSynchronizationQA siteId={applied.siteId} window={rawxSummary.requested_window} deviceId={applied.deviceId} />
      )}
      {applied.source === SOURCE_ACTUAL && applied.dataType !== "accel" && rawxSummary?.requested_window && (
        <SatelliteQualityQA siteId={applied.siteId} deviceId={applied.deviceId} window={rawxSummary.requested_window} />
      )}
      {applied.dataType !== "accel" && gnss.length > 0 && (
        <div className="sensor-grid sensor-gnss-grid">
          <section className="panel sensor-card">
            <div className="sensor-chart-head">
              <div>
                <h2>GNSS latitude / longitude</h2>
                <span>
                  Latest: {latest ? `${fmt(latest.latitude, 7)}, ${fmt(latest.longitude, 7)}` : "—"}
                </span>
              </div>
            </div>

            {gnss.length ? (
              <>
                <div className="sensor-chart-legend" aria-label="GNSS coordinate legend">
                  <span><i style={{ background: pal.lineDefault }} />Latitude</span>
                  <span><i className="is-dashed" style={{ borderColor: pal.line.displacement || pal.lineDefault }} />Longitude</span>
                </div>
                <PanelChart
                  height={320}
                  axisFontSize={11}
                  left={{ name: "latitude" }}
                  right={{ name: "longitude" }}
                  series={[
                    { name: "Latitude", data: pts(gnss, "latitude"), color: pal.lineDefault, width: 1.8 },
                    { name: "Longitude", data: pts(gnss, "longitude"), color: pal.line.displacement || pal.lineDefault, width: 1.8, axis: 1, dash: "dashed" },
                  ]}
                />
              </>
            ) : (
              <div className="sensor-empty">
                <strong>No GNSS rows in the applied filter.</strong>
                <span>Empty remains empty; no synthetic fallback and no interpolation.</span>
              </div>
            )}
          </section>

          <section className="panel sensor-card">
            <div className="sensor-chart-head">
              <div>
                <h2>GNSS altitude / h_acc</h2>
                <span>
                  Latest: altitude {latest?.altitude_m == null ? "—" : `${fmt(latest.altitude_m, 3)} m`} ·
                  {" "}h_acc {latest?.h_acc_m == null ? "—" : `${fmt(latest.h_acc_m, 3)} m`}
                </span>
              </div>
            </div>

            {gnss.length ? (
              <>
                <div className="sensor-chart-legend" aria-label="GNSS altitude accuracy legend">
                  <span><i style={{ background: pal.line.disp_u || pal.lineDefault }} />Altitude · m</span>
                  <span><i className="is-dashed" style={{ borderColor: pal.lineDefault }} />h_acc · m</span>
                </div>
                <PanelChart
                  height={320}
                  axisFontSize={11}
                  left={{ name: "m altitude" }}
                  right={{ name: "m h_acc", min: 0 }}
                  series={[
                    { name: "Altitude", data: pts(gnss, "altitude_m"), color: pal.line.disp_u || pal.lineDefault, width: 1.8 },
                    { name: "h_acc", data: pts(gnss, "h_acc_m"), color: pal.lineDefault, width: 1.6, axis: 1, dash: "dashed" },
                  ]}
                />
              </>
            ) : (
              <div className="sensor-empty">
                <strong>No GNSS rows in the applied filter.</strong>
                <span>Check source, device, time range and fix filters.</span>
              </div>
            )}
          </section>
        </div>
      )}

      {applied.dataType !== "gnss" && (events.length > 0 || wave.length > 0) && (
        <section className="panel sensor-event-panel sensor-v2-event">
          <div className="sensor-event-controls">
            <div>
              <span className="sensor-v2-eyebrow">Event explorer</span>
              <h2>Blast / acceleration waveform</h2>
              <span>Event-based data. Accelerometer is not presented as a continuous live stream.</span>
            </div>

            <label>
              <span>Event / source file</span>
              <select value={eventFile} onChange={(e) => setEventFile(e.target.value)}>
                <option value="">— select event —</option>
                {events.map((e) => (
                  <option key={String(e.event_id)} value={e.source_file} disabled={applied.source === SOURCE_ACTUAL && !e.raw_available}>
                    {e.source_file}{applied.source === SOURCE_ACTUAL ? (e.raw_available ? ` · RAW ${e.actual_raw_samples} samples` : " · RAW unavailable") : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="sensor-v2-wave-actions">
            <button
              className="admin-btn admin-btn-primary"
              onClick={loadWaveform}
              disabled={!eventFile || waveBusy || (applied.source === SOURCE_ACTUAL && !event?.raw_available)}
            >
              {waveBusy ? "Loading waveform…" : "Load waveform"}
            </button>
            <span>Changing Event does not trigger a request. Load Waveform is explicit.</span>
          </div>

          {event && (
            <>
              <div className="sensor-event-meta-grid">
                <div><span>Event ID</span><strong>{event.event_id ?? "—"}</strong></div>
                <div><span>Device</span><strong>{event.device_id || applied.deviceId || "—"}</strong></div>
                <div><span>Observed rate</span><strong>{event.observed_sample_rate_hz == null ? "—" : `${event.observed_sample_rate_hz} Hz`}</strong></div>
                <div><span>Declared samples</span><strong>{event.sample_count ?? "—"}</strong></div>
                {applied.source === SOURCE_ACTUAL && <div><span>Persisted RAW</span><strong>{event.actual_raw_samples ?? 0} · {event.raw_available ? "available" : "unavailable"}</strong></div>}
                <div><span>Duration</span><strong>{event.duration_ms == null ? "—" : `${event.duration_ms} ms`}</strong></div>
                <div><span>Median gap</span><strong>{event.median_gap_ms == null ? "—" : `${event.median_gap_ms} ms`}</strong></div>
                <div><span>Max gap</span><strong>{event.max_gap_ms == null ? "—" : `${event.max_gap_ms} ms`}</strong></div>
                <div><span>Quality gate</span><strong>{event.quality_gate_status ?? "—"}</strong></div>
                <div><span>Validation</span><strong>{event.validation_status ?? "—"}</strong></div>
                <div><span>Received at</span><strong>{eventReceived}</strong></div>
                <div className="sensor-event-wide"><span>Source file</span><strong>{event.source_file || "—"}</strong></div>
              </div>

              <div className="sensor-v2-wave-kpis">
                <div>
                  <span>ADXL355 server PPA</span>
                  <strong>{event.adxl355_ppa_g == null ? "—" : `${fmt(event.adxl355_ppa_g, 4)} g`}</strong>
                  <small>server-derived only; no synthetic fabrication</small>
                </div>
                <div>
                  <span>ADXL355 raw peak |a|</span>
                  <strong>{fmtMaybe(adxlStats.peak, " m/s²", 3)}</strong>
                  <small>derived from loaded waveform, includes gravity</small>
                </div>
                <div>
                  <span>ADXL355 RMS |a|</span>
                  <strong>{fmtMaybe(adxlStats.rms, " m/s²", 3)}</strong>
                  <small>raw vector magnitude RMS</small>
                </div>
                <div>
                  <span>MPU9250 server PPA</span>
                  <strong>{event.mpu9250_ppa_g == null ? "—" : `${fmt(event.mpu9250_ppa_g, 4)} g`}</strong>
                  <small>acceleration only</small>
                </div>
                <div>
                  <span>MPU9250 raw peak |a|</span>
                  <strong>{fmtMaybe(mpuStats.peak, " m/s²", 3)}</strong>
                  <small>derived from loaded waveform, includes gravity</small>
                </div>
                <div>
                  <span>MPU9250 RMS |a|</span>
                  <strong>{fmtMaybe(mpuStats.rms, " m/s²", 3)}</strong>
                  <small>raw vector magnitude RMS</small>
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
                stride {waveMeta.downsampling?.stride ?? "—"} · interpolation none
              </span>
              <small>Raw persisted/reference samples remain authoritative for technical metrics.</small>
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
              {wave.length ? (
                <PanelChart
                  height={330}
                  axisFontSize={11}
                  left={{ name: "m/s²" }}
                  series={[
                    { name: "ADXL355 X", data: pts(wave, "adxl355_x_mps2"), color: pal.line.ppa || pal.lineDefault, width: 1.5 },
                    { name: "ADXL355 Y", data: pts(wave, "adxl355_y_mps2"), color: pal.line.tilt_x || pal.lineDefault, width: 1.3, dash: "dashed" },
                    { name: "ADXL355 Z", data: pts(wave, "adxl355_z_mps2"), color: pal.line.displacement || pal.lineDefault, width: 1.3, dash: "dotted" },
                  ]}
                />
              ) : (
                <div className="sensor-empty">
                  <strong>No waveform loaded.</strong>
                  <span>Select an event and click Load waveform.</span>
                </div>
              )}
            </div>

            <div className="sensor-wave-card">
              <h3>MPU9250 acceleration XYZ</h3>
              <div className="sensor-chart-legend">
                <span><i style={{ background: pal.line.ppa_mpu9250 || pal.lineDefault }} />X</span>
                <span><i className="is-dashed" style={{ borderColor: pal.line.tilt_y || pal.lineDefault }} />Y</span>
                <span><i className="is-dotted" style={{ borderColor: pal.line.disp_u || pal.lineDefault }} />Z</span>
                <em>m/s²</em>
              </div>
              {wave.length ? (
                <PanelChart
                  height={330}
                  axisFontSize={11}
                  left={{ name: "m/s²" }}
                  series={[
                    { name: "MPU9250 X", data: pts(wave, "mpu9250_x_mps2"), color: pal.line.ppa_mpu9250 || pal.lineDefault, width: 1.5 },
                    { name: "MPU9250 Y", data: pts(wave, "mpu9250_y_mps2"), color: pal.line.tilt_y || pal.lineDefault, width: 1.3, dash: "dashed" },
                    { name: "MPU9250 Z", data: pts(wave, "mpu9250_z_mps2"), color: pal.line.disp_u || pal.lineDefault, width: 1.3, dash: "dotted" },
                  ]}
                />
              ) : (
                <div className="sensor-empty">
                  <strong>No waveform loaded.</strong>
                  <span>Event changes remain draft until explicit load.</span>
                </div>
              )}
            </div>
          </div>
          <p className="sensor-transport-note">
            Estimated velocity: EXPERIMENTAL / UNVALIDATED — relative to first-sample zero velocity.
            Initial 10% of samples assumed stationary for baseline/gravity offset correction.
            Orientation changes, drift and filter calibration are NOT corrected. Not slope movement velocity, PPV or operational data.
          </p>
          <div className="sensor-grid sensor-wave-grid">
            {[
              { title: "ADXL355 estimated velocity XYZ", value: adxlVelocity },
              { title: "MPU9250 estimated velocity XYZ", value: mpuVelocity },
            ].map(({ title, value }) => (
              <div className="sensor-wave-card" key={title}>
                <h3>{title} — EXPERIMENTAL / UNVALIDATED</h3>
                {value.rows.length > 0 && (
                  <p className="sensor-transport-note">
                    {new Intl.DateTimeFormat("id-ID", { timeZone: "Asia/Jakarta", day: "2-digit", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value.rows.find(r => r.vx_mm_s != null).timestamp_utc))} WIB
                    {" · "}{value.rows.filter(r => r.vx_mm_s != null).length} samples
                    {" · "}{value.valid_segments ?? 1} valid segment(s)
                    {" · "}{value.gaps ?? 0} gap(s)
                    {" · "}X-axis: elapsed time
                  </p>
                )}
                {value.rows.length ? (
                  <PanelChart height={330} axisFontSize={11} xTimeMode="elapsed" left={{ name: "mm/s" }}
                    series={[
                      { name: "Vx", data: pts(value.rows, "vx_mm_s"), color: pal.line.ppa || pal.lineDefault, width: 1.5 },
                      { name: "Vy", data: pts(value.rows, "vy_mm_s"), color: pal.line.tilt_x || pal.lineDefault, width: 1.3, dash: "dashed" },
                      { name: "Vz", data: pts(value.rows, "vz_mm_s"), color: pal.line.displacement || pal.lineDefault, width: 1.3, dash: "dotted" },
                    ]} />
                ) : (
                  <div className="sensor-empty"><strong>Velocity unavailable</strong><span>{value.reason}</span></div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <details className="panel sensor-v2-provenance" style={{padding: "12px 18px", marginTop: 12}}>
        <summary style={{cursor: "pointer", fontWeight: 600}}>Data provenance & interpretation</summary>
        <div style={{marginTop: 12}}>
        <div className="sensor-v2-section-head">
          <div>
            <span className="sensor-v2-eyebrow">Provenance & interpretation</span>
            <h2>What this view represents</h2>
          </div>
        </div>

        <div className="sensor-v2-provenance-grid">
          <div><span>Source</span><strong>{sourceLabel}</strong></div>
          <div><span>Site</span><strong>{applied.siteId || "—"}</strong></div>
          <div><span>Device</span><strong>{applied.deviceId || "—"}</strong></div>
          {sourceFile && sourceFile !== "unavailable" && sourceFile !== "—" && <div><span>Latest position source file</span><strong>{sourceFile}</strong></div>}
          {latest && <div><span>Position validation</span><strong>{latest.validation_status || "unvalidated"}</strong></div>}
          <div><span>Interpolation</span><strong>none</strong></div>
        </div>

        {applied.source === SOURCE_REFERENCE && (
          <p>
            {ITB_REFERENCE_META.note} Reference data is real sample material, but it is not live/persisted operational telemetry,
            not production displacement acceptance, and not ML ground truth.
          </p>
        )}
        {applied.source === SOURCE_SYNTHETIC && (
          <p>
            SYNTHETIC DEMO DATA — NOT FIELD MEASUREMENT. Browser-only, deterministic, and excluded from DB, PPK,
            displacement baseline, alarm evaluation, and ML ground truth.
          </p>
        )}
        {applied.source === SOURCE_ACTUAL && (
          <p>
            Actual GNSS is persisted telemetry, but direct GNSS position is not production-valid displacement.
            PPK/displacement remains UNVALIDATED until geodetic production acceptance is complete.
          </p>
        )}
        </div>
      </details>

      <details className="panel sensor-guard">
        <summary>Data limitations & interpretation</summary>
        <p>
          GNSS direct position is positioning telemetry and does not automatically become production-valid displacement.
          Accelerometer panels show acceleration XYZ only; MPU9250 is not described as gyro/angular-rate because those fields are absent.
          LoRa blast acceleration is event/manual-upload data rather than a continuous live 1000 Hz stream.
          Missing data is not fabricated or silently interpolated.
        </p>
      </details>
    </div>
  );
}
