import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ onboarding: vi.fn(), onboardingAction: vi.fn(), updateOnboardingStatus: vi.fn(), logout: vi.fn(),
  uploadOnboardingPhoto: vi.fn(), consent: vi.fn(), challenge: vi.fn(), preview: vi.fn(), verify: vi.fn(),
  googleNonce: vi.fn(() => Promise.reject(Object.assign(new Error('not configured'), { status: 503 }))) }));
vi.mock('../api/services.js', () => ({
  authApi: { onboarding: mocks.onboarding, onboardingAction: mocks.onboardingAction, uploadOnboardingPhoto: mocks.uploadOnboardingPhoto, googleNonce: mocks.googleNonce },
  identityApi: { consent: mocks.consent, challenge: mocks.challenge, preview: mocks.preview, verify: mocks.verify },
}));
vi.mock('../components/GoogleButton.jsx', () => ({ GoogleButton: ({ onCredential }) => <button type="button" onClick={() => onCredential('google-id-token')}>Continue with Google</button> }));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ updateOnboardingStatus: mocks.updateOnboardingStatus, logout: mocks.logout }) }));
import { Onboarding } from '../pages/Onboarding.jsx';

const personalDetails = {
  status: 'details_pending', email: 'ryver@example.com', phone_number: '+254712345678',
  residential_address: '', county: '', town: '', occupation: '', monthly_income: null,
};

function CurrentPath() {
  const location = useLocation();
  return <output data-testid="current-path">{location.pathname}</output>;
}

function renderOnboarding() {
  return render(<MemoryRouter initialEntries={['/onboarding']}><CurrentPath /><Routes>
    <Route path="/onboarding" element={<Onboarding />} />
    <Route path="*" element={<div>Dashboard</div>} />
  </Routes></MemoryRouter>);
}

