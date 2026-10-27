import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { authApi } from '../api/services.js';
import { clearAccessToken, restoreSessionToken, setAccessToken } from '../api/client.js';

const AuthContext = createContext(null);
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [authenticated, setAuthenticated] = useState(false);
  const [booting, setBooting] = useState(true);
  useEffect(() => {
    let active = true;
    restoreSessionToken()
      .then((token) => { if (active && token) { setAccessToken(token); setAuthenticated(true); } })
      .catch(() => { if (active) { clearAccessToken(); setAuthenticated(false); } })
      .finally(() => { if (active) setBooting(false); });
    return () => { active = false; };
  }, []);
  const acceptSession = useCallback((data) => {
    if (data.access) setAccessToken(data.access);
    if (data.user) setUser(data.user);
    setAuthenticated(true);
  }, []);
  const logout = useCallback(async () => {
    try { await authApi.logout(); } finally { clearAccessToken(); setAuthenticated(false); setUser(null); }
  }, []);
  const value = useMemo(() => ({ user, authenticated, booting, acceptSession, logout }), [user, authenticated, booting, acceptSession, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export const useAuth = () => useContext(AuthContext);
