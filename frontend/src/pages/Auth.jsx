import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Check, LockKeyhole, ShieldCheck } from 'lucide-react';
import { BackButton } from '../components/BackButton.jsx';
import { FiBrand } from '../components/icons/FinIcons.jsx';
import { authApi } from '../api/services.js';
import { GoogleOption } from '../components/GoogleOption.jsx';
import { ApiError } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';

function AuthFrame({ children, mode }) {
  return <div className="auth-page"><section className="auth-visual"><div className="auth-brand"><div className="brand-symbol"><ShieldCheck size={19} /></div>fin<span>guard</span></div><div className="visual-orbit orbit-one" /><div className="visual-orbit orbit-two" /><div className="visual-content"><div className="visual-kicker"><FiBrand size={14} /> FINANCIAL CLARITY, BUILT IN</div><h1>Money should<br />move with <em>confidence.</em></h1><p>One secure place to keep an eye on your balance, activity, and financial wellbeing.</p><div className="visual-list"><span><Check size={15} /> Protected account access</span><span><Check size={15} /> Clear, real-time activity</span><span><Check size={15} /> Security built around you</span></div></div><div className="visual-footer"><span>FinGuard Financial Services</span><span>Secure by design <LockKeyhole size={13} /></span></div></section><section className="auth-panel"><div className="auth-panel-top"><BackButton fallback="/" label="Back to home" className="auth-back" /><span className="auth-panel-label">Secure account access</span><span className="secure-chip"><ShieldCheck size={14} /> Encrypted</span></div><div className="auth-mode-tabs"><Link className={mode === 'register' ? 'selected' : ''} to="/auth?mode=register">Create account</Link><Link className={mode === 'login' ? 'selected' : ''} to="/auth?mode=login">Sign in</Link></div>{children}<div className="auth-legal">By continuing, you agree to use FinGuard responsibly and keep your sign-in details private.</div></section></div>;
}

export function AuthPage() {
  const [params] = useSearchParams();
  return params.get('mode') === 'register' ? <Register /> : <Login />;
}

export function Login() {
  const { acceptSession } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({ identifier: '', password: '', otp_code: '' });
  const [mfa, setMfa] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = mfa ? await authApi.verifyMfa({ mfa_token: mfa, otp_code: values.otp_code }) : await authApi.login({ identifier: values.identifier, password: values.password });
      if (result.data.mfa_required) { setMfa(result.data.mfa_token); return; }
      acceptSession(result.data);
      const onboarding = typeof authApi.onboarding === 'function' ? await authApi.onboarding().catch(() => null) : null;
      navigate(onboarding && onboarding.data.status !== 'approved' ? '/onboarding' : '/overview');
    } catch (e) { setError(e.message || 'We couldn’t sign you in.'); }
    finally { setBusy(false); }
  }
  return <AuthFrame mode="login"><div className="auth-card"><div className="auth-icon"><LockKeyhole size={19} /></div><div className="eyebrow">WELCOME BACK</div><h2>{mfa ? 'Verify it’s you' : 'Sign in to FinGuard'}</h2><p className="auth-description">{mfa ? 'Enter the one-time code sent to your registered device.' : 'Your finances are in good hands. Sign in to continue.'}</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <form onSubmit={submit} className="form-stack">{mfa ? <label>One-time code<input autoComplete="one-time-code" inputMode="numeric" value={values.otp_code} onChange={(e) => setValues({ ...values, otp_code: e.target.value })} required autoFocus /></label> : <><label>Email or username<input autoComplete="username" value={values.identifier} onChange={(e) => setValues({ ...values, identifier: e.target.value })} placeholder="you@example.com" required /></label><label>Password<input type="password" autoComplete="current-password" value={values.password} onChange={(e) => setValues({ ...values, password: e.target.value })} placeholder="Enter your password" required /></label></>}
      <button className="primary-button full" disabled={busy}>{busy ? 'Please wait…' : mfa ? 'Verify and continue' : 'Sign in'} {!busy && <ArrowRight size={16} />}</button></form>
    {mfa && <div className="auth-step-back"><BackButton label="Use a different account" onClick={() => { setMfa(null); setError(''); setValues({ ...values, otp_code: '' }); }} /></div>}
    {!mfa && <GoogleOption label="or" text="signin_with" centered onCredential={async (credential, nonce) => {
      setError('');
      try {
        const { data } = await authApi.googleLogin(credential, nonce);
        acceptSession(data);
        const onboarding = await authApi.onboarding().catch(() => null);
        navigate(onboarding && onboarding.data.status !== 'approved' ? '/onboarding' : '/overview');
      } catch (e) { setError(e.data?.detail || e.message || 'We couldn’t sign you in with Google.'); }
    }} />}
    <div className="auth-switch">New to FinGuard? <Link to="/auth?mode=register">Create an account <ArrowRight size={13} /></Link></div>
  </div><div className="auth-trust"><ShieldCheck size={15} /> Your session is protected with secure token handling</div></AuthFrame>;
}

export function Register() {
  const { acceptSession } = useAuth(); const navigate = useNavigate();
  const [values, setValues] = useState({ username: '', email: '', password: '' }); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event) { event.preventDefault(); setBusy(true); setError(''); try { const { data } = await authApi.register(values); acceptSession(data); navigate('/onboarding'); } catch (e) { setError(e.message || 'We couldn’t create your account.'); } finally { setBusy(false); } }
  return <AuthFrame mode="register"><div className="auth-card"><div className="auth-icon"><ShieldCheck size={19} /></div><div className="eyebrow">GET STARTED</div><h2>Create your account</h2><p className="auth-description">A safer, clearer view of your money starts here.</p>{error && <div className="form-error" role="alert">{error}</div>}<form onSubmit={submit} className="form-stack"><label>Username<input autoComplete="username" value={values.username} onChange={(e) => setValues({ ...values, username: e.target.value })} required /></label><label>Email address<input type="email" autoComplete="email" value={values.email} onChange={(e) => setValues({ ...values, email: e.target.value })} required /></label><label>Password<input type="password" autoComplete="new-password" value={values.password} onChange={(e) => setValues({ ...values, password: e.target.value })} required /></label><small className="field-note">Choose a strong password. Your account enforces the server’s password policy.</small><button className="primary-button full" disabled={busy}>{busy ? 'Creating account…' : 'Create account'} {!busy && <ArrowRight size={16} />}</button></form><GoogleOption label="or create your account with Google" text="signup_with" centered onCredential={async (credential, nonce) => {
      setError('');
      try { const { data } = await authApi.googleLogin(credential, nonce); acceptSession(data); navigate('/onboarding'); }
      catch (e) { setError(e.data?.detail || e.message || 'We couldn’t create your account with Google.'); }
    }} /><div className="auth-switch">Already have an account? <Link to="/auth?mode=login">Sign in <ArrowRight size={13} /></Link></div></div><div className="auth-trust"><ShieldCheck size={15} /> Your information is protected</div></AuthFrame>;
}
