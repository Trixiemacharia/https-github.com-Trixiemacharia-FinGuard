import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Check, CheckCircle2, Clock3, Loader2, LogOut, Mail, ShieldCheck, UserPlus, WifiOff, XCircle } from 'lucide-react';
import { authApi, onboardingApi } from '../api/services.js';
import { GoogleButton } from '../components/GoogleButton.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { DetailsStep } from './onboarding/DetailsStep.jsx';
import { CameraCheck, ConsentPanel, OutcomePanel, PhotoUpload } from './onboarding/IdentityStep.jsx';
import './onboarding/onboarding.css';

// Only the random session id is kept in this tab (never images): progress survives a reload or a lost connection.
const TOKEN_KEY = 'finguard.onboarding';
const STAGES = [['email', 'Email verification'], ['identity', 'Identity verification'], ['details', 'Personal details'], ['create_account', 'Account creation']];
const readToken = () => { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } };
const writeToken = (token) => { try { if (token) sessionStorage.setItem(TOKEN_KEY, token); else sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ } };

function Stepper({ stage }) {
  const current = STAGES.findIndex(([key]) => key === stage);
  return <ol className="ob-stepper" aria-label="Sign-up progress">{STAGES.map(([key, label], i) => {
    const status = i < current || stage === 'completed' ? 'done' : i === current ? 'current' : 'upcoming';
    return <li key={key} className={status} aria-current={status === 'current' ? 'step' : undefined}>
      <span className="dot">{status === 'done' ? <Check size={13} /> : i + 1}</span><span className="label">{label}</span>
    </li>;
  })}</ol>;
}

function Frame({ stage, children }) {
  return <div className="ob-page">
    <aside className="ob-rail">
      <Link to="/" className="ob-brand"><span className="ob-brand-mark"><ShieldCheck size={17} /></span><span>fin<span>guard</span></span></Link>
      <h1>Open your FinGuard account</h1>
      <p>Four short steps. Your progress is saved as you go.</p>
      {stage && <Stepper stage={stage} />}
      <p className="ob-rail-foot"><ShieldCheck size={13} /> Verification runs on FinGuard’s servers. Nothing on your device decides the result.</p>
    </aside>
    <main className="ob-main"><div className="ob-content">{children}</div></main>
  </div>;
}

// --- step 1: Google ---------------------------------------------------------------------------------------------------

function EmailStep({ onVerified, resuming, notice }) {
  const [config, setConfig] = useState(null); const [error, setError] = useState(null); const [busy, setBusy] = useState(false);
  const loadNonce = useCallback(async () => {
    try { const { data } = await onboardingApi.nonce(); setConfig(data); }
    catch (e) { setError({ code: e.data?.code || (e.status === 0 ? 'offline' : 'error'), detail: e.data?.detail || e.message }); }
  }, []);
  useEffect(() => { loadNonce(); }, [loadNonce]);
  async function onCredential(credential) {
    setBusy(true); setError(null);
    try { const { data } = await onboardingApi.google(credential, config.nonce); onVerified(data); }
    catch (e) { setError({ code: e.data?.code || 'error', detail: e.data?.detail || e.message, login: e.data?.login_method }); setConfig(null); loadNonce(); }
    finally { setBusy(false); }
  }
  return <div className="ob-panel">
    <span className="ob-step-icon"><Mail size={20} /></span>
    <h2>{resuming ? 'Confirm your email to finish setting up' : 'Verify your email with Google'}</h2>
    <p className="ob-lead">We use your Google account to confirm your email address. Google tells us only your name, email and whether Google has verified it. No account is created until every step is complete.</p>
    {notice && <div className="ob-alert info"><Clock3 size={16} /><div><strong>{notice}</strong></div></div>}
    {busy ? <p className="ob-working"><Loader2 size={16} className="ob-spin" /> Verifying with Google…</p>
      : config ? <GoogleButton clientId={config.client_id} nonce={config.nonce} onCredential={onCredential}
        onLoadError={() => setError({ code: 'offline', detail: 'Google sign-in couldn’t load. Check your connection and try again.' })} />
        : !error && <p className="ob-working"><Loader2 size={16} className="ob-spin" /> Connecting to Google…</p>}
    {error && <div className={`ob-alert ${error.code === 'existing_account' ? 'info' : 'error'}`} role="alert">
      {error.code === 'offline' ? <WifiOff size={16} /> : <XCircle size={16} />}
      <div><strong>{error.detail}</strong>
        {error.code === 'existing_account' && <Link to="/auth?mode=login" className="ob-link">Sign in to your account</Link>}
        {['offline', 'error', 'google_not_configured'].includes(error.code) && <button className="ob-link" onClick={() => { setError(null); loadNonce(); }}>Try again</button>}
      </div></div>}
    <p className="ob-muted">If you closed the Google window, just choose the button again.</p>
    {!resuming && <p className="ob-muted">Already have an account? <Link to="/auth?mode=login" className="ob-link">Sign in</Link></p>}
  </div>;
}

