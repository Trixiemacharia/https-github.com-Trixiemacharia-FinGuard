import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ login: vi.fn(), verifyMfa: vi.fn(), acceptSession: vi.fn(), googleLogin: vi.fn(), nonce: vi.fn() }));
vi.mock('../api/services.js', () => ({
  authApi: { login: mocks.login, verifyMfa: mocks.verifyMfa, googleLogin: mocks.googleLogin },
  // Google is not configured in these password tests unless a test says otherwise.
  onboardingApi: { nonce: mocks.nonce },
}));
const google = vi.hoisted(() => ({ credential: null }));
vi.mock('../components/GoogleButton.jsx', () => ({
  GoogleButton: ({ onCredential }) => <button type="button" onClick={() => onCredential(google.credential)}>Sign in with Google</button>,
}));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ acceptSession: mocks.acceptSession }) }));
import { Login } from '../pages/Auth.jsx';

afterEach(() => { cleanup(); vi.clearAllMocks(); });
beforeEach(() => { mocks.nonce.mockRejectedValue({ data: { code: 'google_not_configured' } }); });

describe('login flow', () => {
  it('submits credentials and accepts the returned session', async () => {
    mocks.login.mockResolvedValue({ data: { user: { id: 8, username: 'amina' }, access: 'access-token' } });
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: 'amina@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-passphrase' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith({ identifier: 'amina@example.com', password: 'secret-passphrase' }));
    expect(mocks.acceptSession).toHaveBeenCalledWith({ user: { id: 8, username: 'amina' }, access: 'access-token' });
  });

  it('moves to the OTP form when the backend requires MFA', async () => {
    mocks.login.mockResolvedValue({ data: { mfa_required: true, mfa_token: 'short-lived-challenge' } });
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: 'amina' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-passphrase' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByLabelText(/one-time code/i)).toBeTruthy();
  });

  it('shows server errors without accepting a session', async () => {
    mocks.login.mockRejectedValue(new Error('Invalid username/email or password.'));
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: 'amina' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect((await screen.findByRole('alert')).textContent).toContain('Invalid username/email or password.');
    expect(mocks.acceptSession).not.toHaveBeenCalled();
  });
});

describe('Google sign-in for existing accounts', () => {
  it('signs in an existing Google account', async () => {
    mocks.nonce.mockResolvedValue({ data: { nonce: 'n1', client_id: 'cid' } });
    mocks.googleLogin.mockResolvedValue({ data: { user: { id: 3 }, access: 'a' } });
    google.credential = 'id-token';
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Google' }));
    await waitFor(() => expect(mocks.acceptSession).toHaveBeenCalledWith({ user: { id: 3 }, access: 'a' }));
    expect(mocks.googleLogin).toHaveBeenCalledWith('id-token');
  });

  it('sends a Google user without an account to verified sign-up and creates nothing', async () => {
    mocks.nonce.mockResolvedValue({ data: { nonce: 'n1', client_id: 'cid' } });
    mocks.googleLogin.mockRejectedValue({ data: { code: 'no_account' } });
    render(<MemoryRouter initialEntries={['/auth']}><Routes><Route path="/auth" element={<Login />} /><Route path="/onboarding" element={<div>Onboarding page</div>} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Google' }));
    expect(await screen.findByText('Onboarding page')).toBeTruthy();
    expect(mocks.acceptSession).not.toHaveBeenCalled();
  });
});
