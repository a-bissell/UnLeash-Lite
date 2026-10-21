import { useRef, useState, useEffect } from 'react';
import { getToken } from '../api/client';
import { FleetSocket } from '../api/websocket';

interface Step {
  num: string;
  label: string;
  status: 'pending' | 'active' | 'done' | 'skip' | 'fail';
  detail?: string;
}

const INITIAL_STEPS: Step[] = [
  { num: '1/6', label: 'Connecting via WebRTC', status: 'pending' },
  { num: '2/6', label: 'Deploying SSH access', status: 'pending' },
  { num: '3/6', label: 'Waiting for SSH', status: 'pending' },
  { num: '4/6', label: 'Installing persistence', status: 'pending' },
  { num: '5/6', label: 'Redirecting to broker', status: 'pending' },
  { num: '6/6', label: 'Verifying enrollment', status: 'pending' },
];

interface FeedItem {
  id: number;
  time: string;
  kind: string;
  label: string;
  message: string;
}

let _seq = 0;

export default function Enroll() {
  const [robotIp, setRobotIp] = useState('192.168.123.161');
  const [aesKey, setAesKey] = useState('');
  const [password, setPassword] = useState('unleash');
  const [brokerIp, setBrokerIp] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [manual, setManual] = useState(false);
  const [skipRedirect, setSkipRedirect] = useState(false);
  const [skipPersist, setSkipPersist] = useState(false);

  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>(INITIAL_STEPS);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [result, setResult] = useState<{ serial?: string; ssh?: string; dashboard?: string } | null>(null);

  const feedRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<FleetSocket | null>(null);

  const push = (kind: string, label: string, message: string) =>
    setFeed((prev) => [
      ...prev.slice(-199),
      { id: _seq++, time: nowTime(), kind, label, message },
    ]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [feed]);

  useEffect(() => {
    return () => { wsRef.current?.disconnect(); };
  }, []);

  const startEnroll = async () => {
    setRunning(true);
    setResult(null);
    setSteps(INITIAL_STEPS);
    setFeed([]);
    push('system', 'ENROLL', `Starting enrollment for ${robotIp}...`);

    wsRef.current?.disconnect();
    const ws = new FleetSocket();
    wsRef.current = ws;
    ws.connect('/ws/enroll');
    ws.onMessage((ev) => {
      if (!ev) return;

      if (ev.type === 'step') {
        setSteps((prev) =>
          prev.map((s) =>
            s.num === ev.step ? { ...s, status: ev.status, detail: ev.detail || s.detail } : s
          )
        );
        const kind = ev.status === 'fail' ? 'error' : ev.status === 'done' ? 'success' : 'stage';
        push(kind, `[${ev.step}]`, ev.detail || ev.label || '');
      } else if (ev.type === 'feed') {
        push(ev.badge || 'system', ev.label || 'ENROLL', ev.message);
      } else if (ev.type === 'complete') {
        setRunning(false);
        setResult(ev.result || {});
        push('success', 'DONE', 'Enrollment complete');
      } else if (ev.type === 'error') {
        setRunning(false);
        push('error', 'ERROR', ev.message || 'Enrollment failed');
      }
    });

    try {
      const token = getToken();
      const res = await fetch('/api/v1/enroll/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          robot_ip: robotIp,
          aes_key: aesKey || null,
          password,
          broker_ip: brokerIp || null,
          manual_trigger: manual,
          skip_redirect: skipRedirect,
          skip_persist: skipPersist,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        push('error', 'ERROR', err.detail || 'Failed to start enrollment');
        setRunning(false);
      }
    } catch (e: any) {
      push('error', 'ERROR', `Connection error: ${e.message}`);
      setRunning(false);
    }
  };

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', gap: 0, padding: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* Left: config + steps */}
        <div style={{ width: 360, flexShrink: 0, borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="panel-head"><span>Enrollment</span></div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="field">
              <span className="field-label">Robot IP</span>
              <input className="input" value={robotIp} onChange={(e) => setRobotIp(e.target.value)}
                placeholder="192.168.123.161" disabled={running} />
            </div>
            <div className="field">
              <span className="field-label">AES Key (firmware &ge; 1.1.15)</span>
              <input className="input" value={aesKey} onChange={(e) => setAesKey(e.target.value)}
                placeholder="32 hex chars (optional)" disabled={running} />
            </div>
            <div className="field">
              <span className="field-label">Root Password</span>
              <input className="input" value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="unleash" disabled={running} />
            </div>

            <button className="link" style={{ fontSize: 11, alignSelf: 'flex-start' }}
              onClick={() => setShowAdvanced(!showAdvanced)}>
              {showAdvanced ? '▾ Hide advanced' : '▸ Advanced options'}
            </button>

            {showAdvanced && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div className="field">
                  <span className="field-label">Broker IP (auto-detect)</span>
                  <input className="input" value={brokerIp} onChange={(e) => setBrokerIp(e.target.value)}
                    placeholder="auto" disabled={running} />
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-body)', cursor: 'pointer' }}>
                  <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} disabled={running} />
                  Manual trigger (press controller hotkey)
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-body)', cursor: 'pointer' }}>
                  <input type="checkbox" checked={skipRedirect} onChange={(e) => setSkipRedirect(e.target.checked)} disabled={running} />
                  Skip MQTT redirect
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-body)', cursor: 'pointer' }}>
                  <input type="checkbox" checked={skipPersist} onChange={(e) => setSkipPersist(e.target.checked)} disabled={running} />
                  Skip persistence install
                </label>
              </div>
            )}

            <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '10px' }}
              onClick={startEnroll} disabled={running || !robotIp.trim()}>
              {running ? 'Enrolling…' : 'Start Enrollment'}
            </button>

            {/* Step progress */}
            <div style={{ marginTop: 8 }}>
              <div className="cmd-label" style={{ marginBottom: 8 }}>Progress</div>
              {steps.map((s) => (
                <div key={s.num} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', fontSize: 12 }}>
                  <StepIcon status={s.status} />
                  <span style={{ color: s.status === 'active' ? 'var(--accent)' : s.status === 'fail' ? 'var(--red)' : 'var(--text-body)' }}>
                    [{s.num}] {s.label}
                  </span>
                  {s.status === 'skip' && <span className="muted" style={{ fontSize: 10 }}>skipped</span>}
                </div>
              ))}
            </div>

            {/* Result card */}
            {result && (
              <div className="card" style={{ marginTop: 8 }}>
                {result.serial && (
                  <div className="info-row"><span className="k">Serial</span><span className="v mono">{result.serial}</span></div>
                )}
                {result.ssh && (
                  <div className="info-row"><span className="k">SSH</span><span className="v mono">{result.ssh}</span></div>
                )}
                {result.dashboard && (
                  <div className="info-row"><span className="k">Dashboard</span><span className="v mono">{result.dashboard}</span></div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right: live feed */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="panel-head">
            <span>Live Feed</span>
            <button className="btn btn-ghost" style={{ padding: '2px 8px', fontSize: 10 }}
              onClick={() => setFeed([])}>Clear</button>
          </div>
          <div className="feed" ref={feedRef} style={{ flex: 1 }}>
            {feed.length === 0 ? (
              <div className="empty">Start an enrollment to see live progress…</div>
            ) : feed.map((f) => (
              <div className="entry entry-new" key={f.id}>
                <div className="entry-time">{f.time}</div>
                <div className={`badge b-${f.kind}`}>{f.label}</div>
                <div className="entry-body">{f.message}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function StepIcon({ status }: { status: string }) {
  const s: Record<string, { color: string; char: string }> = {
    pending: { color: 'var(--text-dim)', char: '○' },
    active: { color: 'var(--accent)', char: '◉' },
    done: { color: 'var(--green)', char: '✓' },
    skip: { color: 'var(--text-muted)', char: '–' },
    fail: { color: 'var(--red)', char: '✗' },
  };
  const { color, char } = s[status] || s.pending;
  return <span style={{ color, fontWeight: 600, width: 14, textAlign: 'center' }}>{char}</span>;
}

function nowTime(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
