import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, setTokens } from '../api/client';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await api.login(username, password);
      setTokens(res.access_token, res.refresh_token);
      navigate('/');
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-overlay">
      <form className="login-box" onSubmit={handleSubmit}>
        <div className="logo">UN<span>LEASH</span></div>
        <input
          className="login-input"
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          className="login-input"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="err-text" style={{ textAlign: 'center' }}>{error}</div>}
        <button type="submit" className="btn btn-primary" disabled={loading} style={{ justifyContent: 'center', padding: '10px' }}>
          {loading ? 'Signing in…' : 'Access'}
        </button>
        <div className="login-sub">Own your Unitree robot</div>
      </form>
    </div>
  );
}
