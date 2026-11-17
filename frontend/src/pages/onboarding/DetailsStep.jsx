import { useState } from 'react';
import { CheckCircle2, Loader2, Lock, UserRound } from 'lucide-react';
import { onboardingApi } from '../../api/services.js';

const PHONE = /^(?:\+?[1-9]\d{7,14}|0[17]\d{8})$/;
const NAME = /^[\p{L}]+(?:[ '-][\p{L}]+)*$/u;

function validate(form, minDob) {
  const errors = {};
  ['first_name', 'last_name'].forEach((key) => {
    if (!form[key].trim()) errors[key] = 'Required.';
    else if (!NAME.test(form[key].trim())) errors[key] = 'Use letters, spaces, hyphens or apostrophes.';
  });
  if (!form.date_of_birth) errors.date_of_birth = 'Required.';
  else if (minDob && form.date_of_birth > minDob) errors.date_of_birth = 'You must be at least 18.';
  ['country', 'residential_address', 'county', 'town', 'occupation'].forEach((key) => { if (!String(form[key] || '').trim()) errors[key] = 'Required.'; });
  if (form.monthly_income === '' || !/^\d{1,12}(\.\d{1,2})?$/.test(String(form.monthly_income))) errors.monthly_income = 'Enter an amount in KSh, e.g. 45000.';
  return errors;
}

export function DetailsStep({ token, state, onState }) {
  const prefill = state.details;
  const [form, setForm] = useState({
    first_name: prefill.first_name || '', last_name: prefill.last_name || '', date_of_birth: prefill.date_of_birth || '',
    country: prefill.country || 'KE', residential_address: prefill.residential_address || '', county: prefill.county || '',
    town: prefill.town || '', occupation: prefill.occupation || '', monthly_income: prefill.monthly_income ?? '',
  });
  const [phone, setPhone] = useState(state.phone.number || ''); const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false); const [phoneMsg, setPhoneMsg] = useState(null);
  const [touched, setTouched] = useState(false); const [serverErrors, setServerErrors] = useState({});
  const [busy, setBusy] = useState(''); const [error, setError] = useState('');
  const errors = { ...validate(form, state.minimum_birth_date), ...serverErrors };
  const set = (key) => (e) => { setForm((f) => ({ ...f, [key]: e.target.value })); setServerErrors((s) => { const n = { ...s }; delete n[key]; return n; }); };

  async function sendCode() {
    if (!PHONE.test(phone.replace(/[\s().-]/g, ''))) { setPhoneMsg({ type: 'error', text: 'Enter a valid phone number, e.g. 0712 345 678.' }); return; }
    setBusy('send'); setPhoneMsg(null);
    try { const { data } = await onboardingApi.sendPhoneCode(token, phone); setPhone(data.phone_number); setCodeSent(true); setPhoneMsg({ type: 'info', text: data.detail }); }
    catch (e) { setPhoneMsg({ type: 'error', text: e.data?.detail || e.message }); } finally { setBusy(''); }
  }
  async function verifyCode() {
    setBusy('verify'); setPhoneMsg(null);
    try { const { data } = await onboardingApi.verifyPhoneCode(token, code); onState(data); setPhoneMsg({ type: 'good', text: 'Phone number verified.' }); }
    catch (e) { setPhoneMsg({ type: 'error', text: e.data?.detail || e.message }); } finally { setBusy(''); }
  }
  async function submit(event) {
    event.preventDefault(); setTouched(true); setError('');
    if (!state.phone.verified) { setError('Verify your phone number first.'); return; }
    if (Object.keys(validate(form, state.minimum_birth_date)).length) return;
    setBusy('save');
    try { const { data } = await onboardingApi.details(token, { ...form, first_name: form.first_name.trim(), last_name: form.last_name.trim() }); onState(data); }
    catch (e) {
      const fieldErrors = Object.fromEntries(Object.entries(e.data || {}).filter(([k, v]) => k in form && Array.isArray(v)).map(([k, v]) => [k, v.join(' ')]));
      setServerErrors(fieldErrors); setError(Object.keys(fieldErrors).length ? 'Please correct the highlighted fields.' : e.data?.detail || e.message);
    } finally { setBusy(''); }
  }
  const field = (key, label, props = {}) => <label className={touched && errors[key] ? 'invalid' : ''}>{label}
    <input value={form[key]} onChange={set(key)} aria-invalid={touched && !!errors[key]} {...props} />
    {touched && errors[key] && <small className="ob-field-error">{errors[key]}</small>}</label>;

  return <form className="ob-panel" onSubmit={submit} noValidate>
    <span className="ob-step-icon"><UserRound size={20} /></span>
    <h2>Complete your profile</h2>
    <p className="ob-lead">Your email <strong>{state.email}</strong> is verified with Google and can’t be changed here.</p>

    <fieldset className="ob-fieldset"><legend>Phone number</legend>
      {state.phone.verified ? <p className="ob-verified"><CheckCircle2 size={16} /> {state.phone.number} verified</p> : <>
        <div className="ob-inline">
          <label>Mobile number (used for M-Pesa)<input inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => { setPhone(e.target.value); setCodeSent(false); }} placeholder="0712 345 678" /></label>
          <button type="button" className="ob-btn" onClick={sendCode} disabled={busy === 'send'}>{busy === 'send' ? 'Sending…' : codeSent ? 'Resend code' : 'Send code'}</button>
        </div>
        {codeSent && <div className="ob-inline">
          <label>6-digit code<input inputMode="numeric" autoComplete="one-time-code" maxLength="6" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} /></label>
          <button type="button" className="ob-btn primary" onClick={verifyCode} disabled={code.length !== 6 || busy === 'verify'}>{busy === 'verify' ? 'Checking…' : 'Verify'}</button>
        </div>}
        {phoneMsg && <p className={`ob-msg ${phoneMsg.type}`} role={phoneMsg.type === 'error' ? 'alert' : 'status'}>{phoneMsg.text}</p>}
      </>}
    </fieldset>

    <fieldset className="ob-fieldset"><legend>About you</legend>
      <div className="ob-grid">
        {field('first_name', 'First name', { autoComplete: 'given-name' })}
        {field('last_name', 'Last name', { autoComplete: 'family-name' })}
        {field('date_of_birth', 'Date of birth', { type: 'date', max: state.minimum_birth_date, autoComplete: 'bday' })}
        <label className={touched && errors.country ? 'invalid' : ''}>Country of residence
          <select value={form.country} onChange={set('country')}>{Object.entries(state.countries).map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select>
          {touched && errors.country && <small className="ob-field-error">{errors.country}</small>}</label>
      </div>
    </fieldset>
    <fieldset className="ob-fieldset"><legend>Address and income</legend>
      <div className="ob-grid">
        <div className="wide">{field('residential_address', 'Residential address', { autoComplete: 'street-address' })}</div>
        {field('county', 'County / region')}
        {field('town', 'Town', { autoComplete: 'address-level2' })}
        {field('occupation', 'Occupation')}
        {field('monthly_income', 'Monthly income (KSh)', { inputMode: 'decimal' })}
      </div>
    </fieldset>
    <p className="ob-privacy"><Lock size={13} /> We use these details to open and protect your account and meet our legal obligations. Your photos are not kept after verification (see the notice you accepted).</p>
    {error && <div className="ob-alert error" role="alert"><div><strong>{error}</strong></div></div>}
    <button className="ob-btn primary" disabled={busy === 'save'}>{busy === 'save' ? <><Loader2 size={16} className="ob-spin" /> Saving…</> : 'Continue'}</button>
  </form>;
}
