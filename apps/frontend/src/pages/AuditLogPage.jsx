// Halaman Audit Log — GET /api/v1/audit-log, dengan filter (action/actor)
// dan paging offset-based sungguhan (2026-09-20, revisi — sebelumnya cuma
// limit=100 tanpa filter/paging).

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function AuditLogPage() {
  const { authFetch } = useAuth();
  const navigate = useNavigate();
  const [entries, setEntries] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [actionFilter, setActionFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({ limit: pageSize, offset: page * pageSize });
    if (actionFilter) params.set("action", actionFilter);
    if (actorFilter) params.set("actor_email", actorFilter);
    authFetch(`/api/v1/audit-log?${params}`)
      .then((r) => r.json())
      .then((body) => { if (alive) { setEntries(body.entries || []); setTotal(body.total || 0); } })
      .catch((e) => alive && setError(String(e)));
    return () => { alive = false; };
  }, [authFetch, page, pageSize, actionFilter, actorFilter]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate("/")}>← Back</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Audit Log</h1>
      </div>

      <div className="panel" style={{ maxWidth: 1100, margin: "0 auto", padding: 20 }}>
        <div className="table-filters">
          <input placeholder="Filter aksi (mis. login, blast)" value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(0); }} />
          <input placeholder="Filter email pelaku" value={actorFilter}
            onChange={(e) => { setActorFilter(e.target.value); setPage(0); }} />
          <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}>
            {[10, 25, 50, 100, 500].map((n) => <option key={n} value={n}>{n} / halaman</option>)}
          </select>
          <span className="table-total">{total} total entri</span>
        </div>

        {error && <div className="admin-error">{error}</div>}
        {!entries && !error && <div className="loading">Loading…</div>}
        {entries && entries.length === 0 && <div className="sc-row">No matching log entries.</div>}
        {entries && entries.length > 0 && (
          <>
            <table className="devtable">
              <thead>
                <tr><th>Time</th><th>Actions</th><th>Target</th><th>By</th></tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id}>
                    <td>{new Date(e.occurred_at).toLocaleString("id-ID")}</td>
                    <td><code>{e.action}</code></td>
                    <td>{e.target_type}: {e.target_id}</td>
                    <td>{e.actor_email || "(sistem/device)"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="table-pager">
              <button className="admin-btn" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>← Previous</button>
              <span>Halaman {page + 1} dari {totalPages}</span>
              <button className="admin-btn" onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}>Berikutnya →</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
