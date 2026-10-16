import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext.jsx';

const REQUIRED = ['gps_week','gps_tow_s','latitude_deg','longitude_deg','ellipsoidal_height_m','rtklib_quality','satellite_count','sdn_m','sde_m','sdu_m'];
const LABELS = {1:'FIX',2:'FLOAT',5:'SINGLE'};
const COLORS = {1:'#16866c',2:'#bd8836',5:'#8792a0'};
const fmt = (v, n=3) => Number.isFinite(v) ? v.toFixed(n) : '—';

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  const head = lines.shift()?.replace(/^\uFEFF/,'').split(',');
  if (!head || !REQUIRED.every(k => head.includes(k))) throw Error('CSV bukan output parser ppk.qa.solution.v1');
  if (lines.length > 100000) throw Error('QA CSV terlalu besar');
  const rows = lines.filter(Boolean).map((line,i) => {
    const fields = line.split(',');
    if (fields.length !== head.length) throw Error(`Kolom CSV tidak valid pada row ${i+1}`);
    const obj=Object.fromEntries(head.map((k,j)=>[k, fields[j]]));
    const r=Object.fromEntries(REQUIRED.map(k=>[k,Number(obj[k])]));
    if (!Object.values(r).every(Number.isFinite) || !Number.isInteger(r.gps_week) || r.gps_tow_s<0 || r.gps_tow_s>=604800 || ![1,2,5].includes(r.rtklib_quality) || Math.abs(r.latitude_deg)>90 || Math.abs(r.longitude_deg)>180 || r.sdn_m<0 || r.sde_m<0 || r.sdu_m<0) throw Error(`Nilai QA tidak valid pada row ${i+1}`);
    return {...r, epoch:r.gps_week*604800+r.gps_tow_s};
  });
  if (!rows.length || rows.some((r,i)=>i && r.epoch<=rows[i-1].epoch)) throw Error('Epoch kosong, duplikat, atau tidak berurutan');
  return rows;
}
function Scatter({rows,field,label,color='#157d99'}) {
  const values=rows.map(r=>r[field]);
  const lo=Math.min(...values), hi=Math.max(...values), span=hi-lo||1;
  const t0=rows[0].epoch, ts=rows[rows.length-1].epoch-t0||1;
  return <div className="ppk-qa-series"><div className="ppk-qa-series-title">{label} <small>{fmt(lo,6)} – {fmt(hi,6)}</small></div>
    <svg viewBox="0 0 800 135" role="img" aria-label={`Experimental ${label} by GNSS epoch`} preserveAspectRatio="none">
      <line x1="24" x2="790" y1="113" y2="113" stroke="currentColor" opacity=".2" />
      {rows.map((r,i)=> <circle key={i} cx={24+(r.epoch-t0)/ts*766} cy={10+(1-(r[field]-lo)/span)*96} r="2" fill={COLORS[r.rtklib_quality]||color}><title>{`GPS week ${r.gps_week}; TOW ${r.gps_tow_s}s; ${LABELS[r.rtklib_quality]||'OTHER'}; ${label}: ${fmt(r[field],8)}`}</title></circle>)}
    </svg></div>;
}
export default function PPKQACharts({siteId,roverId,timeRange,limit,revision}){
 const {authFetch}=useAuth();
 const [rows,setRows]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 useEffect(()=>{let alive=true;setLoading(true);setError('');setRows(null);
  authFetch(`/api/v1/ppk/qa/solutions?${new URLSearchParams({site_id:siteId, ...(roverId?{rover_device_id:roverId}:{}),time_range:timeRange,limit:String(limit)})}`)
   .then(async resp=>{const body=await resp.json();if(!resp.ok)throw Error(body.detail||`HTTP ${resp.status}`);
     if(body.applied_filters?.site_id!==siteId||body.applied_filters?.rover_device_id!==(roverId||null)||body.applied_filters?.time_range!==timeRange||body.applied_filters?.limit!==limit)throw Error('Filter response mismatch');
     if(body.scope!=='EXPERIMENTAL_ENGINE_QA_ONLY'||body.schema_version!=='ppk.qa.solution.v1'||body.reference_type!=='PROVISIONAL_SPP'||body.validation_status!=='unvalidated'||body.operational_displacement_approved!==false||!Array.isArray(body.rows))throw Error('QA response contract mismatch');
     const converted=body.rows.map(r=>({...r,epoch:Number(r.gps_week)*604800+Number(r.gps_tow_s)}));
     if(converted.length>2000||converted.some((r,i)=>!Number.isFinite(r.epoch)||!Number.isFinite(r.latitude_deg)||!Number.isFinite(r.longitude_deg)||!Number.isFinite(r.ellipsoidal_height_m)||!Number.isFinite(r.sdn_m)||!Number.isFinite(r.sde_m)||!Number.isFinite(r.sdu_m)||![1,2,5].includes(r.rtklib_quality)||(i>0&&r.epoch<=converted[i-1].epoch)))throw Error('Malformed QA epoch data');
     if(alive)setRows(converted);
   }).catch(e=>{if(alive)setError(e.message||'QA fetch failed')}).finally(()=>{if(alive)setLoading(false)});
  return ()=>{alive=false};
 },[authFetch,siteId,roverId,timeRange,limit,revision]);
 const counts=useMemo(()=>rows?rows.reduce((a,r)=>(a[r.rtklib_quality]=(a[r.rtklib_quality]||0)+1,a),{}):{},[rows]);
 return <section className="panel ppk-qa-section" aria-label="Experimental PPK QA charts">
   <div className="ppk-card-head"><div><h2>Experimental PPK engine QA — auto-loaded from QA API</h2><span>Source: persisted experimental QA only · BASE provisional SPP · unvalidated · bukan displacement</span></div></div>
   <p className="ppk-qa-hint">Applied: {siteId} · {roverId||'All QA rovers'} · {timeRange==='all'?'All available':timeRange} · limit {limit}. Times in GPST (UTC = GPST − 18 s for this session).</p>
   {error && <p role="alert">QA API: {error}</p>}
   {loading && <p className="ppk-qa-hint">Memuat hasil QA dari API…</p>}{!loading && !error && (!rows || rows.length===0) && <p className="ppk-qa-hint">Tidak ada hasil PPK QA untuk Site, Rover, dan Time Range terpilih.</p>}
   {rows && rows.length>0 && <>
      <p className="ppk-qa-hint">{rows.length} epoch · API persisted · reference_type=PROVISIONAL_SPP · validation_status=unvalidated</p>
      <div className="ppk-qa-counts">{[1,2,5].map(q=><div key={q}><span>{LABELS[q]}</span><strong>{counts[q]||0}</strong></div>)}</div>
      <div className="ppk-qa-stacked" aria-label="PPK quality distribution">{[1,2,5].map(q=><span key={q} style={{width:`${((counts[q]||0)/rows.length)*100}%`,background:COLORS[q]}} title={`${LABELS[q]} ${counts[q]||0}`} />)}</div>
      <h3>Solution quality timeline</h3><div className="ppk-qa-timeline"><svg viewBox="0 0 800 72" role="img" aria-label="FIX FLOAT SINGLE across GPS epoch" preserveAspectRatio="none">{rows.map((r,i)=><circle key={i} cx={15+(r.epoch-rows[0].epoch)/((rows[rows.length-1].epoch-rows[0].epoch)||1)*770} cy={{1:13,2:35,5:57}[r.rtklib_quality]} r="2.4" fill={COLORS[r.rtklib_quality]}><title>{`GPS ${r.gps_week}/${r.gps_tow_s} · ${LABELS[r.rtklib_quality]}`}</title></circle>)}</svg><div className="ppk-qa-legend">FIX · top / FLOAT · middle / SINGLE · bottom</div></div>
      <h3>Experimental position & uncertainty</h3><p className="ppk-qa-hint">Absolute WGS84 ellipsoidal estimates, not displacement. Spread mixes FIX, FLOAT, and SINGLE; no RMSE or accuracy claim.</p>
      <div className="ppk-qa-series-grid"><Scatter rows={rows} field="latitude_deg" label="Latitude (°)"/><Scatter rows={rows} field="longitude_deg" label="Longitude (°)"/><Scatter rows={rows} field="ellipsoidal_height_m" label="Height ellipsoidal (m)"/><Scatter rows={rows} field="sdn_m" label="RTKLIB SD North (m)"/><Scatter rows={rows} field="sde_m" label="RTKLIB SD East (m)"/><Scatter rows={rows} field="sdu_m" label="RTKLIB SD Up (m)"/></div>
      <p className="ppk-qa-hint">SD adalah ketidakpastian formal keluaran solver, bukan akurasi yang dibuktikan survei. Setiap seri mempertahankan gap pada sumbu GPS time.</p>
   </>}
 </section>;
}
