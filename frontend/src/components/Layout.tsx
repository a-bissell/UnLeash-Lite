import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api, clearToken } from '../api/client';
import { getTheme, toggleTheme } from '../theme';
import { Sun, Moon } from 'lucide-react';

const TABS = [
  { to: '/', label: 'Fleet', end: true },
  { to: '/enroll', label: 'Enroll', end: false },
  { to: '/packages', label: 'Packages', end: false },
  { to: '/deployments', label: 'Deployments', end: false },
  { to: '/audit', label: 'Audit', end: false },
];

export default function Layout() {
  const navigate = useNavigate();
  const [online, setOnline] = useState<number | null>(null);
  const [light, setLight] = useState(getTheme() === 'light');

  useEffect(() => {
    let alive = true;
    const poll = () =>
      api.fleetStatus().then((s) => { if (alive) setOnline(s.online); }).catch(() => {});
    poll();
    const t = setInterval(poll, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const logout = () => { clearToken(); navigate('/login'); };
  const flipTheme = () => setLight(toggleTheme() === 'light');

  const connected = online !== null;

  return (
    <div className="app">
      <div className="topbar">
        <div className="logo">UN<span>LEASH</span></div>
        <div className="top-r">
          <div className="indicators">
            <div className="ind">
              <div className={`dot ${connected ? 'dot-g' : 'dot-x'}`} />
              <span>{connected ? 'Broker online' : 'Connecting…'}</span>
            </div>
            <div className="ind">
              <div className={`dot ${online ? 'dot-a' : 'dot-x'}`} />
              <span>{online ?? 0} online</span>
            </div>
          </div>
          <div className="top-actions">
            <button className="btn btn-theme" onClick={flipTheme} title="Toggle light/dark">
              {light ? <Moon size={14} /> : <Sun size={14} />}
            </button>
            <button className="btn btn-ghost" onClick={logout}>Sign out</button>
          </div>
        </div>
      </div>

      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) => `tab${isActive ? ' active' : ''}`}
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="app-content">
        <Outlet />
      </div>

      <div className="bottombar">
        <span><span className={`live-dot${connected ? '' : ' off'}`} />Live · polling 10s</span>
        <span>{window.location.host}</span>
      </div>
    </div>
  );
}