// --- step 2: identity --------------------------------------------------------------------------------------------------

function IdentityStage({ token, state, onState }) {
  const [busy, setBusy] = useState(false); const [result, setResult] = useState(null); const [changePhoto, setChangePhoto] = useState(false);
  const identity = state.identity;
  if (!state.consent_given) {
    return <ConsentPanel busy={busy} onAccept={async () => { setBusy(true); try { onState((await onboardingApi.consent(token)).data); } finally { setBusy(false); } }} />;
  }
  if (result) {
    return <>
      <OutcomePanel result={result} onRetry={() => { setResult(null); if (result.state) onState(result.state); }} />
      {['VERIFIED', 'MANUAL_REVIEW'].includes(result.outcome) && <button className="ob-btn primary ob-continue" onClick={() => { onState(result.state); setResult(null); }}>Continue to personal details</button>}
    </>;
  }
  if (identity.status === 'not_started' || changePhoto) {
    return <PhotoUpload token={token} attemptsLeft={identity.photo_attempts_left} onAccepted={(data) => { setChangePhoto(false); onState(data.state); }} />;
  }
  return <CameraCheck token={token} onResult={setResult} onChangePhoto={() => setChangePhoto(true)} />;
}

// --- step 4: create account ---------------------------------------------------------------------------------------------

function CreateStep({ token, state, onCreated, onExpired }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function create() {
    setBusy(true); setError('');
    try { const { data } = await onboardingApi.complete(token); onCreated(data); }
    catch (e) {
      if (e.status === 401) { onExpired(e.data?.detail); return; }
      setError(e.status === 0 ? 'You appear to be offline. Your progress is saved; try again when you’re connected.' : e.data?.detail || e.message);
    } finally { setBusy(false); }
  }
  const d = state.details;
  return <div className="ob-panel">
    <span className="ob-step-icon"><UserPlus size={20} /></span>
    <h2>Create your account</h2>
    <p className="ob-lead">Check your details. Your account is created only when you confirm.</p>
    <dl className="ob-summary">
      <div><dt>Email</dt><dd>{state.email} <span className="ob-tag good">Verified by Google</span></dd></div>
      <div><dt>Identity</dt><dd>{state.identity.status === 'VERIFIED' ? <span className="ob-tag good">Verified</span> : <span className="ob-tag info">Pending human review</span>}</dd></div>
      <div><dt>Name</dt><dd>{d.first_name} {d.last_name}</dd></div>
      <div><dt>Phone</dt><dd>{state.phone.number} <span className="ob-tag good">Verified</span></dd></div>
      <div><dt>Address</dt><dd>{d.residential_address}, {d.town}, {d.county}</dd></div>
    </dl>
    {state.identity.status === 'MANUAL_REVIEW' && <div className="ob-alert info"><Clock3 size={16} /><div><strong>Your account will be created, but the wallet stays locked until a person confirms your identity.</strong></div></div>}
    {error && <div className="ob-alert error" role="alert"><XCircle size={16} /><div><strong>{error}</strong></div></div>}
    <button className="ob-btn primary" onClick={create} disabled={busy}>{busy ? <><Loader2 size={16} className="ob-spin" /> Creating your account…</> : 'Create my account'}</button>
  </div>;
}

