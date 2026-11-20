import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function AuditLog() {
  const [logs, setLogs] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.auditLogs({ page: String(page), page_size: '50' })
      .then((res) => { setLogs(res.items); setTotal(res.total); })
      .catch(() => {});
  }, [page]);

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title">Audit Log</div>
        <span className="page-sub">{total} total entries</span>
      </div>

      <div className="card">
        {logs.length === 0 ? (
          <div className="empty">No audit entries yet.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>Timestamp</th><th>User</th><th>Action</th><th>Target</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td className="muted">{new Date(log.timestamp).toLocaleString()}</td>
                  <td style={{ color: 'var(--text-pri)' }}>{log.username}</td>
                  <td><span className="badge b-system">{log.action}</span></td>
                  <td className="mono muted">{log.target_type ? `${log.target_type}:${log.target_id || ''}` : '—'}</td>
                  <td className="dim" style={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {log.detail_json || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {total > 50 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
          <button className="btn btn-ghost" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>Previous</button>
          <span className="muted" style={{ padding: '6px 12px' }}>Page {page}</span>
          <button className="btn btn-ghost" onClick={() => setPage((p) => p + 1)} disabled={page * 50 >= total}>Next</button>
        </div>
      )}
    </div>
  );
}
