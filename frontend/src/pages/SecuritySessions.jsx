import { useCallback, useEffect, useState } from 'react';
import { MonitorSmartphone, RefreshCw, ShieldCheck } from 'lucide-react';
import { authApi } from '../api/services.js';
import { Empty, ErrorState, Loading, PageTitle } from '../components/Feedback.jsx';
import { formatWhen } from '../utils/format.js';

export function SecuritySessions() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const { data } = await authApi.sessions(); setSessions(data.sessions || []); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  async function revoke(jti) {
    setBusy(jti); setError('');
    try { const { data } = await authApi.revokeSession(jti); setMessage(data.detail); await load(); }
    catch (e) { setError(e.message); }
    finally { setBusy(''); }
  }
  return <><PageTitle eyebrow="ACCOUNT PROTECTION" title="Devices & sessions" detail="Review active sign-in sessions and revoke access you no longer recognise." action={<button className="icon-text-button" onClick={load}><RefreshCw size={14} /> Refresh</button>} />
    {message && <div className="success-banner"><ShieldCheck size={16} /> {message}<button onClick={() => setMessage('')} aria-label="Dismiss">×</button></div>}
    {loading ? <Loading label="Loading sessions" /> : error ? <ErrorState error={error} onRetry={load} /> : sessions.length === 0 ? <Empty title="No active sessions found" detail="Your active sign-in sessions will appear here." /> : <div className="beneficiary-grid">{sessions.map((session) => <article className="beneficiary-card" key={session.jti}><div className="beneficiary-avatar"><MonitorSmartphone size={18} /></div><div className="beneficiary-info"><strong>{session.current ? 'This session' : 'Signed-in session'}</strong><span>Started {formatWhen(session.created_at)}</span><small>Expires {formatWhen(session.expires_at)}</small></div>{!session.current && <button className="secondary-button" disabled={busy === session.jti} onClick={() => revoke(session.jti)}>{busy === session.jti ? 'Revoking…' : 'Revoke'}</button>}</article>)}</div>}
    <div className="notice-card"><ShieldCheck size={18} /><div><strong>Session details are private</strong><p>Only sessions created for your account are listed. Device and network details are not collected by this backend.</p></div></div>
  </>;
}
