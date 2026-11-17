import { useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Check, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react';
import { authApi, onboardingApi } from '../api/services.js';
import { GoogleButton } from '../components/GoogleButton.jsx';
import { ApiError } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';

function AuthFrame({ children, mode }) {
  return <div className="auth-page"><section className="auth-visual"><div className="auth-brand"><div className="brand-symbol"><ShieldCheck size={19} /></div>fin<span>guard</span></div><div className="visual-orbit orbit-one" /><div className="visual-orbit orbit-two" /><div className="visual-content"><div className="visual-kicker"><Sparkles size={14} /> FINANCIAL CLARITY, BUILT IN</div><h1>Money should<br />move with <em>confidence.</em></h1><p>One secure place to keep an eye on your balance, activity, and financial wellbeing.</p><div className="visual-list"><span><Check size={15} /> Protected account access</span><span><Check size={15} /> Clear, real-time activity</span><span><Check size={15} /> Security built around you</span></div></div><div className="visual-footer"><span>FinGuard Financial Services</span><span>Secure by design <LockKeyhole size={13} /></span></div></section><section className="auth-panel"><div className="auth-panel-top"><span>Secure account access</span><span className="secure-chip"><ShieldCheck size={14} /> Encrypted</span></div><div className="auth-mode-tabs"><Link className={mode === 'register' ? 'selected' : ''} to="/onboarding">Create account</Link><Link className={mode === 'login' ? 'selected' : ''} to="/auth?mode=login">Sign in</Link></div>{children}<div className="auth-legal">By continuing, you agree to use FinGuard responsibly and keep your sign-in details private.</div></section></div>;
}

export function AuthPage() {
  const [params] = useSearchParams();
  // New accounts are created only through verified onboarding (Google email -> identity -> details).
  return params.get('mode') === 'register' ? <Navigate to="/onboarding" replace /> : <Login />;
}

function GoogleLogin({ onSession }) {
  const navigate = useNavigate();
  const [config, setConfig] = useState(null); const [error, setError] = useState('');
  const load = () => onboardingApi.nonce().then(({ data }) => setConfig(data)).catch((e) => setError(e.data?.code === 'google_not_configured' ? '' : 'Google sign-in is unavailable right now.'));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!config && !error) return null;
  async function onCredential(credential) {
    setError('');
    try { onSession((await authApi.googleLogin(credential)).data); }
    catch (e) {
      if (e.data?.code === 'no_account') navigate('/onboarding');
      else { setError(e.data?.detail || e.message); setConfig(null); load(); }
    }
  }
  return <div className="auth-google">{config && <GoogleButton clientId={config.client_id} nonce={config.nonce} text="signin_with" onCredential={onCredential} />}
    {error && <div className="form-error" role="alert">{error}</div>}<div className="auth-divider"><span>or sign in with your password</span></div></div>;
}

export function Login() {
  const { acceptSession } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({ identifier: '', password: '', otp_code: '' });
  const [mfa, setMfa] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function finish(data) {
    acceptSession(data);
    const onboarding = typeof authApi.onboarding === 'function' ? await authApi.onboarding().catch(() => null) : null;
    navigate(onboarding && onboarding.data.status !== 'approved' ? '/onboarding' : '/overview');
  }
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = mfa ? await authApi.verifyMfa({ mfa_token: mfa, otp_code: values.otp_code }) : await authApi.login({ identifier: values.identifier, password: values.password });
      if (result.data.mfa_required) { setMfa(result.data.mfa_token); return; }
      await finish(result.data);
    } catch (e) { setError(e.message || 'We couldn’t sign you in.'); }
    finally { setBusy(false); }
  }
  return <AuthFrame mode="login"><div className="auth-card"><div className="auth-icon"><LockKeyhole size={19} /></div><div className="eyebrow">WELCOME BACK</div><h2>{mfa ? 'Verify it’s you' : 'Sign in to FinGuard'}</h2><p className="auth-description">{mfa ? 'Enter the one-time code sent to your registered device.' : 'Your finances are in good hands. Sign in to continue.'}</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    {!mfa && <GoogleLogin onSession={finish} />}
    <form onSubmit={submit} className="form-stack">{mfa ? <label>One-time code<input autoComplete="one-time-code" inputMode="numeric" value={values.otp_code} onChange={(e) => setValues({ ...values, otp_code: e.target.value })} required autoFocus /></label> : <><label>Email or username<input autoComplete="username" value={values.identifier} onChange={(e) => setValues({ ...values, identifier: e.target.value })} placeholder="you@example.com" required /></label><label>Password<input type="password" autoComplete="current-password" value={values.password} onChange={(e) => setValues({ ...values, password: e.target.value })} placeholder="Enter your password" required /></label></>}
      <button className="primary-button full" disabled={busy}>{busy ? 'Please wait…' : mfa ? 'Verify and continue' : 'Sign in'} {!busy && <ArrowRight size={16} />}</button></form>
    <div className="auth-switch">New to FinGuard? <Link to="/onboarding">Create an account <ArrowRight size={13} /></Link></div>
  </div><div className="auth-trust"><ShieldCheck size={15} /> Your session is protected with secure token handling</div></AuthFrame>;
}
