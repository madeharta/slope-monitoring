// Keep existing device popup, connectivity and site navigation intact.
// GNSS positions override telemetry positions only when valid and no older.
export function mergeGnssLocations(devices, locations) {
  const byId = new Map();
  for (const item of locations || []) {
    if (!item || typeof item.device_id !== "string") continue;
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
    const oldTime = Date.parse(device.position?.time || "");
    const newTime = Date.parse(location.observed_at);
    if (Number.isFinite(oldTime) && oldTime > newTime) return device;
    return { ...device, position: {
      ...(device.position || {}),
      lat: Number(location.latitude), lon: Number(location.longitude),
      time: location.observed_at, source: location.position_source,
      validation_status: location.quality_status,
      h_acc_m: null,
      gnss_quality_code: location.quality_code,
      ellipsoidal_height_m: location.ellipsoidal_height_m,
    } };
  });
}
