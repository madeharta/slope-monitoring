/* B15.12: Weather Underground observations, normalized without fabricating missing metrics. */
const num = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
export function mapWuObservation(row) {
  const m = row?.metrics || {};
  const hist = m._source_format === 'WU_PWS_HISTORY_ALL_PERIOD_AGGREGATE';
  return {
    id: `${row.station_id}:${row.observed_at}`,
    timestamp_utc: row.observed_at,
    source: 'WEATHER_UNDERGROUND_PWS',
    station_id: row.station_id,
    qc_status: row.qc_status,
    quality: row.qc_status == null ? 'Not reported' : `WU QC ${row.qc_status}`,
    observation_kind: hist ? 'period average' : 'current observation',
    temperature_c: num(m.temp) ?? num(m.tempAvg),
    humidity_pct: num(m.humidity) ?? num(m.humidityAvg),
    wind_kmh: num(m.windSpeed) ?? num(m.windspeedAvg),
    wind_gust_kmh: num(m.windGust) ?? num(m.windgustHigh) ?? num(m._history_metric?.windgustHigh),
    wind_direction_deg: num(m.winddir) ?? num(m.winddirAvg),
    pressure_hpa: num(m.pressure),
    dew_point_c: num(m.dewpt) ?? num(m.dewptAvg),
    heat_index_c: num(m.heatIndex) ?? num(m.heatindexAvg),
    precip_rate_mmh: num(m.precipRate) ?? num(m._history_metric?.precipRate),
    precip_total_today_mm: num(m.precipTotal) ?? num(m._history_metric?.precipTotal),
    rain_mm: null, // derived from adjacent same-day readings below, never mapped from daily total
    lat: row.lat, lon: row.lon,
  };
}
export async function loadWuWeather(authFetch, {from, to, signal, maxRows=20000}={}) {
  if (typeof authFetch !== 'function') throw new Error('Authenticated API client missing');
  const all=[]; let offset=0;
  while (offset < maxRows) {
    const params=new URLSearchParams({limit: String(Math.min(2000,maxRows-offset)),offset:String(offset)});
    if (from) params.set('from',from);
    if (to) params.set('to',to);
    const response=await authFetch(`/api/v1/weather/wu/observations?${params}`, {signal});
    if(!response.ok) throw new Error(`Weather API HTTP ${response.status}`);
    const data=await response.json();
    if(!data?.ok || !Array.isArray(data.observations)) throw new Error('Invalid Weather API response');
    all.push(...data.observations.map(mapWuObservation));
    if(data.observations.length < Number(params.get('limit'))) break;
    offset += data.observations.length;
  }
  return calculateRainIntervals(all.sort((a,b)=>Date.parse(a.timestamp_utc)-Date.parse(b.timestamp_utc)));
}
// B15_12_RAIN_INTERVAL_QA: deltas of WU *daily cumulative* rain (mm).
// First observation of a local day, gaps >45 min, clock reversals, negative
// resets and missing cumulative are unknown (null), never fabricated zero.
const wibDay = iso => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit'
}).format(new Date(iso));
export function calculateRainIntervals(rows) {
  let prev = null;
  return rows.map(row => {
    const now = Date.parse(row.timestamp_utc);
    const today = Number.isFinite(now) ? wibDay(row.timestamp_utc) : null;
    const cumulative = row.precip_total_today_mm;
    let delta = null;
    if (prev && today && today === prev.day &&
        Number.isFinite(cumulative) && Number.isFinite(prev.cumulative) &&
        now > prev.time && now - prev.time <= 45 * 60 * 1000 &&
        cumulative >= prev.cumulative && cumulative >= 0) {
      delta = Math.max(0, Number((cumulative - prev.cumulative).toFixed(3)));
    }
    prev = {time: now, day: today, cumulative};
    return {...row, rain_mm: delta};
  });
}
export function wuFreshness(rows,now=Date.now()) {
  if(!rows?.length) return 'NO DATA';
  const last=Date.parse(rows.at(-1).timestamp_utc);
  return Number.isFinite(last)&&last<=now+300000&&now-last<=3600000?'DATA CURRENT':'DATA STALE';
}
