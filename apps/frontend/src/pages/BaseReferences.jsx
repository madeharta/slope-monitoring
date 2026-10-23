import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { roleSatisfies, useAuth } from '../context/AuthContext.jsx';
import './base-references.css';

const API = '/api/v1/base-references/versions';
const format = v => v ? new Date(v).toLocaleString('en-GB', { timeZone: 'Asia/Jakarta', timeZoneName: 'short' }) : '—';
const localNow = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const initial = () => ({ latitude_deg: '', longitude_deg: '', ellipsoidal_height_m: '', evidence_type: 'PROVISIONAL_SPP', effective_from: localNow(), note: '' });

export default function BaseReferences() {
  const { auth, authFetch } = useAuth();
  const canWrite = roleSatisfies(auth?.role, 'operator');
  const [devices, setDevices] = useState([]);
  const [devicesError, setDevicesError] = useState('');
  const [siteId, setSiteId] = useState('ITB-STAGING-01');
  const [baseId, setBaseId] = useState('BASE-01');
  const [query, setQuery] = useState({ site_id: 'ITB-STAGING-01', base_device_id: 'BASE-01' });
  const [draft, setDraft] = useState(initial);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const siteOptions = [...new Set(devices.map(d => d.site_id).filter(Boolean))].sort();
  const baseDevices = devices.filter(d => d.site_id === siteId && (/base/i.test(d.device_type || '') || /^base/i.test(d.device_id || '')));
  const update = (key, value) => setDraft(d => ({ ...d, [key]: value }));
  useEffect(() => {
    let active = true;
    authFetch('/api/v1/devices').then(async r => {
      const body = await r.json().catch(() => ({}));
      if (!r.ok || !Array.isArray(body.devices)) throw new Error(body.detail || `Device list unavailable (HTTP ${r.status})`);
      return body.devices;
    }).then(rows => {
      if (!active) return;
      setDevices(rows);
      setDevicesError('');
      const sites = [...new Set(rows.map(d => d.site_id).filter(Boolean))];
      setSiteId(current => sites.includes(current) ? current : (sites[0] || ''));
    }).catch(e => { if (active) setDevicesError(String(e.message || e)); });
    return () => { active = false; };
  }, [authFetch]);
  useEffect(() => {
    const options = devices.filter(d => d.site_id === siteId && (/base/i.test(d.device_type || '') || /^base/i.test(d.device_id || '')));
    if (devices.length) setBaseId(current => options.some(d => d.device_id === current) ? current : (options[0]?.device_id || ''));
  }, [devices, siteId]);
  const reload = useCallback(() => setRevision(n => n + 1), []);

  useEffect(() => {
    const ctrl = new AbortController();
    let active = true;
    setLoading(true); setError('');
    const qs = new URLSearchParams(query);
    authFetch(`${API}?${qs}`, { signal: ctrl.signal })
      .then(async response => { const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(response.status === 404 ? 'BASE history API unavailable (HTTP 404). Check backend routing and the Vite API proxy.' : (body.detail || `History request failed (HTTP ${response.status})`)); if (body.ok !== true || body.operational_displacement_approved !== false || !Array.isArray(body.versions)) throw new Error('BASE history API contract mismatch'); return body.versions; })
      .then(v => { if (active) setVersions(v); })
      .catch(e => { if (active && e.name !== 'AbortError') setError(String(e.message || e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; ctrl.abort(); };
  }, [authFetch, query, revision]);

  const submit = async e => {
    e.preventDefault();
    if (!canWrite || submitting) return;
    setError(''); setNotice('');
    const lat = Number(draft.latitude_deg), lon = Number(draft.longitude_deg), height = Number(draft.ellipsoidal_height_m);
    if (![lat,lon,height].every(Number.isFinite) || draft.latitude_deg === '' || draft.longitude_deg === '' || draft.ellipsoidal_height_m === '' || lat < -90 || lat > 90 || lon < -180 || lon > 180) { setError('Invalid coordinates. Latitude must be −90 to 90°, longitude −180 to 180°, and height must be numeric.'); return; }
    const parsed = new Date(draft.effective_from);
    if (!Number.isFinite(parsed.getTime())) { setError('Invalid effective date and time.'); return; }
    if (!window.confirm(`Save a NEW version for ${query.site_id} / ${query.base_device_id}? This version remains UNVERIFIED and is NOT used for operational displacement.`)) return;
    setSubmitting(true);
    try {
      const response = await authFetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...query, latitude_deg: lat, longitude_deg: lon, ellipsoidal_height_m: height, evidence_type: draft.evidence_type, effective_from: parsed.toISOString(), note: draft.note }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `HTTP ${response.status}`);
      if (response.status !== 201 || result.validation_state !== 'UNVERIFIED' || result.operational_displacement_approved !== false) throw new Error('Create-version response failed safety contract validation');
      setNotice(`Version ${result.version_no} saved as UNVERIFIED. Not active for displacement.`);
      setDraft(initial()); reload();
    } catch (err) { setError(String(err.message || err)); }
    finally { setSubmitting(false); }
  };

  return <main className="base-ref-page">
    <header className="base-ref-heading"><Link to="/ppk">← PPK</Link><div><h1>BASE Reference Management</h1><p>Version-controlled BASE coordinates · WGS84 ellipsoidal · QA and administration only</p></div></header>
    <div className="base-ref-alert" role="status"><strong>UNVERIFIED / NOT OPERATIONAL</strong><span>Submitted coordinates are not automatically validated and do not replace an operational BASE reference or enable displacement monitoring or alarms. Survey-derived coordinates still require independent verification.</span></div>
    <section className="base-ref-panel"><h2>Select BASE device</h2><form className="base-ref-picker" onSubmit={e => { e.preventDefault(); if (!siteId || !baseId || !baseDevices.some(d => d.device_id === baseId)) return; setQuery({site_id: siteId, base_device_id: baseId}); }}>
      <label>Monitoring site<select aria-label="Monitoring site" value={siteId} onChange={e => setSiteId(e.target.value)} required disabled={!siteOptions.length}><option value="">Select site</option>{siteOptions.map(id => <option key={id} value={id}>{id}</option>)}</select></label>
      <label>BASE device<select aria-label="BASE device" value={baseId} onChange={e => setBaseId(e.target.value)} required disabled={!baseDevices.length}><option value="">Select BASE device</option>{baseDevices.map(d => <option key={d.device_id} value={d.device_id}>{d.label ? `${d.label} (${d.device_id})` : d.device_id}</option>)}</select></label>
      <div className="base-ref-picker-actions"><button type="submit" disabled={!siteId || !baseId || loading}>Load history</button><button type="button" onClick={reload} disabled={loading}>Refresh</button></div>
    </form>{devicesError && <p className="base-ref-error" role="alert">{devicesError}</p>}{!devicesError && !!siteId && !baseDevices.length && <p className="base-ref-caption">No BASE device is registered for this site.</p>}</section>
    {error && <p className="base-ref-error" role="alert">{error}</p>}{notice && <p className="base-ref-success" role="status">{notice}</p>}
    {canWrite ? <section className="base-ref-panel"><h2>Add BASE coordinate version</h2><p className="base-ref-caption">Operator and Admin can submit new versions; previous records are preserved. Target: {query.site_id} / {query.base_device_id}</p><form onSubmit={submit} className="base-ref-form">
      <label>Latitude (°) <input type="number" step="any" min="-90" max="90" required value={draft.latitude_deg} onChange={e=>update('latitude_deg',e.target.value)} /></label>
      <label>Longitude (°) <input type="number" step="any" min="-180" max="180" required value={draft.longitude_deg} onChange={e=>update('longitude_deg',e.target.value)} /></label>
      <label>Ellipsoidal height (m) <input type="number" step="any" required value={draft.ellipsoidal_height_m} onChange={e=>update('ellipsoidal_height_m',e.target.value)} /></label>
      <label>Coordinate source <select value={draft.evidence_type} onChange={e=>update('evidence_type',e.target.value)}><option value="PROVISIONAL_SPP">Provisional GNSS estimate (SPP)</option><option value="SURVEYED">Survey measurement</option></select><small className="base-ref-help">Provisional: estimated using GNSS and not approved for displacement. Survey: measured in the field but still requires review and approval.</small></label>
      <label>Effective from (local time) <input type="datetime-local" required value={draft.effective_from} onChange={e=>update('effective_from',e.target.value)} /></label>
      <label className="base-ref-wide">Notes / survey document reference <textarea maxLength={2000} rows={3} value={draft.note} onChange={e=>update('note',e.target.value)} placeholder="Measurement method, survey personnel, document reference, and quality notes" /></label>
      <div className="base-ref-wide"><button disabled={submitting} type="submit">{submitting ? 'Saving…' : 'Save new version (UNVERIFIED)'}</button></div>
    </form></section> : <p className="base-ref-caption" role="status">Viewer access: read-only history. Only Operator and Admin can submit coordinates.</p>}
    <section className="base-ref-panel"><h2>Version history — {query.site_id} / {query.base_device_id}</h2>{loading ? <p>Loading history…</p> : versions.length === 0 ? <p>No coordinate versions for this device.</p> : <div className="base-ref-table-wrap"><table><thead><tr><th>Version</th><th>Latitude (°)</th><th>Longitude (°)</th><th>Height ell. (m)</th><th>Source</th><th>Status</th><th>Effective from (WIB)</th><th>Submitted by</th><th>Created (WIB)</th><th>Notes</th></tr></thead><tbody>{versions.map(v => <tr key={v.id}><td>{v.version_no}</td><td>{Number(v.latitude_deg).toFixed(9)}</td><td>{Number(v.longitude_deg).toFixed(9)}</td><td>{Number(v.ellipsoidal_height_m).toFixed(4)}</td><td>{v.evidence_type === 'PROVISIONAL_SPP' ? 'Provisional GNSS (SPP)' : v.evidence_type === 'SURVEYED' ? 'Survey' : v.evidence_type}</td><td><strong>{v.validation_state}</strong></td><td>{format(v.effective_from)}</td><td>{v.created_by}</td><td>{format(v.created_at)}</td><td>{v.note || '—'}</td></tr>)}</tbody></table></div>}<p className="base-ref-caption">Showing up to 200 most recent versions. No versions are approved for operational displacement.</p></section>
  </main>;
}
