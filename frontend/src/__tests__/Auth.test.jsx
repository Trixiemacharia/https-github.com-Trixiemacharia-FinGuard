import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ login: vi.fn(), verifyMfa: vi.fn(), acceptSession: vi.fn(), register: vi.fn(), googleLogin: vi.fn(), onboarding: vi.fn(),
  // Google sign-in is not configured unless a test says otherwise, so the original pages render unchanged.
  googleNonce: vi.fn(() => Promise.reject(Object.assign(new Error('not configured'), { status: 503 }))) }));
vi.mock('../api/services.js', () => ({ authApi: { login: mocks.login, verifyMfa: mocks.verifyMfa, register: mocks.register,
  googleLogin: mocks.googleLogin, googleNonce: mocks.googleNonce, onboarding: mocks.onboarding } }));
vi.mock('../components/GoogleButton.jsx', () => ({
  GoogleButton: ({ onCredential, text }) => <button type="button" onClick={() => onCredential('google-id-token')}>{text === 'signup_with' ? 'Sign up with Google' : 'Sign in with Google'}</button>,
}));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ acceptSession: mocks.acceptSession }) }));
import { Login, Register } from '../pages/Auth.jsx';

afterEach(() => cleanup());

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

describe('Google option (step 01)', () => {
  const configured = () => mocks.googleNonce.mockResolvedValue({ data: { client_id: 'cid', nonce: 'nonce-1' } });

  it('leaves the original pages unchanged when Google is not configured', async () => {
    render(<MemoryRouter><Register /></MemoryRouter>);
    await waitFor(() => expect(mocks.googleNonce).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /with Google/i })).toBeNull();
    expect(screen.getByRole('button', { name: /create account/i })).toBeTruthy();
  });

  it('creates the account with Google using the server nonce and continues to onboarding', async () => {
    configured();
    mocks.googleLogin.mockResolvedValue({ data: { user: { id: 4 }, access: 'jwt' } });
    render(<MemoryRouter initialEntries={['/auth']}><Routes><Route path="/auth" element={<Register />} /><Route path="/onboarding" element={<div>Onboarding page</div>} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Sign up with Google' }));
    expect(await screen.findByText('Onboarding page')).toBeTruthy();
    expect(mocks.googleLogin).toHaveBeenCalledWith('google-id-token', 'nonce-1');
    expect(mocks.acceptSession).toHaveBeenCalledWith({ user: { id: 4 }, access: 'jwt' });
  });

  it('shows the server reason when Google sign-in is refused', async () => {
    configured();
    mocks.googleLogin.mockRejectedValue(Object.assign(new Error('x'), { data: { detail: 'Google hasn’t verified this account’s email address.' } }));
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Google' }));
    expect(await screen.findByText(/hasn’t verified/)).toBeTruthy();
    expect(mocks.acceptSession).not.toHaveBeenCalled();
  });
});
