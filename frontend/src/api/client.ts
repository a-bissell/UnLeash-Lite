const BASE = '/api/v1';
const ACCESS_KEY = 'unleash_token';
const REFRESH_KEY = 'unleash_refresh';

export function getToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

/** Store both tokens together — always call this instead of setToken alone. */
export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

/** @deprecated Use setTokens. Kept for callers that only update the access token. */
export function setToken(token: string) {
  localStorage.setItem(ACCESS_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

// Deduplicate concurrent refresh attempts: if three requests 401 at once,
// only one POST /auth/refresh goes out and all three await the same promise.
let _refreshPromise: Promise<string | null> | null = null;

async function tryRefresh(): Promise<string | null> {
  const rt = getRefreshToken();
  if (!rt) return null;

  if (!_refreshPromise) {
    _refreshPromise = fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
      .then(r => (r.ok ? r.json() : null))
      .then((data: { access_token: string; refresh_token: string } | null) => {
        if (data?.access_token) {
          setTokens(data.access_token, data.refresh_token);
          return data.access_token;
        }
        return null;
      })
      .catch(() => null)
      .finally(() => { _refreshPromise = null; });
  }

  return _refreshPromise;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 204) return {} as T;
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    const newToken = await tryRefresh();
    if (newToken) {
      const retryHeaders = { ...headers, 'Authorization': `Bearer ${newToken}` };
      const retryRes = await fetch(`${BASE}${path}`, { ...options, headers: retryHeaders });
      if (retryRes.status !== 401) return handleResponse<T>(retryRes);
    }
    clearToken();
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  return handleResponse<T>(res);
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<{ username: string; role: string }>('/auth/me'),
  fleetStatus: () => request<{ total: number; online: number; offline: number; updating: number; error: number }>('/fleet/status'),
  listRobots: () => request<any[]>('/fleet/robots'),
  getRobot: (serial: string) => request<any>(`/fleet/robots/${serial}`),
  updateRobot: (serial: string, data: any) => request<any>(`/fleet/robots/${serial}`, { method: 'PUT', body: JSON.stringify(data) }),
  listGroups: () => request<any[]>('/fleet/groups'),
  createGroup: (name: string, description?: string) => request<any>('/fleet/groups', { method: 'POST', body: JSON.stringify({ name, description }) }),
  sendCommand: (serial: string, payload: any) => request<any>(`/command/${serial}`, { method: 'POST', body: JSON.stringify({ payload }) }),
  broadcast: (payload: any) => request<any>('/command/broadcast', { method: 'POST', body: JSON.stringify({ payload }) }),
  listPackages: () => request<any[]>('/packages'),
  packageTemplates: () => request<any[]>('/packages/templates'),
  createPackage: (data: any) => request<any>('/packages', { method: 'POST', body: JSON.stringify(data) }),
  listDeployments: () => request<any[]>('/deployments'),
  getDeployment: (id: string) => request<any>(`/deployments/${id}`),
  createDeployment: (data: { package_id: string; target_type: string; target_value?: string; strategy?: string }) =>
    request<any>('/deployments', { method: 'POST', body: JSON.stringify(data) }),
  auditLogs: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<{ items: any[]; total: number; page: number; page_size: number }>(`/audit/logs${qs}`);
  },
  systemStatus: () => request<any>('/system/status'),
};
