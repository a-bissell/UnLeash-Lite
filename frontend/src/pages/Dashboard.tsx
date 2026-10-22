import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { FleetSocket } from '../api/websocket';

interface FeedItem {
  id: number;
  time: string;
  kind: string;   // badge class suffix: success | error | message | system | task | warning
  label: string;
  message: string;
}

const STATUS_BADGE: Record<string, string> = {
  online: 'ib-green', offline: 'ib-gray', updating: 'ib-blue', error: 'ib-red',
};

let _feedSeq = 0;

export default function Dashboard() {
  const navigate = useNavigate();
  const [status, setStatus] = useState({ total: 0, online: 0, offline: 0, updating: 0, error: 0 });
  const [robots, setRobots] = useState<any[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [target, setTarget] = useState('*');
  const [cmdType, setCmdType] = useState('reportVersion');
  const [cmdInput, setCmdInput] = useState('');
  const feedRef = useRef<HTMLDivElement>(null);

  const push = (kind: string, label: string, message: string) =>
    setFeed((prev) => [
      ...prev.slice(-199),
      { id: _feedSeq++, time: nowTime(), kind, label, message },
    ]);

  const refresh = async () => {
    try {
      const [s, r] = await Promise.all([api.fleetStatus(), api.listRobots()]);
      setStatus(s);
      setRobots(r);
    } catch {}
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);

    const ws = new FleetSocket();
    ws.connect('/ws/events');
    ws.onMessage((ev) => {
      if (ev?.type === 'connect') push('success', 'CONNECT', `${ev.serial} joined the fleet`);
      else if (ev?.type === 'disconnect') push('error', 'DISCONNECT', `${ev.serial} left the fleet`);
      else if (ev?.type === 'message') push('message', 'MSG', `${ev.serial} · ${ev.topic ?? ''}`);
      refresh();
    });

    push('system', 'SYSTEM', 'Console connected');
    return () => { clearInterval(interval); ws.disconnect(); };
  }, []);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [feed]);

  const onTypeChange = (t: string) => {
    setCmdType(t);
    if (t === 'reportVersion') setCmdInput('{"cmd": "reportVersion", "msgId": "1"}');
    else setCmdInput('');
  };

  const send = async () => {
    let payload: any;
    try {
      payload = JSON.parse(cmdInput.trim() || '{}');
    } catch {
      push('error', 'ERROR', 'Command must be valid JSON');
      return;
    }
    const dest = target === '*' ? 'ALL' : target;
    try {
      if (target === '*') await api.broadcast(payload);
      else await api.sendCommand(target, payload);
      push('task', 'CMD', `${payload.cmd ?? 'command'} → ${dest}`);
      setCmdInput(cmdType === 'reportVersion' ? '{"cmd": "reportVersion", "msgId": "1"}' : '');
    } catch (e: any) {
      push('error', 'ERROR', e.message || 'Send failed');
    }
  };

  return (
    <>
      <div className="stats">
        <Stat v={status.total} l="Total" cls="hl" />
        <Stat v={status.online} l="Online" cls="ok" />
        <Stat v={status.offline} l="Offline" cls="" />
        <Stat v={status.updating} l="Updating" cls="warn" />
        <Stat v={status.error} l="Error" cls="bad" />
      </div>

      <div className="main">
        {/* Live event feed */}
        <div className="feed-panel">
          <div className="panel-head">
            <span>Live feed</span>
            <button className="btn btn-ghost" style={{ padding: '2px 8px', fontSize: 10 }} onClick={() => setFeed([])}>Clear</button>
          </div>
          <div className="feed" ref={feedRef}>
            {feed.length === 0 ? (
              <div className="empty">Waiting for events…</div>
            ) : feed.map((f) => (
              <div className="entry entry-new" key={f.id}>
                <div className="entry-time">{f.time}</div>
                <div className={`badge b-${f.kind}`}>{f.label}</div>
                <div className="entry-body">{f.message}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Robots + command panel */}
        <div className="sidebar">
          <div className="panel-head"><span>Robots</span><span>{robots.length}</span></div>
          <div className="item-list">
            {robots.length === 0 ? (
              <div className="empty">No robots connected.<br />Point a robot's MQTT DNS at this server.</div>
            ) : robots.map((r) => (
              <div className="item" key={r.serial} onClick={() => navigate(`/robot/${r.serial}`)}>
                <div className={`item-badge ${STATUS_BADGE[r.status] || 'ib-gray'}`}>
                  {(r.status || '?')[0].toUpperCase()}
                </div>
                <div className="item-info">
                  <div className="item-title">{r.nickname || r.serial}</div>
                  <div className="item-meta">{r.ip_address || '—'} · {r.last_seen ? timeAgo(r.last_seen) : 'never'}</div>
                </div>
                <span className={`item-status is-${r.status || 'offline'}`}>{r.status}</span>
              </div>
            ))}
          </div>

          <div className="cmd-panel">
            <div className="cmd-label">Command</div>
            <div className="cmd-row">
              <select className="cmd-sel" value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="*">All robots</option>
                {robots.map((r) => <option key={r.serial} value={r.serial}>{r.nickname || r.serial}</option>)}
              </select>
              <select className="cmd-sel" value={cmdType} onChange={(e) => onTypeChange(e.target.value)}>
                <option value="reportVersion">reportVersion</option>
                <option value="custom">Custom JSON</option>
              </select>
            </div>
            <div className="cmd-row">
              <input
                className="cmd-input"
                placeholder='{"cmd": "..."}'
                value={cmdInput}
                onChange={(e) => setCmdInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
              />
              <button className="btn btn-primary" style={{ padding: '6px 16px' }} onClick={send}>Send</button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function Stat({ v, l, cls }: { v: number; l: string; cls: string }) {
  return (
    <div className="stat">
      <div className={`stat-v ${cls}`}>{v}</div>
      <div className="stat-l">{l}</div>
    </div>
  );
}

function nowTime(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
