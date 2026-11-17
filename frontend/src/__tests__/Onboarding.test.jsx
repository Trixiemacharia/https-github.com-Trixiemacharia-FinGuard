import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

const api = vi.hoisted(() => ({
  nonce: vi.fn(), google: vi.fn(), state: vi.fn(), consent: vi.fn(), photo: vi.fn(), challenge: vi.fn(), preview: vi.fn(), verify: vi.fn(),
  sendPhoneCode: vi.fn(), verifyPhoneCode: vi.fn(), details: vi.fn(), complete: vi.fn(),
}));
const auth = vi.hoisted(() => ({ value: {}, onboarding: vi.fn(), logout: vi.fn() }));
vi.mock('../api/services.js', () => ({ onboardingApi: api, authApi: { onboarding: auth.onboarding } }));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth.value }));
vi.mock('../components/GoogleButton.jsx', () => ({
  GoogleButton: ({ onCredential, nonce }) => <button type="button" onClick={() => onCredential(`credential-for-${nonce}`)}>Continue with Google</button>,
}));
import { Onboarding } from '../pages/Onboarding.jsx';

const baseState = {
  stage: 'identity', email: 'amina@example.com', email_verified: true, resuming_account: false, consent_given: false,
  identity: { status: 'not_started', last_failure: '', message: '', photo_attempts_left: 6, liveness_attempts_left: 5, needs_review: false },
  phone: { number: '', verified: false },
  details: { first_name: 'Amina', last_name: 'Otieno', date_of_birth: null, country: '', residential_address: '', county: '', town: '', occupation: '', monthly_income: null },
  details_complete: false, countries: { KE: 'Kenya', UG: 'Uganda' }, minimum_birth_date: '2008-11-18', expires_at: '2026-11-18T12:00:00Z',
};
const state = (overrides = {}) => ({ ...baseState, ...overrides });

function Where() { return <output data-testid="path">{useLocation().pathname}</output>; }
function renderFlow() {
  return render(<MemoryRouter initialEntries={['/onboarding']}><Where /><Routes>
    <Route path="/onboarding" element={<Onboarding />} /><Route path="/overview" element={<div>Dashboard</div>} />
    <Route path="/auth" element={<div>Sign in page</div>} />
  </Routes></MemoryRouter>);
}
const reject = (status, data) => Promise.reject(Object.assign(new Error(data?.detail || 'error'), { status, data }));

beforeEach(() => {
  sessionStorage.clear();
  auth.value = { authenticated: false, user: null, acceptSession: vi.fn(), updateOnboardingStatus: vi.fn(), logout: auth.logout };
  api.nonce.mockResolvedValue({ data: { nonce: 'nonce-1', client_id: 'client' } });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); delete navigator.mediaDevices; });

describe('email verification', () => {
  it('verifies with Google using the server nonce, stores only the session id, and opens identity verification', async () => {
    api.google.mockResolvedValue({ data: { token: 'session-token', resumed: false, ...state() } });
    renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }));
    expect(await screen.findByText('How we use your photos')).toBeTruthy();
    expect(api.google).toHaveBeenCalledWith('credential-for-nonce-1', 'nonce-1');
    expect(sessionStorage.getItem('finguard.onboarding')).toBe('session-token');
    const steps = screen.getByLabelText('Sign-up progress');
    expect(within(steps).getByText('Email verification').closest('li').className).toBe('done');
    expect(within(steps).getByText('Identity verification').closest('li').className).toBe('current');
  });

  it('sends an existing user to sign in without starting a registration', async () => {
    api.google.mockImplementation(() => reject(409, { code: 'existing_account', detail: 'An account already exists for this email. Sign in instead.', login_method: 'google' }));
    renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }));
    expect(await screen.findByText(/already exists/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Sign in to your account' }).getAttribute('href')).toBe('/auth?mode=login');
    expect(sessionStorage.getItem('finguard.onboarding')).toBeNull();
    await waitFor(() => expect(api.nonce).toHaveBeenCalledTimes(2)); // a fresh nonce for the next attempt
  });

  it('explains an unverified Google email', async () => {
    api.google.mockImplementation(() => reject(403, { code: 'unverified_email', detail: 'Your Google account’s email address isn’t verified by Google.' }));
    renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }));
    expect(await screen.findByText(/isn’t verified by Google/)).toBeTruthy();
  });

  it('restores progress after a reload and returns to step 1 when the session has expired', async () => {
    sessionStorage.setItem('finguard.onboarding', 'saved');
    api.state.mockResolvedValueOnce({ data: state({ stage: 'details', identity: { ...baseState.identity, status: 'VERIFIED' } }) });
    renderFlow();
    expect(await screen.findByText('Complete your profile')).toBeTruthy();
    expect(api.state).toHaveBeenCalledWith('saved');
    cleanup();
    sessionStorage.setItem('finguard.onboarding', 'old');
    api.state.mockImplementationOnce(() => reject(401, { code: 'session_expired', detail: 'Your sign-up session expired.' }));
    renderFlow();
    expect(await screen.findByText('Your sign-up session expired.')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Continue with Google' })).toBeTruthy();
    expect(sessionStorage.getItem('finguard.onboarding')).toBeNull();
  });
});