// --- signed-in applicants waiting on a decision ------------------------------------------------------------------------

function StatusScreen({ status }) {
  const { logout } = useAuth(); const navigate = useNavigate();
  const [note, setNote] = useState('');
  useEffect(() => { authApi.onboarding().then(({ data }) => setNote(data.review_note || '')).catch(() => {}); }, []);
  const rejected = status === 'rejected';
  return <Frame stage="completed"><div className="ob-panel center">
    <span className={`ob-result-icon ${rejected ? 'bad' : 'info'}`}>{rejected ? <XCircle size={30} /> : <Clock3 size={30} />}</span>
    <h2>{rejected ? 'We couldn’t approve your account' : 'Your account is being reviewed'}</h2>
    <p className="ob-lead">{note || (rejected ? 'Please contact support if you think this is a mistake.' : 'Your account is set up. Your wallet unlocks as soon as the review is complete; we’ll notify you.')}</p>
    <button className="ob-btn ghost" onClick={async () => { await logout(); navigate('/'); }}><LogOut size={15} /> Sign out</button>
  </div></Frame>;
}

// --- flow --------------------------------------------------------------------------------------------------------------

export function Onboarding() {
  const { authenticated, user, acceptSession, updateOnboardingStatus } = useAuth();
  const navigate = useNavigate();
  const [token, setToken] = useState(readToken);
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(Boolean(readToken()));
  const [notice, setNotice] = useState('');
  const [offline, setOffline] = useState(false);

  const reset = useCallback((message) => { writeToken(null); setToken(null); setState(null); setNotice(message || ''); }, []);
  // Restore saved progress once on page load. Only an invalid/expired session (401) discards it; network and
  // server errors keep the session so the user can reconnect without losing completed steps.
  const restore = useCallback(async () => {
    const saved = readToken();
    if (!saved) { setLoading(false); return; }
    setLoading(true); setOffline(false);
    try { setState((await onboardingApi.state(saved)).data); }
    catch (e) { if (e?.status === 401) reset(e.data?.detail); else setOffline(true); }
    finally { setLoading(false); }
  }, [reset]);
  useEffect(() => { restore(); }, [restore]);

  const status = user?.onboarding_status;
  if (authenticated && (status === 'review_pending' || status === 'rejected')) return <StatusScreen status={status} />;

  function verified(data) {
    writeToken(data.token); setToken(data.token);
    const { token: _token, resumed: _resumed, ...rest } = data;
    setState(rest); setNotice('');
  }
  function created(data) {
    writeToken(null);
    acceptSession(data);
    updateOnboardingStatus(data.onboarding_status);
    navigate(data.onboarding_status === 'approved' ? '/overview' : '/onboarding', { replace: true });
  }
  const stage = state?.stage || 'email';

  return <Frame stage={stage === 'completed' ? 'create_account' : stage}>
    {offline && <div className="ob-alert error"><WifiOff size={16} /><div><strong>We couldn’t reach FinGuard. Your progress is saved.</strong><button className="ob-link" onClick={restore}>Reconnect</button></div></div>}
    {loading ? <p className="ob-working"><Loader2 size={16} className="ob-spin" /> Restoring your progress…</p> : <div className="ob-stage" key={stage}>
      {stage === 'email' && <EmailStep onVerified={verified} resuming={authenticated} notice={notice} />}
      {stage === 'identity' && <>
        <p className="ob-done"><CheckCircle2 size={15} /> Email verified: {state.email}</p>
        <IdentityStage token={token} state={state} onState={setState} />
      </>}
      {stage === 'details' && <DetailsStep token={token} state={state} onState={setState} />}
      {stage === 'create_account' && <CreateStep token={token} state={state} onCreated={created} onExpired={(detail) => reset(detail)} />}
    </div>}
  </Frame>;
}