async function submitDetails() {
  await screen.findByRole('heading', { name: 'Tell us about yourself' });
  fireEvent.change(screen.getByLabelText(/residential address/i), { target: { value: '1 Sample Road' } });
  fireEvent.change(screen.getByLabelText(/county/i), { target: { value: 'Nairobi' } });
  fireEvent.change(screen.getByLabelText(/^town/i), { target: { value: 'Nairobi' } });
  fireEvent.change(screen.getByLabelText(/occupation/i), { target: { value: 'Designer' } });
  fireEvent.change(screen.getByLabelText(/monthly earnings/i), { target: { value: '80000' } });
  fireEvent.click(screen.getByRole('button', { name: /submit application/i }));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('onboarding approval handoff', () => {
  it('redirects to the dashboard only after the backend returns approved', async () => {
    mocks.onboarding.mockResolvedValue({ data: personalDetails });
    mocks.onboardingAction.mockResolvedValue({ data: { ...personalDetails, status: 'approved' } });
    renderOnboarding();

    await submitDetails();

    await waitFor(() => expect(screen.getByTestId('current-path').textContent).toBe('/overview'));
    expect(mocks.updateOnboardingStatus).toHaveBeenCalledWith('approved');
    expect(mocks.onboardingAction).toHaveBeenCalledWith(expect.objectContaining({ action: 'submit_details' }));
  });

  it('keeps a pending application on personal details and shows the backend message', async () => {
    mocks.onboarding.mockResolvedValue({ data: personalDetails });
    mocks.onboardingAction.mockResolvedValue({ data: {
      ...personalDetails,
      status: 'review_pending',
      review_note: 'Screening is still pending. Wallet access follows approval.',
    } });
    renderOnboarding();

    await submitDetails();

    expect(await screen.findByText('Screening is still pending. Wallet access follows approval.')).toBeTruthy();
    expect(screen.getByTestId('current-path').textContent).toBe('/onboarding');
    expect(mocks.updateOnboardingStatus).toHaveBeenCalledWith('review_pending');
  });
});

describe('step 02 verification additions', () => {
  const photoStage = (identity) => ({ status: 'photo_pending', email: 'ryver@example.com', phone_number: '+254712345678',
    phone_verified: true, email_verified: true, photo_uploaded: false, identity: { status: 'not_started', consent_given: false, ...identity } });

  it('verifies the email with Google as an alternative to the email link', async () => {
    mocks.googleNonce.mockResolvedValueOnce({ data: { client_id: 'cid', nonce: 'n-1' } });
    mocks.onboarding.mockResolvedValue({ data: { status: 'email_pending', email: 'ryver@example.com' } });
    mocks.onboardingAction.mockResolvedValue({ data: photoStage({}) });
    renderOnboarding();
    expect(await screen.findByRole('button', { name: /send verification email/i })).toBeTruthy(); // existing control kept
    fireEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }));
    await waitFor(() => expect(mocks.onboardingAction).toHaveBeenCalledWith({ action: 'verify_email_google', credential: 'google-id-token', nonce: 'n-1' }));
    expect(await screen.findByText('Email address verified with Google.')).toBeTruthy();
  });

  it('asks for consent before the photograph upload', async () => {
    mocks.onboarding.mockResolvedValueOnce({ data: photoStage({}) }).mockResolvedValueOnce({ data: photoStage({ consent_given: true }) });
    mocks.consent.mockResolvedValue({ data: {} });
    renderOnboarding();
    expect(await screen.findByRole('heading', { name: 'Upload a photograph' })).toBeTruthy();
    expect(screen.queryByLabelText(/JPEG, PNG or WebP/)).toBeNull();
    const button = screen.getByRole('button', { name: /continue/i });
    expect(button.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(button);
    expect(await screen.findByLabelText(/JPEG, PNG or WebP/)).toBeTruthy();
    expect(mocks.consent).toHaveBeenCalled();
  });

  it('explains why a photograph was rejected and lets the user replace it', async () => {
    mocks.onboarding.mockResolvedValue({ data: photoStage({ consent_given: true }) });
    mocks.uploadOnboardingPhoto.mockRejectedValue(Object.assign(new Error('x'), { status: 422, data: { ...photoStage({ consent_given: true }),
      photo_check: { accepted: false, outcome: 'MULTIPLE_FACES', message: 'More than one face is visible. Use a photo of only you.', attempts_left: 4 } } }));
    renderOnboarding();
    const input = await screen.findByLabelText(/JPEG, PNG or WebP/);
    await userEvent.upload(input, new File(['img'], 'me.jpg', { type: 'image/jpeg' }));
    fireEvent.submit(input.closest('form')); // jsdom's required-file validation blocks a simulated click
    await waitFor(() => expect(mocks.uploadOnboardingPhoto).toHaveBeenCalled());
    expect(await screen.findByText('More than one face is visible. Use a photo of only you. 4 attempts left.')).toBeTruthy();
    expect(screen.getByLabelText(/JPEG, PNG or WebP/)).toBeTruthy();
  });

  it('offers the live selfie once the photograph is accepted and handles a blocked camera', async () => {
    mocks.onboarding.mockResolvedValue({ data: photoStage({ consent_given: true, status: 'photo_accepted' }) });
    navigator.mediaDevices = { getUserMedia: vi.fn().mockRejectedValue(Object.assign(new Error('no'), { name: 'NotAllowedError' })) };
    renderOnboarding();
    expect(await screen.findByLabelText(/Replace photograph/)).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: /start live selfie/i }));
    expect(await screen.findByText(/Camera access was blocked/)).toBeTruthy();
    delete navigator.mediaDevices;
  });

  it('stops the camera when the user leaves the step', async () => {
    mocks.onboarding.mockResolvedValue({ data: photoStage({ consent_given: true, status: 'photo_accepted' }) });
    const track = { stop: vi.fn() };
    navigator.mediaDevices = { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) };
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue();
    const view = renderOnboarding();
    fireEvent.click(await screen.findByRole('button', { name: /start live selfie/i }));
    expect(await screen.findByLabelText('Camera preview')).toBeTruthy();
    view.unmount();
    expect(track.stop).toHaveBeenCalled();
    delete navigator.mediaDevices;
  });
});
