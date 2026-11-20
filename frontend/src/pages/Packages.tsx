import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';

export default function Packages() {
  const [packages, setPackages] = useState<any[]>([]);

  useEffect(() => {
    api.listPackages().then(setPackages).catch(() => {});
  }, []);

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title">Packages</div>
        <Link to="/packages/new" className="btn btn-primary">+ Create Package</Link>
      </div>

      <div className="card">
        {packages.length === 0 ? (
          <div className="empty">No packages yet.<br />Create one to get started.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Name</th><th>Version</th><th>Module</th><th>Size</th><th>Created</th>
              </tr>
            </thead>
            <tbody>
              {packages.map((p) => (
                <tr key={p.id}>
                  <td style={{ color: 'var(--text-pri)', fontWeight: 500 }}>{p.name}</td>
                  <td className="mono">{p.version}</td>
                  <td className="mono muted">{p.module_name}</td>
                  <td className="muted">{formatSize(p.file_size)}</td>
                  <td className="muted">{p.created_at ? new Date(p.created_at).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (!bytes && bytes !== 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
