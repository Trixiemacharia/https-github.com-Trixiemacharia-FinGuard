const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');
let accessToken = null;
let refreshPromise = null;

export const setAccessToken = (token) => { accessToken = token || null; };
export const clearAccessToken = () => { accessToken = null; };

function errorMessage(body, fallback) {
  if (typeof body?.detail === 'string') return body.detail;
  if (typeof body?.message === 'string') return body.message;
  if (body && typeof body === 'object') {
    return Object.entries(body).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(' ') : value}`).join(' · ');
  }
  return fallback;
}

async function refreshAccess() {
  if (!refreshPromise) {
    refreshPromise = fetch(`${BASE_URL}/auth/token/refresh/`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok || !body.access) throw new ApiError(errorMessage(body, 'Your session has expired.'), response.status, body);
        accessToken = body.access;
        return accessToken;
      }).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export const restoreSessionToken = () => refreshAccess();

export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.name = 'ApiError'; this.status = status; this.data = data; }
}

export async function api(path, options = {}) {
  const { auth = true, retryAuth = true, headers: extraHeaders = {}, ...rest } = options;
  const doFetch = () => {
    const headers = new Headers(extraHeaders);
    if (rest.body && !(rest.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    if (auth && accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
    return fetch(`${BASE_URL}${path}`, { ...rest, headers, credentials: 'include' });
  };
  let response;
  try { response = await doFetch(); }
  catch { throw new ApiError('Unable to reach FinGuard. Check your connection and try again.', 0, null); }
  if (response.status === 401 && auth && retryAuth) {
    try { await refreshAccess(); response = await doFetch(); }
    catch (error) { clearAccessToken(); throw error; }
  }
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(errorMessage(data, `Request failed (${response.status}).`), response.status, data);
  return { data, status: response.status, headers: response.headers };
}

export const request = (path, method = 'GET', body, options = {}) => api(path, {
  method,
  ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  ...options,
});

export { BASE_URL };
