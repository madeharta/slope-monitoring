// Operational GNSS coordinates own the map marker whenever accepted by the API.
// Telemetry freshness must never override a validated GNSS location. The source
// and observation timestamp stay explicit; telemetry remains available separately.
const ALLOWED_STATUSES = new Set([
  "ESTIMATED_OPERATIONAL", "ACCEPTED_SPP",
  "ACCEPTED_PPK_FIX", "ACCEPTED_PPK_FLOAT",
]);
const ALLOWED_SOURCES = new Set(["RTKLIB_SPP", "RTKLIB_PPK"]);

export function mergeGnssLocations(devices, locations) {
  const byId = new Map();
  for (const item of locations || []) {
    if (!item || typeof item.device_id !== "string") continue;
    if (!ALLOWED_STATUSES.has(item.quality_status) || !ALLOWED_SOURCES.has(item.position_source)) continue;
    const lat = Number(item.latitude);
    const lon = Number(item.longitude);
    const t = Date.parse(item.observed_at || "");
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180 || (lat === 0 && lon === 0) || !Number.isFinite(t)) continue;
    const prev = byId.get(item.device_id);
    if (!prev || t > Date.parse(prev.observed_at)) byId.set(item.device_id, item);
  }
  return (devices || []).map((device) => {
    const location = byId.get(device.device_id);
    if (!location) return device;
    const prior = device.position || {};
    // Never reinterpret this operational SPP marker as a displacement reference.
    return { ...device, position: {
      ...prior,
      lat: Number(location.latitude), lon: Number(location.longitude),
      time: location.observed_at, source: location.position_source,
      validation_status: location.quality_status,
      h_acc_m: null, // P95 scatter is NOT certified position accuracy.
      gnss_quality_code: location.quality_code,
      ellipsoidal_height_m: location.ellipsoidal_height_m,
      reference_epoch: location.reference_epoch,
      operational_location: true,
      telemetry_position_time: prior.telemetry_position_time ?? prior.time ?? null,
      telemetry_position_source: prior.telemetry_position_source ?? prior.source ?? null,
    } };
  });
}
