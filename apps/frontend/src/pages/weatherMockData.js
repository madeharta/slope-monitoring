// Synthetic fixture. Never represent these observations as actual WeatherLink data.
export const WEATHER_FIXTURE = Object.freeze({
  source: 'mock', station: { name: 'WSDavis1', timezone: 'Asia/Jakarta', location: 'Cimenyan, Jawa Barat', status: 'DEMO — NOT LIVE' },
  generatedAt: '2026-10-22T07:00:00Z',
});
export const WEATHER_METRICS = Object.freeze([
  { key: 'temperature_c', label: 'Temperature', unit: '°C', color: '#bd5c4c', digits: 1 },
  { key: 'humidity_pct', label: 'Humidity', unit: '%', color: '#4a9f91', digits: 0 },
  { key: 'wind_kmh', label: 'Wind Speed', unit: 'km/h', color: '#5680bb', digits: 1 },
  { key: 'wind_gust_kmh', label: 'Wind Gust', unit: 'km/h', color: '#3c8eae', digits: 1 },
  { key: 'wind_direction_deg', label: 'Wind Direction', unit: '°', color: '#6982a8', digits: 0 },
  { key: 'rain_mm', label: 'Rainfall (interval)', unit: 'mm', color: '#5bafbf', digits: 1 },
  { key: 'precip_rate_mmh', label: 'Rain Rate', unit: 'mm/h', color: '#439e88', digits: 1 },
  { key: 'pressure_hpa', label: 'Barometer', unit: 'hPa', color: '#b187c2', digits: 1 },
]);
export function buildWeatherMockRows() {
  const start = Date.parse('2026-10-18T00:00:00Z');
  return Array.from({ length: 7 * 24 }, (_, i) => {
    const dayCycle = Math.sin((i % 24 - 6) * Math.PI / 12);
    return {
      id: `demo-${i}`, timestamp_utc: new Date(start + i * 3600000).toISOString(),
      temperature_c: +(26 + 3.2 * dayCycle + Math.sin(i * 0.67) * .3).toFixed(2),
      humidity_pct: Math.max(40, Math.min(96, Math.round(78 - dayCycle * 13 + Math.cos(i / 5) * 4))),
      wind_kmh: +(2.8 + Math.abs(Math.sin(i * .34)) * 7.3).toFixed(2),
      wind_direction_deg: (75 + Math.round(30 * Math.sin(i / 8)) + 360) % 360,
      rain_mm: i % 31 === 12 ? 0.6 : i % 29 === 7 ? 0.2 : 0,
      pressure_hpa: +(1016.4 + Math.sin(i * .12) * 1.8 + Math.cos(i * .035) * 1.2).toFixed(2),
      quality: 'simulated',
    };
  });
}
export const WEATHER_MOCK_ROWS = buildWeatherMockRows();
export function weatherWib(utc) {
  return new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(utc));
}
export function filterWeatherRows(rows, start, end) {
  const from = Date.parse(start), until = Date.parse(end);
  if (!Number.isFinite(from) || !Number.isFinite(until) || from > until) return [];
  return rows.filter(row => { const t = Date.parse(row.timestamp_utc); return Number.isFinite(t) && t >= from && t <= until; });
}

// Display-only derived values are illustrative, not WeatherLink-supplied fields.
export function weatherDerived(row) {
  if (!row) return null;
  const t = row.temperature_c, rh = row.humidity_pct;
  const dew = t - (100 - rh) / 5; // intentionally only a mock approximation
  return {
    wind_chill_c: +(t - Math.min(row.wind_kmh, 20) * 0.015).toFixed(1),
    heat_index_c: +(t + Math.max(0, rh - 55) * 0.035).toFixed(1),
    dew_point_c: +dew.toFixed(1),
    wet_bulb_c: +(t - (t - dew) * 0.45).toFixed(1),
  };
}
export function weatherRainTotal(rows) {
  return +(rows.reduce((sum, r) => sum + (Number.isFinite(r.rain_mm) ? Math.max(0, r.rain_mm) : 0), 0)).toFixed(2);
}
export function weatherWindRose(rows, buckets = 8) {
  const result = Array.from({ length: buckets }, () => 0);
  for (const row of rows) {
    if (!Number.isFinite(row.wind_direction_deg) || !Number.isFinite(row.wind_kmh) || row.wind_kmh < 0) continue;
    const idx = Math.floor((((row.wind_direction_deg % 360) + 360) % 360 + 180 / buckets) / (360 / buckets)) % buckets;
    result[idx] += 1;
  }
  return result;
}
