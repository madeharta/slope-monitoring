import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";

export default function GnssSynchronizationQA({ siteId, window, deviceId }) {
  const { authFetch } = useAuth();
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const from = window?.from;
  const to = window?.to;
  useEffect(() => {
    if (!siteId || !from || !to) return;
    const controller = new AbortController();
    setResult(null); setError(null);
    const q = new URLSearchParams({site_id:siteId, from, to, tolerance_s:"2"});
    authFetch(`/api/v1/sensors/gnss/rawx/synchronization?${q}`, {signal:controller.signal})
      .then(async (r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((v) => { if (!controller.signal.aborted) setResult(v); })
      .catch((err) => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [authFetch, siteId, from, to]);
  if (!siteId || !from || !to) return null;
  if (error) return <section className="panel sensor-card gnss-sync-qa"><h2>BASE–ROVER synchronization</h2><p role="alert">Synchronization API failed: {error}</p></section>;
  if (!result) return <section className="panel sensor-card gnss-sync-qa"><h2>BASE–ROVER synchronization</h2><p>Loading verified epoch pairs…</p></section>;
  // Epoch matching remains server-derived; only the view is device-scoped.
  // BASE is a reference, so show both rover comparisons when BASE is selected.
  // ROVER-01 has no verified GNSS RAWX and must not inherit other rovers' bars.
  if (deviceId === "ROVER-01") return null;
  const allRovers = Array.isArray(result.rovers) ? result.rovers : [];
  const selectedRover = deviceId && deviceId !== "BASE-01" ? deviceId : null;
  const rovers = selectedRover ? allRovers.filter(r => r.device_id === selectedRover) : allRovers;
  if (!result.base_epochs && !rovers.length) return null;
  return <section className="panel sensor-card gnss-sync-qa" aria-label="BASE rover epoch synchronization">
    <div className="sensor-v2-section-head"><div><span className="sensor-v2-eyebrow">Verified RAWX UTC · experimental timing</span><h2>BASE–ROVER synchronization</h2></div></div>
    <p className="sensor-v2-note">BASE-01: {result.base_epochs} epochs · match tolerance ≤ {result.tolerance_s} s · {selectedRover ? `selected rover: ${selectedRover}` : "comparison: all rovers"} · window follows applied Analytics filter</p>
    {rovers.map(r => <div key={r.device_id} className="gnss-sync-row">
      <strong>{r.device_id}</strong>
      <div className="gnss-sync-track" role="img" aria-label={`${r.matched_epochs} matched of ${r.rover_epochs} epochs`}>
        {r.rover_epochs > 0 && <span style={{width:`${100*r.matched_epochs/r.rover_epochs}%`}} />}
      </div>
      <span>{r.matched_epochs}/{r.rover_epochs} epochs</span>
    </div>)}
    {rovers.length===0 && <p className="sensor-v2-note">No rover RAWX epochs in this selected window.</p>}
    <p className="sensor-v2-note">Only nearest-time epoch overlap. This does not prove satellite overlap, FIX accuracy, slope motion, or operational readiness.</p>
  </section>;
}
