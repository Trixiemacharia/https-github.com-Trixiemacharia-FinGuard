import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Check, LogOut, ShieldCheck } from 'lucide-react';
import { authApi } from '../api/services.js';
import { ErrorState, Loading } from '../components/Feedback.jsx';
import { useAuth } from '../context/AuthContext.jsx';

const stepForStatus = {
  account_created: 0,
  phone_pending: 0,
  email_pending: 1,
  photo_pending: 2,
  details_pending: 3,
  rejected: 3,
  review_pending: 4,
  approved: 4,
};

export function Onboarding() {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [notice, setNotice] = useState('');
  const [emailSent, setEmailSent] = useState(false);
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const emailTokenHandled = useRef(false);
  const { updateOnboardingStatus, logout } = useAuth();

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await authApi.onboarding();
      setProfile(data);
      setPhone(data.phone_number || '');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const token = search.get('email_token');
    if (token && !emailTokenHandled.current) {
      emailTokenHandled.current = true;
      authApi.onboardingAction({ action: 'verify_email', token })
        .then(({ data }) => {
          setProfile(data);
          setNotice('Email address verified.');
        })
        .catch((e) => setError(e.message || 'This email verification link is invalid or expired.'))
        .finally(() => {
          setLoading(false);
          navigate('/onboarding', { replace: true });
        });
    } else if (!token) {
      load();
    }
  }, [load, search, navigate]);

  useEffect(() => {
    if (profile?.status === 'approved') {
      updateOnboardingStatus('approved');
      navigate('/overview', { replace: true });
    }
  }, [profile, navigate, updateOnboardingStatus]);

  async function action(body) {
    setError('');
    setNotice('');
    try {
      const { data } = await authApi.onboardingAction(body);
      setProfile(data);
      return data;
    } catch (e) {
      if (e.data?.status) setProfile((current) => ({ ...current, ...e.data }));
      setError(e.message || 'We could not save that step.');
      return null;
    }
  }

  if (loading) return <main className="onboarding-standalone"><Loading label="Loading your account setup" /></main>;
  if (error && !profile) return <main className="onboarding-standalone"><ErrorState error={error} onRetry={load} /></main>;

  const progress = stepForStatus[profile?.status] ?? 0;
  const steps = ['Phone', 'Email', 'Photograph', 'Personal details'];

  return <main className="onboarding-standalone">
    <header className="onboarding-topbar">
      <Link className="onboarding-brand" to="/"><span><ShieldCheck size={18}/></span>FinGuard</Link>
      <span className="onboarding-secure-label"><ShieldCheck size={14}/>Secure account setup</span>
      <button className="onboarding-signout" onClick={async () => { await logout(); navigate('/auth?mode=login', { replace: true }); }}><LogOut size={14}/>Sign out</button>
    </header>
    <section className="onboarding-wrap"><div className="onboarding-card">
      <div className="onboarding-head"><span className="onboarding-badge"><ShieldCheck size={17}/></span><div><span className="eyebrow">YOUR FIN GUARD ACCOUNT</span><h1>Let’s get you set up</h1><p>Complete the setup steps to submit your wallet application.</p></div></div>
      <div className="onboarding-progress">{steps.map((step, i) => <div key={step} className={`onboarding-step ${progress > i ? 'done' : progress === i ? 'current' : ''}`}><span>{progress > i ? <Check size={13}/> : i + 1}</span><small>{step}</small></div>)}</div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {notice && <div className="onboarding-notice"><Check size={15}/>{notice}</div>}

      {['account_created', 'phone_pending'].includes(profile?.status) && <section className="onboarding-stage">
        <span className="eyebrow">STEP 01 · PHONE NUMBER</span><h2>Verify your current phone number</h2>
        <p>We’ll send a one-time code to this number.</p>
        <form className="onboarding-form" onSubmit={async (e) => {
          e.preventDefault();
          const result = await action({ action: 'send_phone_code', phone_number: phone });
          if (result) {
            setCode(result.development_code || '');
            setNotice(result.detail || 'Verification code sent.');
          }
        }}>
          <label>Phone number<input type="tel" autoComplete="tel" placeholder="+254 7XX XXX XXX" value={phone} onChange={(e) => setPhone(e.target.value)} required /></label>
          <button className="primary-button" type="submit">Send code <ArrowRight size={15}/></button>
        </form>
        {profile?.status === 'phone_pending' && <form className="onboarding-form verify-form" onSubmit={async (e) => {
          e.preventDefault();
          const result = await action({ action: 'verify_phone', code });
          if (result) setNotice('Phone number verified.');
        }}>
          <label>Verification code<input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required /></label>
          <button className="primary-button" type="submit">Verify phone <Check size={15}/></button>
        </form>}
      </section>}

      {profile?.status === 'email_pending' && <section className="onboarding-stage">
        <span className="eyebrow">STEP 02 · EMAIL ADDRESS</span><h2>Verify your email address</h2>
        <p>We’ll send a single-use verification link to <strong>{profile.email || 'your registered address'}</strong>.</p>
        <button className="primary-button" disabled={emailSent} onClick={async () => {
          const result = await action({ action: 'send_email_link' });
          if (result) { setEmailSent(true); setNotice(result.detail || 'Verification email sent.'); }
        }}>{emailSent ? 'Verification email sent' : 'Send verification email'} <ArrowRight size={15}/></button>
      </section>}

      {profile?.status === 'photo_pending' && <section className="onboarding-stage">
        <span className="eyebrow">STEP 03 · PHOTOGRAPH</span><h2>Upload a photograph</h2>
        <p>This photograph is collected for your profile. It is not biometric or government-ID verification.</p>
        <form className="onboarding-form" onSubmit={async (e) => {
          e.preventDefault();
          const file = e.currentTarget.photo.files[0];
          if (!file) return;
          try { const { data } = await authApi.uploadOnboardingPhoto(file); setProfile(data); setNotice('Photograph uploaded.'); }
          catch (err) { setError(err.message); }
        }}>
          <label>JPEG, PNG or WebP · up to 5 MB<input name="photo" type="file" accept="image/jpeg,image/png,image/webp" required /></label>
          <button className="primary-button" type="submit">Upload photograph <ArrowRight size={15}/></button>
        </form>
      </section>}

      {(profile?.status === 'details_pending' || profile?.status === 'rejected' || profile?.status === 'review_pending') && <section className="onboarding-stage">
        <span className="eyebrow">STEP 04 · PERSONAL DETAILS</span><h2>{profile.status === 'review_pending' ? 'Your details are saved' : profile.status === 'rejected' ? 'Update your application' : 'Tell us about yourself'}</h2>
        {profile.status === 'review_pending' && <div className="onboarding-pending" role="status">{profile.review_note || 'Your account is pending verification. Wallet access is available after approval. You can submit your details again to retry screening.'}</div>}
        <p>{profile.status === 'review_pending' ? 'Update any details below, then resubmit to retry screening.' : profile.review_note || 'Your information helps us complete account checks.'}</p>
        <form className="onboarding-form details-form" onSubmit={async (e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          const payload = Object.fromEntries(form.entries());
          payload.action = 'submit_details';
          const result = await action(payload);
          if (result) {
            updateOnboardingStatus(result.status);
            if (result.status === 'approved') navigate('/overview', { replace: true });
          }
        }}>
          <label>Residential address<input name="residential_address" defaultValue={profile.residential_address} required maxLength="250" /></label>
          <label>County / region<input name="county" defaultValue={profile.county} required maxLength="80" /></label>
          <label>Town<input name="town" defaultValue={profile.town} required maxLength="80" /></label>
          <label>Occupation<input name="occupation" defaultValue={profile.occupation} required maxLength="100" /></label>
          <label>Monthly earnings (KES)<input name="monthly_income" type="number" min="0" step="0.01" defaultValue={profile.monthly_income || ''} required /></label>
          <button className="primary-button" type="submit">{profile.status === 'review_pending' ? 'Resubmit personal details' : 'Submit application'} <ArrowRight size={15}/></button>
        </form>
      </section>}

      <div className="onboarding-foot"><ShieldCheck size={14}/>Your information is handled securely and scoped to your account.</div>
    </div></section>
  </main>;
}
