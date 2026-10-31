// B15_13_WU_EXTRA_CARDS: 10 weather cards, Wind Gust and Rain Rate use WU actual data.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as echarts from 'echarts';
import { WEATHER_METRICS, filterWeatherRows, weatherWib, weatherRainTotal, weatherWindRose } from './weatherMockData.js';
import { loadWuWeather, wuFreshness } from './wuWeatherAdapter.js';
import { useAuth } from '../context/AuthContext.jsx';
import './weatherStation.css';

// B15_12_WU_ACTUAL: dates and time are user-controlled, not fixture constants.
const dateWib = time => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Jakarta', year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(time));
const wibDate = () => { const x=new Date(); return `${new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jakarta',year:'numeric',month:'2-digit',day:'2-digit'}).format(x)}`; };
const clock = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const number = (value, digits = 1) => Number.isFinite(value) ? Number(value).toFixed(digits) : '—';
const byKey = key => WEATHER_METRICS.find(m => m.key === key);
const latestLabel = row => row?.timestamp_utc ? `Latest observation · ${weatherWib(row.timestamp_utc)} WIB` : 'No observation';
const WEATHER_DETAIL_SLUGS = { temperature_c: 'temperature', wind_kmh: 'wind-speed', wind_gust_kmh: 'wind-gust', wind_direction_deg: 'wind-direction', rain_mm: 'rainfall', precip_rate_mmh: 'rain-rate', humidity_pct: 'humidity', pressure_hpa: 'barometer' };
const metricFromSlug = slug => slug === 'wind-rose' ? 'wind_direction_deg' : Object.keys(WEATHER_DETAIL_SLUGS).find(key => WEATHER_DETAIL_SLUGS[key] === slug);
function WeatherPlot({ option, label, height = 260 }) {
  const node = useRef(null);
  useEffect(() => {
    if (!node.current) return undefined;
    const chart = echarts.init(node.current);
    chart.setOption({ animation: false, ...option });
    const resize = () => chart.resize();
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    resizeObserver?.observe(node.current);
    window.addEventListener('resize', resize);
    return () => { resizeObserver?.disconnect(); window.removeEventListener('resize', resize); chart.dispose(); };
  }, [option]);
  return <div ref={node} className="weather-chart" style={{ height }} role="img" aria-label={label} />;
}
function windSpeedGustOption(rows) {
  const seriesFor = (name, key, color) => ({
    name, type: 'line', showSymbol: false, connectNulls: false,
    lineStyle: { width: 2 }, itemStyle: { color },
    data: rows.map(r => [r.timestamp_utc, Number.isFinite(r[key]) ? r[key] : null]),
  });
  return {
    tooltip: { trigger: 'axis', valueFormatter: value => value == null ? '—' : `${Number(value).toFixed(1)} km/h` },
    legend: { top: 4, data: ['Wind Speed', 'Wind Gust'] },
    grid: { left: 70, right: 24, top: 56, bottom: 60 },
    xAxis: { type: 'time', name: 'Time (WIB)', axisLabel: { hideOverlap: true, formatter: x => clock.format(x) }, splitLine: { show: false } },
    yAxis: { type: 'value', name: 'km/h', min: 0, splitLine: { lineStyle: { color: '#edf1f5' } } },
    series: [
      seriesFor('Wind Speed', 'wind_kmh', '#5680bb'),
      seriesFor('Wind Gust', 'wind_gust_kmh', '#3c8eae'),
    ],
  };
}

// B15_14_TEMP_DEWPOINT: both values originate from WU, never synthesized.
function temperatureDewPointOption(rows) {
  const mkSeries = (name, key, color) => ({
    name, type: 'line', showSymbol: false, connectNulls: false,
    lineStyle: { width: 2 }, itemStyle: { color },
    data: rows.map(r => [r.timestamp_utc, Number.isFinite(r[key]) ? r[key] : null]),
  });
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: value => value == null ? '—' : `${Number(value).toFixed(1)} °C`,
    },
    legend: { top: 4, data: ['Temperature', 'Dew Point'] },
    grid: { left: 70, right: 24, top: 56, bottom: 65 },
    xAxis: {
      type: 'time', name: 'Time (WIB)',
      axisLabel: { hideOverlap: true, formatter: x => clock.format(x) },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', name: '°C', scale: true,
      splitLine: { lineStyle: { color: '#edf1f5' } },
    },
    series: [
      mkSeries('Temperature', 'temperature_c', '#dd705d'),
      mkSeries('Dew Point', 'dew_point_c', '#3c8eae'),
    ],
  };
}