describe('identity verification', () => {
  async function atPhoto() {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: state({ consent_given: true }) });
    renderFlow();
    return screen.findByText('Verify your identity');
  }

  it('requires consent before any photo is processed', async () => {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: state() });
    api.consent.mockResolvedValue({ data: state({ consent_given: true }) });
    renderFlow();
    const button = await screen.findByRole('button', { name: 'Continue' });
    expect(button.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(button);
    expect(await screen.findByText('Verify your identity')).toBeTruthy();
  });

  it('rejects unsupported and oversized files before upload, and shows the server reason for unsuitable photos', async () => {
    await atPhoto();
    const input = screen.getByLabelText('Choose photo');
    fireEvent.change(input, { target: { files: [new File(['x'], 'doc.pdf', { type: 'application/pdf' })] } });
    expect(screen.getByText('Use a JPEG, PNG or WebP photo.')).toBeTruthy();
    const big = new File(['x'], 'big.jpg', { type: 'image/jpeg' }); Object.defineProperty(big, 'size', { value: 6 * 1024 * 1024 });
    fireEvent.change(input, { target: { files: [big] } });
    expect(screen.getByText(/over 5 MB/)).toBeTruthy();
    expect(api.photo).not.toHaveBeenCalled();
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:preview'); globalThis.URL.revokeObjectURL = vi.fn();
    api.photo.mockImplementation(() => reject(422, { accepted: false, outcome: 'MULTIPLE_FACES', message: 'More than one face is visible. Use a photo of only you.', attempts_left: 4 }));
    fireEvent.change(input, { target: { files: [new File(['img'], 'me.jpg', { type: 'image/jpeg' })] } });
    expect(screen.getByAltText('Selected photograph preview')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Check photo' }));
    expect(await screen.findByText('More than one face is visible. Use a photo of only you.')).toBeTruthy();
    expect(screen.getByText('4 attempts left')).toBeTruthy();
    expect(screen.getByRole('button', { name: /replace image/i })).toBeTruthy();
  });

  it('handles a blocked or missing camera with clear next steps', async () => {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: state({ consent_given: true, identity: { ...baseState.identity, status: 'photo_accepted' } }) });
    navigator.mediaDevices = { getUserMedia: vi.fn().mockRejectedValue(Object.assign(new Error('no'), { name: 'NotAllowedError' })) };
    renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: /turn on camera/i }));
    expect(await screen.findByText('Allow camera access to continue.')).toBeTruthy();
    navigator.mediaDevices.getUserMedia.mockRejectedValue(Object.assign(new Error('none'), { name: 'NotFoundError' }));
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByText('We couldn’t use a camera on this device.')).toBeTruthy();
    expect(screen.getByText(/Your progress is saved for 24 hours/)).toBeTruthy();
  });

  it('stops the camera when the step is left', async () => {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: state({ consent_given: true, identity: { ...baseState.identity, status: 'photo_accepted' } }) });
    const track = { stop: vi.fn() };
    navigator.mediaDevices = { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) };
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue();
    const view = renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: /turn on camera/i }));
    expect(await screen.findByLabelText('Camera preview')).toBeTruthy();
    view.unmount();
    expect(track.stop).toHaveBeenCalled();
  });
});

