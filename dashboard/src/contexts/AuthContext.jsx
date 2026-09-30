// Self-host config context: reads /api/config for the one flag that still
// varies at runtime (whether a local LLM is configured for the moment picker).
import { createContext, useContext, useState, useEffect } from 'react';
import { getApiUrl } from '../config';

const AuthContext = createContext(null);
// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [config, setConfig] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const cfg = await (await fetch(getApiUrl('/api/config'))).json();
        setConfig(cfg);
      } catch (_) { /* config fetch failed — stay on defaults */ }
      setLoading(false);
    })();
  }, []);

  const value = {
    localLlm: config.localLlm || null,
    jobRetentionSeconds: config.jobRetentionSeconds || null,
    loading,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
