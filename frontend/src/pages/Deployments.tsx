import { useEffect, useState } from 'react';
import { api } from '../api/client';

const STATUS_CLS: Record<string, string> = {
  pending: 'b-system', in_progress: 'b-message', completed: 'b-success',
  failed: 'b-fail', partial: 'b-warning',
};

function statusBadge(status: string) {
  return <span className={`badge ${STATUS_CLS[status] || 'b-system'}`}>{status}</span>;
}

export default function Deployments() {
  const [deployments, setDeployments] = useState<any[]>([]);
  const [packages, setPackages] = useState<any[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<any | null>(null);

  const pkgName = (id: string) => {
    const p = packages.find((x) => x.id === id);
    return p ? `${p.name} ${p.version}` : id.slice(0, 8);
  };

  const refresh = () => api.listDeployments().then(setDeployments).catch(() => {});

  useEffect(() => {
    refresh();
    api.listPackages().then(setPackages).catch(() => {});
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const openDetail = (id: string) => api.getDeployment(id).then(setDetail).catch(() => {});

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title">Deployments</div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ New Deployment</button>
      </div>

      <div className="card">
        {deployments.length === 0 ? (
          <div className="empty">No deployments yet.<br />Roll a package out to the fleet to get started.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>ID</th><th>Package</th><th>Target</th><th>Strategy</th><th>Status</th><th>Created</th></tr>
            </thead>
            <tbody>
              {deployments.map((d) => (
                <tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => openDetail(d.id)}>
                  <td className="mono link">{d.id.slice(0, 8)}</td>
                  <td style={{ color: 'var(--text-pri)' }}>{pkgName(d.package_id)}</td>
                  <td className="muted">{d.target_type}{d.target_value ? `: ${d.target_value}` : ''}</td>
                  <td className="muted">{d.strategy}</td>
                  <td>{statusBadge(d.status)}</td>
                  <td className="muted">{d.created_at ? new Date(d.created_at).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateModal
          packages={packages}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refresh(); }}
        />
      )}

      {detail && <DetailModal deployment={detail} pkgName={pkgName} onClose={() => setDetail(null)} />}
    </div>
  );
}

function CreateModal({ packages, onClose, onCreated }: {
  packages: any[]; onClose: () => void; onCreated: () => void;
}) {
  const [packageId, setPackageId] = useState(packages[0]?.id || '');
  const [targetType, setTargetType] = useState('all');
  const [targetValue, setTargetValue] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!packageId) { setError('Select a package'); return; }
    setSaving(true);
    setError('');
    try {
      await api.createDeployment({
        package_id: packageId,
        target_type: targetType,
        target_value: targetType === 'all' ? undefined : targetValue,
      });
      onCreated();
    } catch (e: any) {
      setError(e.message || 'Failed to create deployment');
      setSaving(false);
    }
  };

  return (
    <>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal">
        <div className="modal-head">
          <h3>New Deployment</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="field">
            <span className="field-label">Package</span>
            <select className="cmd-sel" value={packageId} onChange={(e) => setPackageId(e.target.value)}>
              {packages.length === 0 && <option value="">No packages available</option>}
              {packages.map((p) => <option key={p.id} value={p.id}>{p.name} {p.version} ({p.module_name})</option>)}
            </select>
          </div>
          <div className="field">
            <span className="field-label">Target</span>
            <select className="cmd-sel" value={targetType} onChange={(e) => setTargetType(e.target.value)}>
              <option value="all">All robots</option>
              <option value="group">Group (group id)</option>
              <option value="serial_list">Serial list</option>
            </select>
          </div>
          {targetType !== 'all' && (
            <div className="field">
              <span className="field-label">{targetType === 'group' ? 'Group ID' : 'Serials (comma-separated)'}</span>
              <input className="input" value={targetValue} onChange={(e) => setTargetValue(e.target.value)}
                placeholder={targetType === 'group' ? 'group-uuid' : 'B42D…, B42E…'} />
            </div>
          )}
          {error && <div className="err-text">{error}</div>}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>{saving ? 'Creating…' : 'Deploy'}</button>
        </div>
      </div>
    </>
  );
}

function DetailModal({ deployment, pkgName, onClose }: {
  deployment: any; pkgName: (id: string) => string; onClose: () => void;
}) {
  const targets: any[] = deployment.targets || [];
  return (
    <>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal">
        <div className="modal-head">
          <h3>Deployment {deployment.id.slice(0, 8)}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="card">
            <div className="info-row"><span className="k">Package</span><span className="v">{pkgName(deployment.package_id)}</span></div>
            <div className="info-row"><span className="k">Status</span><span className="v">{statusBadge(deployment.status)}</span></div>
            <div className="info-row"><span className="k">Target</span><span className="v">{deployment.target_type}{deployment.target_value ? `: ${deployment.target_value}` : ''}</span></div>
            <div className="info-row"><span className="k">Strategy</span><span className="v">{deployment.strategy}</span></div>
          </div>
          <div>
            <div className="cmd-label" style={{ marginBottom: 8 }}>Targets ({targets.length})</div>
            {targets.length === 0 ? (
              <div className="dim" style={{ fontSize: 11 }}>No matching robots.</div>
            ) : (
              <table className="tbl">
                <thead><tr><th>Robot</th><th>Status</th><th>Downloads</th><th>Error</th></tr></thead>
                <tbody>
                  {targets.map((t) => (
                    <tr key={t.robot_serial}>
                      <td className="mono">{t.robot_serial}</td>
                      <td>{statusBadge(t.status)}</td>
                      <td className="muted">{t.download_count}</td>
                      <td className="dim">{t.error_message || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