describe('personal details and account creation', () => {
  const detailsState = () => state({ stage: 'details', consent_given: true, identity: { ...baseState.identity, status: 'VERIFIED' } });

  it('validates fields and requires a verified phone', async () => {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: detailsState() });
    renderFlow();
    await screen.findByText('Complete your profile');
    expect(screen.getByDisplayValue('Amina')).toBeTruthy(); // prefilled from Google, editable
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText('Verify your phone number first.')).toBeTruthy();
    expect(api.details).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Mobile number/), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(screen.getByText(/Enter a valid phone number/)).toBeTruthy();
    api.sendPhoneCode.mockResolvedValue({ data: { phone_number: '+254712345678', detail: 'We sent a 6-digit code to +254712345678.' } });
    api.verifyPhoneCode.mockResolvedValue({ data: { ...detailsState(), phone: { number: '+254712345678', verified: true } } });
    fireEvent.change(screen.getByLabelText(/Mobile number/), { target: { value: '0712 345 678' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send code' }));
    fireEvent.change(await screen.findByLabelText('6-digit code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('+254712345678 verified')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Date of birth/), { target: { value: '2010-01-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByText('You must be at least 18.')).toBeTruthy();
    expect(screen.getAllByText('Required.').length).toBeGreaterThan(0);
    expect(api.details).not.toHaveBeenCalled();
  });

  it('creates the account and opens the dashboard only when the backend returns approved', async () => {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: state({ stage: 'create_account', identity: { ...baseState.identity, status: 'VERIFIED' },
      phone: { number: '+254712345678', verified: true }, details: { ...baseState.details, residential_address: '1 Road', town: 'Nairobi', county: 'Nairobi' } }) });
    api.complete.mockResolvedValue({ data: { user: { id: 9 }, access: 'jwt', onboarding_status: 'approved' } });
    renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: 'Create my account' }));
    expect(await screen.findByText('Dashboard')).toBeTruthy();
    expect(auth.value.acceptSession).toHaveBeenCalledWith({ user: { id: 9 }, access: 'jwt', onboarding_status: 'approved' });
    expect(auth.value.updateOnboardingStatus).toHaveBeenCalledWith('approved');
    expect(sessionStorage.getItem('finguard.onboarding')).toBeNull();
  });

  it('keeps a pending application on onboarding and shows the backend message', async () => {
    auth.value = { ...auth.value, authenticated: true, user: { onboarding_status: 'review_pending' } };
    auth.onboarding.mockResolvedValue({ data: { review_note: 'Your identity check needs a person to confirm it.' } });
    renderFlow();
    expect(await screen.findByText('Your identity check needs a person to confirm it.')).toBeTruthy();
    expect(screen.getByTestId('path').textContent).toBe('/onboarding');
  });

  it('keeps progress and offers a retry when account creation fails', async () => {
    sessionStorage.setItem('finguard.onboarding', 'tok');
    api.state.mockResolvedValue({ data: state({ stage: 'create_account', identity: { ...baseState.identity, status: 'VERIFIED' },
      phone: { number: '+254712345678', verified: true }, details: { ...baseState.details, residential_address: '1 Road', town: 'N', county: 'N' } }) });
    api.complete.mockImplementationOnce(() => reject(0, null)).mockResolvedValueOnce({ data: { user: {}, access: 'jwt', onboarding_status: 'approved' } });
    renderFlow();
    fireEvent.click(await screen.findByRole('button', { name: 'Create my account' }));
    expect(await screen.findByText(/You appear to be offline/)).toBeTruthy();
    expect(sessionStorage.getItem('finguard.onboarding')).toBe('tok');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Create my account' })); });
    expect(await screen.findByText('Dashboard')).toBeTruthy();
  });
});

it('keeps the saved session through a temporary server error', async () => {
  sessionStorage.setItem('finguard.onboarding', 'tok');
  api.state.mockImplementationOnce(() => reject(503, { detail: 'down' })).mockResolvedValueOnce({ data: state({ consent_given: true }) });
  renderFlow();
  expect(await screen.findByText(/Your progress is saved/)).toBeTruthy();
  expect(sessionStorage.getItem('finguard.onboarding')).toBe('tok');
  fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
  expect(await screen.findByText('Verify your identity')).toBeTruthy();
});
