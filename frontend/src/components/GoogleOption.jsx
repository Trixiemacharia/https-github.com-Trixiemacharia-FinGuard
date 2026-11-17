import { useCallback, useEffect, useState } from 'react';
import { authApi } from '../api/services.js';
import { GoogleButton } from './GoogleButton.jsx';
import '../pages/onboarding/identity.css';

/**
 * "or continue with Google" under an existing form. Fetches a single-use nonce for every attempt.
 * Renders nothing when Google sign-in isn't configured on the server, so existing layouts stay unchanged.
 */
export function GoogleOption({ label, text = 'continue_with', onCredential, centered = false }) {
  const [config, setConfig] = useState(null); const [busy, setBusy] = useState(false);
  const load = useCallback(() => authApi.googleNonce().then(({ data }) => setConfig(data.client_id ? data : null)).catch(() => setConfig(null)), []);
  useEffect(() => { load(); }, [load]);
  if (!config) return null;
  async function handle(credential) {
    setBusy(true);
    try { await onCredential(credential, config.nonce); }
    finally { setBusy(false); setConfig(null); load(); } // nonces are single-use
  }
  return <div className={`google-option ${centered ? 'centered' : ''}`}>
    <div className="google-option-divider"><span>{label}</span></div>
    {busy ? <span className="ob-muted">Verifying with Google…</span>
      : <GoogleButton clientId={config.client_id} nonce={config.nonce} text={text} onCredential={handle} />}
  </div>;
}