function timeOption(rows, key, type = 'line') {
  if (key === 'temperature_c') return temperatureDewPointOption(rows);
  if (key === 'wind_kmh' || key === 'wind_gust_kmh') return windSpeedGustOption(rows);
  const metric = byKey(key);
  return {
    tooltip: { trigger: 'axis', valueFormatter: v => v == null ? '—' : `${Number(v).toFixed(metric.digits)} ${metric.unit}` },
    grid: { left: 65, right: 24, top: 36, bottom: 60 },
    xAxis: { type: 'time', axisLabel: { hideOverlap: true, formatter: x => clock.format(x) }, splitLine: { show: false } },
    yAxis: { type: 'value', name: metric.unit, scale: key !== 'rain_mm', min: key === 'rain_mm' ? 0 : undefined, splitLine: { lineStyle: { color: '#edf1f5' } } },
    series: [{ name: metric.label, type, showSymbol: false, connectNulls: false, barMaxWidth: 16, itemStyle: { color: metric.color }, lineStyle: { width: 2 }, data: rows.map(r => [r.timestamp_utc, r[key] ?? null]) }],
  };
}
function windRoseDetailOption(rows) {
  const sectors = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const counts = weatherWindRose(rows);
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: value => `${value} observations` },
    grid: { left: 65, right: 24, top: 26, bottom: 46 },
    xAxis: { type: 'category', data: sectors, axisTick: { alignWithLabel: true } },
    yAxis: { type: 'value', name: 'Observations', min: 0, minInterval: 1, splitLine: { lineStyle: { color: '#edf1f5' } } },
    series: [{ name: 'Frequency', type: 'bar', barMaxWidth: 42, data: counts,
      itemStyle: { color: '#429a85', borderRadius: [5, 5, 0, 0] } }],
  };
}
function TrendMetric({ rows, metricKey, unit, label, color, digits = 1 }) {
  const last = rows.at(-1);
  const value = last?.[metricKey];
  const series = useMemo(() => ({
    tooltip: { trigger: 'axis', valueFormatter: v => `${number(v, digits)} ${unit}` },
    grid: { left: 10, right: 12, top: 12, bottom: 16, containLabel: false },
    xAxis: { type: 'time', show: false },
    yAxis: { type: 'value', scale: true, show: false },
    series: [{ type: 'line', name: label, data: rows.map(r => [r.timestamp_utc, Number.isFinite(r[metricKey]) ? r[metricKey] : null]), smooth: 0.2,
      symbol: 'none', connectNulls: false, lineStyle: { color, width: 2.7 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}44` }, { offset: 1, color: `${color}00` }] } } }],
  }), [rows, metricKey, label, unit, color, digits]);
  return <><div className="weather-trend-value">{number(value, digits)} <small>{unit}</small></div><p className="weather-summary-caption">{latestLabel(last)}</p><WeatherPlot option={series} label={`${label} trend`} height={124} /><p className="weather-mini-note">Selected-range observations</p></>;
}
function WindDirectionDial({ degrees, timestamp }) {
  const direction = Number.isFinite(degrees) ? degrees : null;
  const rotation = direction == null ? 0 : (direction + 180) % 360;
  return <div className="weather-wind-dial" role="img" aria-label={direction == null ? 'No direction data' : `Wind from ${direction} degrees`}>
    <p className="weather-summary-caption">{latestLabel({ timestamp_utc: timestamp })}</p>
    <div className="weather-wind-dial-ring"><span>N</span><span>E</span><span>S</span><span>W</span>
      <div className="weather-wind-dial-pointer" style={{ transform: `translate(-50%, -50%) rotate(${rotation}deg)` }}><div /></div>
      <div className="weather-wind-dial-hub" />
    </div>
    <p className="weather-mini-note">{direction == null ? '—' : `${number(direction, 0)}°`} · wind origin (meteorological convention)</p>
  </div>;
}
function WindRose({ rows }) {
  const directions = ['N','NE','E','SE','S','SW','W','NW'];
  const counts = weatherWindRose(rows);
  const maximum = Math.max(1, ...counts);
  return <div className="weather-wind-bars" role="img" aria-label="Wind-direction frequencies by sector">
    {directions.map((direction, i) => <div className="weather-wind-bar-row" key={direction}><span>{direction}</span><div className="weather-wind-bar-track"><div style={{ width: `${counts[i]/maximum*100}%` }} /></div><small>{counts[i]}</small></div>)}
    <p className="weather-mini-note">Direction-frequency sectors · {rows.length} observations · {rows.length ? `${weatherWib(rows[0].timestamp_utc)}–${weatherWib(rows.at(-1).timestamp_utc)} WIB` : "no observations"}</p>
  </div>;
}
function TemperatureSummary({ rows, last }) {
  const d = {heat_index_c:last?.heat_index_c, dew_point_c:last?.dew_point_c};
  return <>
    <TrendMetric rows={rows} metricKey="temperature_c" unit="°C" label="temperature" color="#dd705d" />
    <div className="weather-derived-tags"><span>Heat index {number(d.heat_index_c)}°</span><span>Dew point {number(d.dew_point_c)}°</span></div>
    <p className="weather-mini-note">Values supplied by Weather Underground when available.</p>
  </>;
}
function RainAccumulationSummary({ rows }) {
  const valid=rows.filter(r=>Number.isFinite(r.rain_mm));
  if (!valid.length) return <div className="weather-empty">Rainfall interval totals unavailable: no consecutive valid daily cumulative readings in the selected range.</div>;
  const cutoff=Date.parse(rows.at(-1)?.timestamp_utc)-24*3600000;
  const last24=weatherRainTotal(valid.filter(r=>Date.parse(r.timestamp_utc)>=cutoff));
  const total = weatherRainTotal(rows);
  const max = Math.max(total, last24, 0.001);
  const segments = [
    { label: 'Last 24 hours', value: last24, color: '#dd705d' },
    { label: 'Selected period', value: total, color: '#3c8eae' },
  ];
  return <div className="weather-rain-summary" role="group" aria-label="rainfall accumulations">
    <div className="weather-trend-value">{number(last24)} <small>mm / 24h</small></div>
    <p className="weather-summary-caption">24-hour accumulated rainfall · ending {rows.length ? `${weatherWib(rows.at(-1).timestamp_utc)} WIB` : "—"}</p>
    <div className="weather-rain-tracks">
      {segments.map(segment => <div className="weather-rain-track-row" key={segment.label}>
        <div className="weather-rain-track-label"><span>{segment.label}</span><strong>{number(segment.value)} mm</strong></div>
        <div className="weather-rain-track"><div style={{ width: `${Math.max(0, segment.value / max * 100)}%`, background: segment.color }} /></div>
      </div>)}
    </div>
    <p className="weather-mini-note">accumulations · not live. Values are totals, NOT rain rate (mm/h).</p>
  </div>;
}
function WeatherPanel({ title, children, onOpen }) { return <section className="weather-panel weather-clickable" onClick={onOpen} onKeyDown={e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onOpen(); } }} role="button" tabIndex={0} aria-label={`Open ${title.replace('','')} details`}><h2>{title}<span className="weather-card-action">Explore ↗</span></h2>{children}</section>; }
export default function WeatherStation() {
  const navigate = useNavigate();
  const {authFetch}=useAuth();
  const { metricSlug } = useParams();
  const isDetail = metricSlug !== undefined;
  const routeMetricKey = metricFromSlug(metricSlug);
  const openDetails = key => { navigate(`/weather/${WEATHER_DETAIL_SLUGS[key]}`); };
  const isWindRose = metricSlug === 'wind-rose';
  const metricKey = routeMetricKey || 'pressure_hpa';
  const [from,setFrom]=useState(()=>{const d=new Date(Date.now()-7*86400000);return dateWib(d);});
  const [to,setTo]=useState(wibDate);
  const [fromHour,setFromHour]=useState('00:00');
  const [toHour,setToHour]=useState('23:59');
  const [allRows,setAllRows]=useState([]);
  const [weatherLoading,setWeatherLoading]=useState(true);
  const [weatherError,setWeatherError]=useState('');
  const [refreshTick,setRefreshTick]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setRefreshTick(v=>v+1),60000);return ()=>clearInterval(timer)},[]);
  const rangeValid=Boolean(from&&to&&/^\d{2}:\d{2}$/.test(fromHour)&&/^\d{2}:\d{2}$/.test(toHour)&&Date.parse(`${from}T${fromHour}:00+07:00`)<Date.parse(`${to}T${toHour}:59+07:00`));
  useEffect(()=>{
    const controller=new AbortController();
    if(!rangeValid){setWeatherError('Invalid date/time range');setWeatherLoading(false);return ()=>controller.abort();}
    setWeatherLoading(true);setWeatherError('');
    loadWuWeather(authFetch,{from:`${from}T${fromHour}:00+07:00`,to:`${to}T${toHour}:59+07:00`,signal:controller.signal})
      .then(rows=>{if(!controller.signal.aborted){setAllRows(rows);setWeatherLoading(false);}})
      .catch(e=>{if(!controller.signal.aborted){setAllRows([]);setWeatherError(e.message);setWeatherLoading(false);}});
    return ()=>controller.abort();
  },[authFetch,from,to,fromHour,toHour,refreshTick,rangeValid]);
  const [page, setPage] = useState(1), [sortDesc, setSortDesc] = useState(true);
  const metric = byKey(metricKey) || WEATHER_METRICS[0];
  const rows=allRows;
  const displayRows = useMemo(() => sortDesc ? [...rows].reverse() : rows, [rows, sortDesc]);
  const last=rows.at(-1);
  const stationId=last?.station_id || rows[0]?.station_id || "—";
  const freshness=weatherError?"DATA UNAVAILABLE":weatherLoading?"LOADING":wuFreshness(rows);
  const perPage = 15, pages = Math.max(1, Math.ceil(displayRows.length / perPage)), actualPage = Math.min(page, pages);
  const dashboardRows = rows.slice(-192);
  const chart = useMemo(() => isWindRose ? windRoseDetailOption(rows) : timeOption(rows, metric.key, metric.key === 'rain_mm' ? 'bar' : 'line'), [rows, metric, isWindRose]);
  return <main className="weather-page">
    <div className="weather-heading"><div><p className="weather-eyebrow">Independent module · Weather Station</p><h1>Weather Station</h1><p>Weather Underground observations · updated automatically every 15 minutes</p></div><strong className="weather-mock-badge">{freshness}</strong></div>
    <div className="weather-warning" role="status">{weatherError ? `Weather data unavailable: ${weatherError}` : weatherLoading ? "Loading Weather Underground observations…" : `${rows.length} Weather Underground observations in selected range. Weather metrics do not trigger operational slope alarms.`}</div>
    <div className="weather-station-meta"><span><strong>Station reference:</strong> {stationId}</span><span><strong>Source:</strong> Weather Underground PWS</span><span><strong>Timezone:</strong> WIB (Asia/Jakarta)</span><span><strong>Last observation:</strong> {last ? weatherWib(last?.timestamp_utc) + " WIB" : "—"}</span></div>
    <div className="weather-controls" role="group" aria-label="Weather observation range"><label>From (WIB)<input type="date" value={from} onChange={e=>{setFrom(e.target.value);setPage(1);}} /></label><label>From time (WIB)<input type="time" value={fromHour} onChange={e=>{setFromHour(e.target.value);setPage(1);}} /></label><label>To (WIB)<input type="date" value={to} onChange={e=>{setTo(e.target.value);setPage(1);}} /></label><label>To time (WIB)<input type="time" value={toHour} onChange={e=>{setToHour(e.target.value);setPage(1);}} /></label></div>
      {isDetail && <nav className="weather-detail-nav" aria-label="Weather navigation"><button type="button" onClick={() => navigate('/weather')}>← Back to Weather Station</button><span>Historical chart and observation table</span></nav>}
    {!isDetail && !weatherLoading && !weatherError && !rows.length && <div className="weather-empty">No observations available for the selected range.</div>}
      {!isDetail && rows.length > 0 && <div className="weather-bulletin">
      <WeatherPanel title="Temperature" onOpen={() => openDetails('temperature_c')}><TemperatureSummary rows={dashboardRows} last={last} /></WeatherPanel>
      <WeatherPanel title="Humidity" onOpen={() => openDetails('humidity_pct')}><TrendMetric rows={dashboardRows} metricKey="humidity_pct" unit="%" label="humidity" color="#6389b3" digits={0} /></WeatherPanel>
      <WeatherPanel title="Barometer" onOpen={() => openDetails('pressure_hpa')}><TrendMetric rows={dashboardRows} metricKey="pressure_hpa" unit="hPa" label="barometer" color="#a479bf" /></WeatherPanel>
      <WeatherPanel title="Wind Speed" onOpen={() => openDetails('wind_kmh')}><TrendMetric rows={dashboardRows} metricKey="wind_kmh" unit="km/h" label="wind speed" color="#3c8eae" /></WeatherPanel>
      <WeatherPanel title="Wind Gust" onOpen={() => openDetails('wind_gust_kmh')}><TrendMetric rows={dashboardRows} metricKey="wind_gust_kmh" unit="km/h" label="wind gust" color="#3c8eae" /></WeatherPanel>
      <WeatherPanel title="Wind Direction" onOpen={() => openDetails('wind_direction_deg')}><WindDirectionDial degrees={last?.wind_direction_deg} timestamp={last?.timestamp_utc} /></WeatherPanel>
      <WeatherPanel title="Wind Rose" onOpen={() => navigate('/weather/wind-rose')}><WindRose rows={rows} /></WeatherPanel>
      <WeatherPanel title="Total Rain" onOpen={() => openDetails('rain_mm')}><RainAccumulationSummary rows={rows} /></WeatherPanel>
      <WeatherPanel title="Current Rain" onOpen={() => openDetails('rain_mm')}><div className="weather-readout"><strong>{number(Number.isFinite(last?.rain_mm) ? last.rain_mm : last?.precip_rate_mmh)} <small>{Number.isFinite(last?.rain_mm) ? "mm" : "mm/h"}</small></strong><p className="weather-summary-caption">Latest observation interval · {weatherWib(last?.timestamp_utc)} WIB</p><p>{Number.isFinite(last?.rain_mm) ? "Rainfall calculated from consecutive daily cumulative observations (mm)." : "Rain rate from WU (mm/h); interval accumulation unavailable."}</p></div></WeatherPanel>
      <WeatherPanel title="Rain Rate" onOpen={() => openDetails('precip_rate_mmh')}><TrendMetric rows={dashboardRows} metricKey="precip_rate_mmh" unit="mm/h" label="rain rate" color="#439e88" /></WeatherPanel>
    </div>}
    {isDetail && !routeMetricKey && <div className="weather-empty" role="alert">Unknown weather parameter. <button type="button" onClick={() => navigate('/weather')}>Back to Weather Station</button></div>}
    {isDetail && routeMetricKey && <div className="weather-detail-stack">
      <section className="weather-panel weather-detail-chart"><div className="weather-table-top"><div><h2>{isWindRose ? "Wind Rose" : (metric.key === "temperature_c" ? "Temperature & Dew Point" : (["wind_kmh", "wind_gust_kmh"].includes(metric.key) ? "Wind Speed & Wind Gust" : metric.label))} — historical detail</h2><p>observations · {rows.length} points · WIB (UTC+7) · no gap interpolation</p></div><span className="weather-detail-unit">{isWindRose ? "counts" : metric.unit}</span></div>

        {rows.length ? <WeatherPlot option={chart} label={isWindRose ? "wind-sector frequency distribution" : `historical ${metric.label}`} height={365} /> : <div className="weather-empty">No observations for this range.</div>}
        {isWindRose && <p className="weather-mini-note">Wind Rose counts observations per direction sector (N, NE, E, SE, S, SW, W, NW), not speed or a temporal direction series. Date filters apply to both the distribution and the table.</p>}
        {!isWindRose && metric.key === 'wind_direction_deg' && <p className="weather-mini-note">Direction is circular: 0° and 360° denote the same heading. Line transitions are display-only and must not be interpreted as arithmetic averages.</p>}
        {metric.key === 'rain_mm' && <p className="weather-mini-note">Rain values refer to an observation interval, not rain rate (mm/h).</p>}
      </section>
      <section className="weather-panel"><div className="weather-table-top"><div><h2>{isWindRose ? "Wind Rose" : metric.label} — observation table</h2><p>Same {rows.length} observed rows and date filters as chart · raw metric values, no interpolation</p></div><button type="button" onClick={() => {setSortDesc(v=>!v);setPage(1);}}>Timestamp {sortDesc ? '↓' : '↑'}</button></div>
        <div className="weather-table-scroll"><table><thead><tr><th>Timestamp (WIB)</th><th>{metric.label} ({metric.unit})</th>{isWindRose && <th>Sector</th>}<th>Quality</th><th>Provenance</th></tr></thead><tbody>{displayRows.slice((actualPage-1)*perPage,actualPage*perPage).map(row=><tr key={row.id}><td>{weatherWib(row.timestamp_utc)}</td><td>{Number.isFinite(row[metric.key]) ? number(row[metric.key],metric.digits) : '—'}</td>{isWindRose && <td>{Number.isFinite(row.wind_direction_deg) ? ['N','NE','E','SE','S','SW','W','NW'][Math.floor((((row.wind_direction_deg % 360) + 360) % 360 + 22.5) / 45) % 8] : '—'}</td>}<td>{row.quality ?? '—'}</td><td>{typeof row.source === 'string' && row.source.trim() ? row.source : 'UNKNOWN'}</td></tr>)}</tbody></table>{!rows.length && <div className="weather-empty">No observations in this range.</div>}</div>
        <div className="weather-pagination"><span>Page {actualPage} / {pages}</span><button type="button" disabled={actualPage<=1} onClick={() => setPage(p=>Math.max(1,p-1))}>Previous</button><button type="button" disabled={actualPage>=pages} onClick={() => setPage(p=>Math.min(pages,p+1))}>Next</button></div>
      </section>
    </div>}
    <p className="weather-footnote">Weather Underground observations are informational only. No automatic weather-to-landslide operational alarm linkage is enabled.</p>
  </main>;
}
