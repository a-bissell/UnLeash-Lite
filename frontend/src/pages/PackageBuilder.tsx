import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

interface CommandEntry {
  Cmd: string;
  Delay: number;
  ExpectCode: number[];
  IgnoreUnexpected: boolean;
}

export default function PackageBuilder() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [moduleName, setModuleName] = useState('system_patch');
  const [description, setDescription] = useState('');
  const [commands, setCommands] = useState<CommandEntry[]>([
    { Cmd: '', Delay: 0, ExpectCode: [0], IgnoreUnexpected: true },
  ]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.packageTemplates().then(setTemplates).catch(() => {});
  }, []);

  const applyTemplate = (tplName: string) => {
    const t = templates.find((x) => x.name === tplName);
    if (!t) return;
    // Prefill everything except the name — the operator names their own copy
    // (and it avoids colliding with the seeded example of the same name).
    setName('');
    setVersion(t.version);
    setModuleName(t.module_name);
    setDescription(t.description);
    setCommands(t.commands.map((c: any) => ({
      Cmd: c.Cmd, Delay: c.Delay ?? 0,
      ExpectCode: c.ExpectCode ?? [0], IgnoreUnexpected: c.IgnoreUnexpected ?? true,
    })));
    setError('');
  };

  const addCommand = () => setCommands([...commands, { Cmd: '', Delay: 0, ExpectCode: [0], IgnoreUnexpected: true }]);
  const removeCommand = (i: number) => setCommands(commands.filter((_, idx) => idx !== i));
  const updateCommand = (i: number, value: string) => {
    const updated = [...commands];
    updated[i].Cmd = value;
    setCommands(updated);
  };

  const save = async () => {
    if (!name.trim()) { setError('Name is required'); return; }
    if (commands.some((c) => !c.Cmd.trim())) { setError('All commands must have content'); return; }
    setSaving(true);
    setError('');
    try {
      await api.createPackage({ name, version, description, module_name: moduleName, commands });
      navigate('/packages');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const preview = {
    Name: moduleName,
    Version: version,
    Type: 'NORMAL',
    Install: { CmdPreList: commands.filter((c) => c.Cmd.trim()), CmdPostList: [] },
  };

  return (
    <div className="page">
      <div className="page-head">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="link" onClick={() => navigate('/packages')}>← Back</span>
          <div className="page-title">Create Package</div>
        </div>
        {templates.length > 0 && (
          <select
            className="cmd-sel"
            style={{ maxWidth: 220 }}
            value=""
            onChange={(e) => applyTemplate(e.target.value)}
          >
            <option value="">Start from template…</option>
            {templates.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, maxWidth: 980 }}>
        <div className="form-grid" style={{ alignContent: 'start' }}>
          <Field label="Package Name" value={name} onChange={setName} placeholder="ssh-enable" />
          <Field label="Version" value={version} onChange={setVersion} placeholder="1.0.0" />
          <Field label="Module Name" value={moduleName} onChange={setModuleName} placeholder="system_patch" />
          <Field label="Description" value={description} onChange={setDescription} placeholder="Optional description" />

          <div className="field">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="field-label">Commands (CmdPreList)</span>
              <span className="link" style={{ fontSize: 11 }} onClick={addCommand}>+ Add</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {commands.map((cmd, i) => (
                <div key={i} className="cmd-row">
                  <input
                    className="cmd-input"
                    value={cmd.Cmd}
                    onChange={(e) => updateCommand(i, e.target.value)}
                    placeholder="echo hello > /tmp/test"
                  />
                  {commands.length > 1 && (
                    <button className="btn btn-danger" style={{ padding: '6px 10px' }} onClick={() => removeCommand(i)}>✕</button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {error && <div className="err-text">{error}</div>}

          <button className="btn btn-primary" onClick={save} disabled={saving} style={{ justifyContent: 'center', padding: '8px' }}>
            {saving ? 'Building…' : 'Build & Save'}
          </button>
        </div>

        <div className="field">
          <span className="field-label">module.json Preview</span>
          <pre className="code-pre" style={{ height: 380 }}>{JSON.stringify(preview, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}
