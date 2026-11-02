import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext.jsx';

const REQUIRED = ['gps_week','gps_tow_s','latitude_deg','longitude_deg','ellipsoidal_height_m','rtklib_quality','satellite_count','sdn_m','sde_m','sdu_m'];
const LABELS = {1:'FIX',2:'FLOAT',5:'SINGLE'};
const COLORS = {1:'#16866c',2:'#bd8836',5:'#8792a0'};
const fmt = (v, n=3) => Number.isFinite(v) ? v.toFixed(n) : '—';

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  const head = lines.shift()?.replace(/^\uFEFF/,'').split(',');
  if (!head || !REQUIRED.every(k => head.includes(k))) throw Error('CSV is not a ppk.qa.solution.v1 parser output');
  if (lines.length > 100000) throw Error('QA CSV exceeds the maximum number of rows');
  const rows = lines.filter(Boolean).map((line,i) => {
    const fields = line.split(',');
    if (fields.length !== head.length) throw Error(`Invalid CSV column count at row ${i+1}`);
    const obj=Object.fromEntries(head.map((k,j)=>[k, fields[j]]));
    const r=Object.fromEntries(REQUIRED.map(k=>[k,Number(obj[k])]));
    if (!Object.values(r).every(Number.isFinite) || !Number.isInteger(r.gps_week) || r.gps_tow_s<0 || r.gps_tow_s>=604800 || ![1,2,5].includes(r.rtklib_quality) || Math.abs(r.latitude_deg)>90 || Math.abs(r.longitude_deg)>180 || r.sdn_m<0 || r.sde_m<0 || r.sdu_m<0) throw Error(`Invalid QA value at row ${i+1}`);
    return {...r, epoch:r.gps_week*604800+r.gps_tow_s};
  });
  if (!rows.length || rows.some((r,i)=>i && r.epoch<=rows[i-1].epoch)) throw Error('Missing, duplicate, or unordered epochs');
  return rows;
}
// PPK_AXES_B14: elapsed GPST is relative to the first solution, not UTC.
function elapsedMinutes(epoch, firstEpoch) {
  return ((epoch - firstEpoch) / 60).toFixed(1);
}
function Scatter({rows,field,label,color='#157d99'}) {
  const validRows=rows.filter(r=>typeof r[field] === "number" && Number.isFinite(r[field]));
  if (!validRows.length) return <div className="ppk-qa-series"><div className="ppk-qa-series-title">{label}</div><p className="ppk-qa-hint">No valid observations for this series.</p></div>;
  const values=validRows.map(r=>r[field]);
  const lo=Math.min(...values), hi=Math.max(...values), span=hi-lo||1;
  const t0=rows[0].epoch, ts=rows[rows.length-1].epoch-t0||1;
  const ticks=[0,0.5,1];
  const X0=100, X1=780, Y0=14, Y1=106;
  return <div className="ppk-qa-series"><div className="ppk-qa-series-title">{label} <small>{fmt(lo,6)} – {fmt(hi,6)}</small></div>
    <svg viewBox="0 0 800 160" role="img" aria-label={`${label} versus elapsed GPST in minutes; minimum ${fmt(lo,6)}, maximum ${fmt(hi,6)}`} preserveAspectRatio="none">
      <line x1={X0} x2={X0} y1={Y0} y2={Y1} stroke="currentColor" opacity=".45" />
      <line x1={X0} x2={X1} y1={Y1} y2={Y1} stroke="currentColor" opacity=".45" />
      {ticks.map((f)=><g key={f}>
        <line x1={X0+f*(X1-X0)} x2={X0+f*(X1-X0)} y1={Y1} y2={Y1+4} stroke="currentColor" opacity=".5" />
        <text x={X0+f*(X1-X0)} y="125" textAnchor="middle" fill="currentColor" fontSize="11">{elapsedMinutes(t0+f*ts,t0)}</text>
      </g>)}
      <text x="10" y="19" fill="currentColor" fontSize="11">{fmt(hi,4)}</text>
      <text x="10" y={Y1} fill="currentColor" fontSize="11">{fmt(lo,4)}</text>
      <text x="440" y="146" textAnchor="middle" fill="currentColor" fontSize="11">Elapsed GPST (min)</text>
      <text x="10" y="60" fill="currentColor" fontSize="10">Value</text>
      {validRows.map((r,i)=> <circle key={i} cx={X0+(r.epoch-t0)/ts*(X1-X0)} cy={Y0+(1-(r[field]-lo)/span)*(Y1-Y0)} r="2" fill={COLORS[r.rtklib_quality]||color}><title>{`GPS week ${r.gps_week}; TOW ${r.gps_tow_s}s; ${LABELS[r.rtklib_quality]||'OTHER'}; ${label}: ${fmt(r[field],8)}`}</title></circle>)}
    </svg><div className="ppk-qa-legend">Y: {label} · X: elapsed GPST (minutes)</div></div>;
}
export default function PPKQACharts({siteId,roverId,timeRange,limit,revision}){
 const {authFetch}=useAuth();
 const [rows,setRows]=useState(null),[availability,setAvailability]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const [truncated,setTruncated]=useState(false);
 useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    // Keep the last validated QA chart visible during background refresh.

    async function loadQaPages() {
      if (!siteId?.trim() || !roverId?.trim()) {
        throw Error('Select a site and rover before loading PPK QA');
      }
      const accumulated = [];
      let cursor = null;
      const seen = new Set();
      let status = null;
      let hasMore = false;
      let pageCount = 0;
      do {
        const remaining = limit - accumulated.length;
        if (remaining <= 0) break;
        if (++pageCount > 50) throw Error('QA page limit exceeded');
        const params = new URLSearchParams({
          site_id: siteId.trim(), rover_device_id: roverId,
          time_range: timeRange, limit: String(Math.min(remaining, 500)),
          ...(cursor ? {cursor} : {}),
        });
        const resp = await authFetch(`/api/v1/ppk/qa/solutions?${params}`);
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) throw Error(typeof body.detail === 'string' ? body.detail : `HTTP ${resp.status}`);
        const filters = body.applied_filters || {};
        if (filters.site_id !== siteId.trim() || filters.rover_device_id !== roverId ||
            filters.time_range !== timeRange || filters.limit !== Math.min(remaining, 500)) {
          throw Error('QA response does not match the requested filters');
        }
        if (body.scope !== 'EXPERIMENTAL_ENGINE_QA_ONLY' ||
            body.schema_version !== 'ppk.qa.solution.v1' ||
            body.reference_type !== 'PROVISIONAL_SPP' ||
            body.validation_status !== 'unvalidated' ||
            body.operational_displacement_approved !== false ||
            !Array.isArray(body.rows)) throw Error('Invalid QA response contract');
        if (!['available','schema_unavailable'].includes(body.availability_status)) {
          throw Error('Invalid QA availability status');
        }
        if (status !== null && status !== body.availability_status) throw Error('QA availability changed between pages');
        status = body.availability_status;
        if (status === 'schema_unavailable' && body.rows.length) throw Error('QA schema unavailable but data are nonempty');
        const page = body.rows.map(r => ({...r, epoch: Number(r.gps_week) * 604800 + Number(r.gps_tow_s)}));
        for (const r of page) {
          if (!Number.isInteger(r.gps_week) || r.gps_week < 0 ||
              !Number.isFinite(r.gps_tow_s) || r.gps_tow_s < 0 || r.gps_tow_s >= 604800 ||
              !Number.isFinite(r.latitude_deg) || Math.abs(r.latitude_deg) > 90 ||
              !Number.isFinite(r.longitude_deg) || Math.abs(r.longitude_deg) > 180 ||
              !Number.isFinite(r.ellipsoidal_height_m) ||
              ![1,2,5].includes(r.rtklib_quality) ||
              ![r.sdn_m,r.sde_m,r.sdu_m].every(v => v === null || (Number.isFinite(v) && v >= 0))) {
            throw Error('Invalid PPK QA epoch');
          }
          const key = `${r.gps_week}/${r.gps_tow_s}/${r.id}`;
          if (seen.has(key) || (accumulated.length && r.epoch < accumulated[accumulated.length-1].epoch)) {
            throw Error('QA pagination yielded duplicates or invalid ordering');
          }
          seen.add(key);
          accumulated.push(r);
        }
        hasMore = body.pagination?.has_more === true;
        const next = body.pagination?.next_cursor;
        if (hasMore && (!next || next === cursor || page.length === 0)) {
          throw Error('Invalid QA pagination cursor');
        }
        cursor = hasMore ? next : null;
      } while (hasMore && accumulated.length < limit);
      return {rows: accumulated, status, hasMore};
    }

    loadQaPages().then(result => {
      if (!alive) return;
      setAvailability(result.status);
      setRows(result.rows);
      setTruncated(result.hasMore);
    }).catch(e => {
      if (alive) setError(e.message || 'QA fetch failed');
    }).finally(() => {if (alive) setLoading(false)});
    return () => {alive = false};
  },[authFetch,siteId,roverId,timeRange,limit,revision]);
 const counts=useMemo(()=>rows?rows.reduce((a,r)=>(a[r.rtklib_quality]=(a[r.rtklib_quality]||0)+1,a),{}):{},[rows]);
 return <section className="panel ppk-qa-section" aria-label="Experimental PPK QA charts">
   <div className="ppk-card-head"><div><h2>Experimental PPK engine QA — auto-loaded from QA API</h2><span>Source: persisted experimental QA only · BASE provisional SPP · unvalidated · not displacement</span></div></div>
   <p className="ppk-qa-hint">Applied: {siteId} · {roverId||'All QA rovers'} · {timeRange==='all'?'All available':timeRange} · limit {limit}. Chart epochs use GPST. UTC times from the API are valid only within the supported leap-second range.</p>
   {error && <p role="alert">QA API: {error}</p>}
   {!loading && !error && availability==='schema_unavailable' && <p role="status" className="ppk-qa-hint">Experimental PPK QA is unavailable: QA tables are not installed in this environment. This is not an empty measurement result. Status remains PROVISIONAL_SPP / unvalidated; no operational displacement.</p>}
   {loading && <p className="ppk-qa-hint">Loading QA results from API…</p>}{!loading && !error && availability==='available' && (!rows || rows.length===0) && <p className="ppk-qa-hint">No PPK QA results for the selected site, rover, and time range.</p>}
   {rows && rows.length>0 && <>
      <p className="ppk-qa-hint">{rows.length} epoch{truncated ? ' (limited by selected cap)' : ''} · API persisted · reference_type=PROVISIONAL_SPP · validation_status=unvalidated</p>
      <div className="ppk-qa-counts">{[1,2,5].map(q=><div key={q}><span>{LABELS[q]}</span><strong>{counts[q]||0}</strong></div>)}</div>
      <div className="ppk-qa-stacked" aria-label="PPK quality distribution">{[1,2,5].map(q=><span key={q} style={{width:`${((counts[q]||0)/rows.length)*100}%`,background:COLORS[q]}} title={`${LABELS[q]} ${counts[q]||0}`} />)}</div>
      <h3>Solution quality timeline</h3><div className="ppk-qa-timeline"><svg viewBox="0 0 800 118" style={{ height: 118, minHeight: 118, width: "100%", display: "block" }} role="img" aria-label="Solution quality by elapsed GPST in minutes; rows FIX, FLOAT and SINGLE" preserveAspectRatio="xMinYMid meet">
        {[[1,'FIX',20],[2,'FLOAT',48],[5,'SINGLE',76]].map(([q,name,y])=><g key={q}><text x="8" y={y+4} fontSize="11" fill="currentColor">{name}</text><line x1="90" x2="784" y1={y} y2={y} stroke="currentColor" opacity=".1" /></g>)}
        <line x1="90" x2="784" y1="89" y2="89" stroke="currentColor" opacity=".45" />
        {[0,0.5,1].map(f=><text key={f} x={90+f*694} y="103" textAnchor="middle" fontSize="10" fill="currentColor">{elapsedMinutes(rows[0].epoch+f*(rows[rows.length-1].epoch-rows[0].epoch),rows[0].epoch)}</text>)}
        <text x="437" y="115" textAnchor="middle" fontSize="10" fill="currentColor">Elapsed GPST (min)</text>
        {rows.map((r,i)=><circle key={i} cx={90+(r.epoch-rows[0].epoch)/((rows[rows.length-1].epoch-rows[0].epoch)||1)*694} cy={{1:20,2:48,5:76}[r.rtklib_quality]} r="2.4" fill={COLORS[r.rtklib_quality]}><title>{`GPS ${r.gps_week}/${r.gps_tow_s} · ${LABELS[r.rtklib_quality]}`}</title></circle>)}</svg><div className="ppk-qa-legend">Y: solution class (FIX / FLOAT / SINGLE) · X: elapsed GPST (minutes)</div></div>
      <h3>Experimental position & uncertainty</h3><p className="ppk-qa-hint">Absolute WGS84 ellipsoidal estimates, not displacement. Spread mixes FIX, FLOAT, and SINGLE; no RMSE or accuracy claim.</p>
      <div className="ppk-qa-series-grid"><Scatter rows={rows} field="latitude_deg" label="Latitude (°)"/><Scatter rows={rows} field="longitude_deg" label="Longitude (°)"/><Scatter rows={rows} field="ellipsoidal_height_m" label="Height ellipsoidal (m)"/><Scatter rows={rows} field="sdn_m" label="RTKLIB SD North (m)"/><Scatter rows={rows} field="sde_m" label="RTKLIB SD East (m)"/><Scatter rows={rows} field="sdu_m" label="RTKLIB SD Up (m)"/></div>
      <p className="ppk-qa-hint">SD denotes formal solver uncertainty, not survey-verified accuracy. Each series preserves gaps on the GPST time axis.</p>
   </>}
 </section>;
}
