// Experimental only: segmentwise integration of contiguous, full-resolution acceleration.
// An acceleration-only estimate cannot establish absolute or long-term velocity.
function timestampMicroseconds(value) {
  if (typeof value !== "string") return NaN;
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return NaN;
  const fraction = /\.(\d+)(?:Z|[+-]\d\d:?\d\d)$/.exec(value);
  const micro = fraction ? Number((fraction[1] + "000000").slice(0, 6)) : 0;
  return Math.floor(ms / 1000) * 1000000 + (ms % 1000) * 1000 + micro % 1000;
}

export function estimateAccelVelocity(rows, prefix, meta = {}) {
  if (!Array.isArray(rows) || rows.length < 20) return { rows: [], reason: "At least 20 consecutive samples required" };
  if ((meta.downsampling?.method ?? "none") !== "none" || Number(meta.downsampling?.stride ?? 1) !== 1 ||
      Number(meta.total_samples ?? rows.length) !== rows.length) {
    return { rows: [], reason: "Full-resolution waveform required; downsampled data cannot be integrated" };
  }
  const samples = rows.map(r => ({
    t: timestampMicroseconds(r.timestamp_utc),
    idx: r.sample_index == null ? null : Number(r.sample_index),
    a: ["x", "y", "z"].map(axis => Number(r[`${prefix}_${axis}_mps2`])),
    timestamp_utc: r.timestamp_utc,
  }));
  if (samples.some(s => !Number.isFinite(s.t) || s.a.some(v => !Number.isFinite(v)) ||
      (s.idx != null && !Number.isSafeInteger(s.idx)))) {
    return { rows: [], reason: "Missing timestamp, sample_index or acceleration value" };
  }
  const positiveSteps = [];
  for (let i = 1; i < samples.length; i++) {
    const dt = samples[i].t - samples[i - 1].t;
    if (dt > 0 && (samples[i].idx == null || samples[i - 1].idx == null || samples[i].idx - samples[i - 1].idx === 1)) {
      positiveSteps.push(dt);
    }
  }
  positiveSteps.sort((a, b) => a - b);
  const nominal = positiveSteps[Math.floor(positiveSteps.length / 2)];
  if (!Number.isFinite(nominal) || nominal <= 0) {
    return { rows: [], reason: "No verifiable increasing timestamps; integration blocked" };
  }
  // Separate discontinuities; never interpolate or integrate across missing or duplicated epochs.
  const segments = [];
  let current = [samples[0]];
  let gaps = 0;
  for (let i = 1; i < samples.length; i++) {
    const dt = samples[i].t - samples[i - 1].t;
    const indicesOk = samples[i].idx == null || samples[i - 1].idx == null || samples[i].idx - samples[i - 1].idx === 1;
    if (dt <= 0 || dt > nominal * 1.5 || !indicesOk) {
      segments.push(current);
      current = [samples[i]];
      gaps++;
    } else current.push(samples[i]);
  }
  segments.push(current);
  const usable = segments.filter(s => s.length >= 20);
  if (!usable.length) return { rows: [], reason: `No continuous segment with >=20 samples (${gaps} timestamp/index gaps detected)` };
  const output = [];
  for (const segment of usable) {
    // Must be evaluated for a stationary pre-event interval in later field calibration.
    const n = Math.max(10, Math.min(100, Math.floor(segment.length * 0.1)));
    const baseline = [0, 1, 2].map(axis => segment.slice(0, n).reduce((sum, s) => sum + s.a[axis], 0) / n);
    const v = [0, 0, 0];
    // Null values explicitly break ECharts lines across dropped records.
    if (output.length) output.push({ timestamp_utc: output.at(-1).timestamp_utc, vx_mm_s: null, vy_mm_s: null, vz_mm_s: null });
    for (let i = 0; i < segment.length; i++) {
      if (i > 0) {
        const dt = (segment[i].t - segment[i-1].t) / 1e6;
        for (let a = 0; a < 3; a++) v[a] += 0.5 * (segment[i-1].a[a] + segment[i].a[a] - 2 * baseline[a]) * dt;
      }
      output.push({timestamp_utc: segment[i].timestamp_utc, vx_mm_s: v[0] * 1000, vy_mm_s: v[1] * 1000, vz_mm_s: v[2] * 1000});
    }
  }
  return { rows: output, reason: null, gaps, valid_segments: usable.length,
    method: "segment-wise initial-window baseline + trapezoidal integration",
    validation_status: "experimental_unvalidated" };
}
