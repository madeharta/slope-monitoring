// Inverse-velocity failure forecast (Fukuzono 1985): 1/velocity trends toward
// zero as a slope enters tertiary creep, and its x-intercept estimates the
// failure time. This is empirical extrapolation from the GNSS displacement
// series — NOT a Factor-of-Safety / stability model (out of scope, context.md
// §2). Four rules from domain/inverse-velocity are honoured:
//   1. smooth before differentiating,
//   2. fit only the recent accelerating window (last 12 h), not all history,
//   3. render the fit as a dashed extrapolation with an explicit uncertainty
//      band and label the estimate as a range, not a single time,
//   4. SUPPRESS the panel when the slope is not accelerating — a failure
//      estimate on a stable slope is the most dangerous possible output.
// estimateFailure() returns null in that case; the parent then renders nothing.

const WINDOW_H = 12;
const DAY_MS = 86_400_000;

// centred/trailing moving average to smooth the noisy displacement series
function smooth(vals, k = 3) {
  return vals.map((_, i) => {
    let s = 0, n = 0;
    for (let j = Math.max(0, i - k); j <= Math.min(vals.length - 1, i + k); j++) { s += vals[j]; n++; }
    return s / n;
  });
}

// points: [[isoTime, mm], ...] of GNSS resultant displacement (ascending time)
export function estimateFailure(points) {
  const pts = (points || []).filter((p) => p[1] != null).map((p) => [new Date(p[0]).getTime(), p[1]]);
  if (pts.length < 6) return null;

  const nowMs = pts[pts.length - 1][0];
  const winStart = nowMs - WINDOW_H * 3600e3;
  const win = pts.filter((p) => p[0] >= winStart);
  if (win.length < 5) return null;

  // velocity (mm/day) between smoothed consecutive samples
  const sm = smooth(win.map((p) => p[1]));
  const inv = []; // [{ tH, y }] — tH = hours since window start, y = 1/velocity (day/mm)
  for (let i = 1; i < win.length; i++) {
    const dtDays = (win[i][0] - win[i - 1][0]) / DAY_MS;
    if (dtDays <= 0) continue;
    const v = (sm[i] - sm[i - 1]) / dtDays; // mm/day
    if (v <= 0.05) continue; // not moving forward here — skip
    inv.push({ tH: (win[i][0] - winStart) / 3600e3, y: 1 / v });
  }
  if (inv.length < 4) return null;

  // least-squares fit of 1/v against time (hours)
  const n = inv.length;
  const sx = inv.reduce((a, p) => a + p.tH, 0);
  const sy = inv.reduce((a, p) => a + p.y, 0);
  const sxx = inv.reduce((a, p) => a + p.tH * p.tH, 0);
  const sxy = inv.reduce((a, p) => a + p.tH * p.y, 0);
  const denom = n * sxx - sx * sx;
  if (denom === 0) return null;
  const slope = (n * sxy - sx * sy) / denom; // day/mm per hour
  const intercept = (sy - slope * sx) / n;
  if (slope >= 0) return null; // 1/v not falling → not accelerating → suppress

  const tFail = -intercept / slope;      // hours since window start where 1/v = 0
  const lead = tFail - WINDOW_H;          // hours from now
  if (!isFinite(lead) || lead <= 0 || lead > 240) return null;

  // uncertainty from the residual scatter of the fit, widened into a ±band
  const rms = Math.sqrt(inv.reduce((a, p) => a + (p.y - (slope * p.tH + intercept)) ** 2, 0) / n);
  const frac = Math.min(0.45, 0.15 + rms / (Math.abs(intercept) || 1));
  return {
    leadLow: Math.max(1, lead * (1 - frac)),
    leadHigh: lead * (1 + frac),
    lead, inv, slope, intercept, invMax: Math.max(...inv.map((p) => p.y)) * 1.12,
  };
}

const p2 = (n) => String(Math.round(n)).padStart(2, "0");

export default function TimeToFailure({ estimate }) {
  const est = estimate;
  if (!est) return null;

  // mini plot: x spans now-12h (left) .. now+24h (right); observed 1/v on the
  // left third, dashed projection + uncertainty band into the future.
  const X0 = 10, X1 = 288, Y0 = 8, Y1 = 86;
  const SPAN_H = WINDOW_H + 24;
  const xOf = (tH) => X0 + (tH / SPAN_H) * (X1 - X0); // tH since window start
  const yOf = (v) => Y0 + (1 - Math.min(v, est.invMax) / est.invMax) * (Y1 - Y0);

  const obs = est.inv.map((p) => `${xOf(p.tH).toFixed(1)},${yOf(p.y).toFixed(1)}`).join(" ");
  const nowX = xOf(WINDOW_H), nowY = yOf(est.inv[est.inv.length - 1].y);
  const xFail = xOf(WINDOW_H + est.lead);
  const xLow = xOf(WINDOW_H + est.leadLow), xHigh = xOf(Math.min(WINDOW_H + est.leadHigh, SPAN_H));

  return (
    <div style={{ padding: "10px 14px 14px", display: "flex", flexDirection: "column", flex: 1 }}>
      <div style={{ fontSize: 11, letterSpacing: ".04em", color: "var(--ink-3)", marginBottom: 8 }}>
        Inverse velocity, 1/v vs time — Fukuzono (1985)
      </div>
      <svg viewBox="0 0 300 112" style={{ display: "block", width: "100%", height: "auto" }}>
        <rect x={X0} y={Y0} width={X1 - X0} height={Y1 - Y0} fill="var(--chart-plot, #0c0c10)" />
        <line x1={X0} x2={X1} y1={Y1} y2={Y1} stroke="var(--line, #26262d)" />
        <line x1={X0} x2={X1} y1={(Y0 + Y1) / 2} y2={(Y0 + Y1) / 2} stroke="var(--line-soft, #1c1c22)" />
        <polygon points={`${nowX.toFixed(1)},${nowY.toFixed(1)} ${xLow.toFixed(1)},${Y1} ${xHigh.toFixed(1)},${Y1}`}
          fill="var(--bahaya-soft, rgba(239,77,84,.13))" />
        <polyline points={`${nowX.toFixed(1)},${nowY.toFixed(1)} ${xFail.toFixed(1)},${Y1}`}
          fill="none" stroke="var(--bahaya, #ef4d54)" strokeWidth="1.4" strokeDasharray="5 4" />
        <polyline points={obs} fill="none" stroke="var(--ink, #e9e9ee)" strokeWidth="2" strokeLinejoin="round" />
        <text x={X0} y="102" fill="#7c7d87" fontSize="9" fontFamily="ui-monospace,monospace">−12 h</text>
        <text x={nowX} y="102" textAnchor="middle" fill="#7c7d87" fontSize="9" fontFamily="ui-monospace,monospace">now</text>
        <text x={X1} y="102" textAnchor="end" fill="#7c7d87" fontSize="9" fontFamily="ui-monospace,monospace">+24 h</text>
      </svg>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 10 }}>
        <span className="num" style={{ fontSize: 26, fontWeight: 650, letterSpacing: "-.01em", color: "var(--bahaya)" }}>
          {p2(est.leadLow)} – {p2(est.leadHigh)}
        </span>
        <span style={{ fontSize: 11, letterSpacing: ".12em", textTransform: "uppercase", color: "var(--ink-3)" }}>hours</span>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-2)", lineHeight: 1.5, marginTop: 6, textWrap: "pretty" }}>
        Linear 1/v fit on the last 12 h of GNSS resultant — an order of magnitude, not a time.
        Confirm in the field before acting on the lower bound.
      </div>
    </div>
  );
}
