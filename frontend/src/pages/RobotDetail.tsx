import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function RobotDetail() {
  const { serial } = useParams<{ serial: string }>();
  const navigate = useNavigate();
  const [robot, setRobot] = useState<any>(null);
  const [command, setCommand] = useState('{"cmd": "reportVersion", "msgId": "1"}');
  const [commandResult, setCommandResult] = useState('');
  const [tab, setTab] = useState<'info' | 'command'>('info');

  useEffect(() => {
    if (serial) api.getRobot(serial).then(setRobot).catch(() => {});
  }, [serial]);

  const sendCommand = async () => {
    if (!serial || !command.trim()) return;
    try {
      const payload = JSON.parse(command);
      const res = await api.sendCommand(serial, payload);
      setCommandResult(JSON.stringify(res, null, 2));
    } catch (err: any) {
      setCommandResult(`Error: ${err.message}`);
    }
  };

  if (!robot) return <div className="page muted">Loading…</div>;

  return (
    <div className="page">
      <div className="page-head">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="link" onClick={() => navigate('/')}>← Fleet</span>
          <div>
            <div className="page-title mono" style={{ textTransform: 'none' }}>{robot.serial}</div>
            <div className="page-sub">{robot.nickname || 'No nickname set'}</div>
          </div>
          <span className={`item-status is-${robot.status || 'offline'}`} style={{ marginLeft: 4 }}>{robot.status}</span>
        </div>
      </div>

      <div className="subtabs">
        <button className={`subtab${tab === 'info' ? ' active' : ''}`} onClick={() => setTab('info')}>Info</button>
        <button className={`subtab${tab === 'command' ? ' active' : ''}`} onClick={() => setTab('command')}>Command</button>
      </div>

      {tab === 'info' && (
        <div className="card" style={{ maxWidth: 560 }}>
          <Row k="Serial" v={robot.serial} />
          <Row k="Model" v={robot.model || 'Unknown'} />
          <Row k="Firmware" v={robot.firmware_version || 'Unknown'} />
          <Row k="IP Address" v={robot.ip_address || 'Unknown'} />
          <Row k="Group" v={robot.group_name || 'None'} />
          <Row k="First Seen" v={robot.first_seen ? new Date(robot.first_seen).toLocaleString() : '—'} />
          <Row k="Last Seen" v={robot.last_seen ? new Date(robot.last_seen).toLocaleString() : '—'} />
        </div>
      )}

      {tab === 'command' && (
        <div style={{ maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="field">
            <span className="field-label">MQTT Command (JSON)</span>
            <textarea
              className="textarea"
              style={{ minHeight: 120 }}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder='{"cmd": "reportVersion", "msgId": "1"}'
            />
            <button
              className="btn btn-primary"
              style={{ alignSelf: 'flex-start' }}
              onClick={sendCommand}
              disabled={robot.status !== 'online'}
            >
              Send
            </button>
          </div>
          {commandResult && <pre className="code-pre">{commandResult}</pre>}
        </div>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="info-row">
      <span className="k">{k}</span>
      <span className="v mono">{v}</span>
    </div>
  );
}
