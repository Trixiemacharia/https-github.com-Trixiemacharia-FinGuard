import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ login: vi.fn(), verifyMfa: vi.fn(), acceptSession: vi.fn() }));
vi.mock('../api/services.js', () => ({ authApi: { login: mocks.login, verifyMfa: mocks.verifyMfa } }));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ acceptSession: mocks.acceptSession }) }));
import { Login } from '../pages/Auth.jsx';

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
