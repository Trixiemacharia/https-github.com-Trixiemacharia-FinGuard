import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Check, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react';
import { authApi } from '../api/services.js';
import { ApiError } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';

function AuthFrame({ children, mode }) {
  return <div className="auth-page"><section className="auth-visual"><div className="auth-brand"><div className="brand-symbol"><ShieldCheck size={19} /></div>fin<span>guard</span></div><div className="visual-orbit orbit-one" /><div className="visual-orbit orbit-two" /><div className="visual-content"><div className="visual-kicker"><Sparkles size={14} /> FINANCIAL CLARITY, BUILT IN</div><h1>Money should<br />move with <em>confidence.</em></h1><p>One secure place to keep an eye on your balance, activity, and financial wellbeing.</p><div className="visual-list"><span><Check size={15} /> Protected account access</span><span><Check size={15} /> Clear, real-time activity</span><span><Check size={15} /> Security built around you</span></div></div><div className="visual-footer"><span>FinGuard Financial Services</span><span>Secure by design <LockKeyhole size={13} /></span></div></section><section className="auth-panel"><div className="auth-panel-top"><span>Secure account access</span><span className="secure-chip"><ShieldCheck size={14} /> Encrypted</span></div>{children}<div className="auth-legal">By continuing, you agree to use FinGuard responsibly and keep your sign-in details private.</div></section></div>;
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
      acceptSession(result.data); navigate('/');
    } catch (e) { setError(e.message || 'We couldn’t sign you in.'); }
    finally { setBusy(false); }
  }
  return <AuthFrame><div className="auth-card"><div className="auth-icon"><LockKeyhole size={19} /></div><div className="eyebrow">WELCOME BACK</div><h2>{mfa ? 'Verify it’s you' : 'Sign in to FinGuard'}</h2><p className="auth-description">{mfa ? 'Enter the one-time code sent to your registered device.' : 'Your finances are in good hands. Sign in to continue.'}</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <form onSubmit={submit} className="form-stack">{mfa ? <label>One-time code<input autoComplete="one-time-code" inputMode="numeric" value={values.otp_code} onChange={(e) => setValues({ ...values, otp_code: e.target.value })} required autoFocus /></label> : <><label>Email or username<input autoComplete="username" value={values.identifier} onChange={(e) => setValues({ ...values, identifier: e.target.value })} placeholder="you@example.com" required /></label><label>Password<input type="password" autoComplete="current-password" value={values.password} onChange={(e) => setValues({ ...values, password: e.target.value })} placeholder="Enter your password" required /></label></>}
      <button className="primary-button full" disabled={busy}>{busy ? 'Please wait…' : mfa ? 'Verify and continue' : 'Sign in'} {!busy && <ArrowRight size={16} />}</button></form>
    <div className="auth-switch">New to FinGuard? <Link to="/register">Create an account <ArrowRight size={13} /></Link></div>
  </div><div className="auth-trust"><ShieldCheck size={15} /> Your session is protected with secure token handling</div></AuthFrame>;
}

export function Register() {
  const { acceptSession } = useAuth(); const navigate = useNavigate();
  const [values, setValues] = useState({ username: '', email: '', password: '' }); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event) { event.preventDefault(); setBusy(true); setError(''); try { const { data } = await authApi.register(values); acceptSession(data); navigate('/'); } catch (e) { setError(e.message || 'We couldn’t create your account.'); } finally { setBusy(false); } }
  return <AuthFrame><div className="auth-card"><div className="auth-icon"><ShieldCheck size={19} /></div><div className="eyebrow">GET STARTED</div><h2>Create your account</h2><p className="auth-description">A safer, clearer view of your money starts here.</p>{error && <div className="form-error" role="alert">{error}</div>}<form onSubmit={submit} className="form-stack"><label>Username<input autoComplete="username" value={values.username} onChange={(e) => setValues({ ...values, username: e.target.value })} required /></label><label>Email address<input type="email" autoComplete="email" value={values.email} onChange={(e) => setValues({ ...values, email: e.target.value })} required /></label><label>Password<input type="password" autoComplete="new-password" value={values.password} onChange={(e) => setValues({ ...values, password: e.target.value })} required /></label><small className="field-note">Choose a strong password. Your account enforces the server’s password policy.</small><button className="primary-button full" disabled={busy}>{busy ? 'Creating account…' : 'Create account'} {!busy && <ArrowRight size={16} />}</button></form><div className="auth-switch">Already have an account? <Link to="/login">Sign in <ArrowRight size={13} /></Link></div></div><div className="auth-trust"><ShieldCheck size={15} /> Your information is protected</div></AuthFrame>;
}
