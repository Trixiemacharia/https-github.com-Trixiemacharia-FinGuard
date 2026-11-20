import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ onboarding: vi.fn(), onboardingAction: vi.fn(), login: vi.fn(),
  googleNonce: vi.fn(() => Promise.reject(Object.assign(new Error('not configured'), { status: 503 }))) }));
vi.mock('../api/services.js', () => ({
  authApi: { onboarding: mocks.onboarding, onboardingAction: mocks.onboardingAction, login: mocks.login, googleNonce: mocks.googleNonce },
  identityApi: {},
}));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ updateOnboardingStatus: vi.fn(), logout: vi.fn(), acceptSession: vi.fn() }) }));
import { BackButton } from '../components/BackButton.jsx';
import { Onboarding } from '../pages/Onboarding.jsx';
import { Login } from '../pages/Auth.jsx';
import * as Icons from '../components/icons/FinIcons.jsx';

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('BackButton', () => {
  it('returns to the previous page when there is history', () => {
    render(<MemoryRouter initialEntries={['/first', '/second']} initialIndex={1}><Routes>
      <Route path="/first" element={<div>First page</div>} />
      <Route path="/second" element={<BackButton />} />
    </Routes></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('First page')).toBeTruthy();
  });

  it('goes to the fallback page when opened directly', () => {
    render(<MemoryRouter initialEntries={['/only']}><Routes>
      <Route path="/" element={<div>Home page</div>} />
      <Route path="/only" element={<BackButton fallback="/" />} />
    </Routes></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('Home page')).toBeTruthy();
  });
});

describe('back navigation in sign-in and onboarding', () => {
  it('lets the user leave the MFA step and use a different account', async () => {
    mocks.login.mockResolvedValue({ data: { mfa_required: true, mfa_token: 't' } });
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: 'amina' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /^sign in/i }));
    fireEvent.click(await screen.findByRole('button', { name: /use a different account/i }));
    expect(screen.getByLabelText(/email or username/i)).toBeTruthy();
  });

  it('lets the user go back from email verification to change the phone number', async () => {
    mocks.onboarding.mockResolvedValue({ data: { status: 'email_pending', email: 'a@example.com', phone_number: '+254712345678' } });
    render(<MemoryRouter initialEntries={['/onboarding']}><Routes><Route path="/onboarding" element={<Onboarding />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /change phone number/i }));
    expect(screen.getByLabelText(/phone number/i).value).toBe('+254712345678');
    fireEvent.click(screen.getByRole('button', { name: /back to email verification/i }));
    expect(screen.getByRole('heading', { name: /verify your email address/i })).toBeTruthy();
  });
});

describe('FinGuard iconography', () => {
  it('renders every icon as a decorative 24px-grid SVG', () => {
    const names = Object.keys(Icons);
    expect(names.length).toBeGreaterThanOrEqual(15);
    const { container } = render(<div>{names.map((n) => { const Icon = Icons[n]; return <Icon key={n} size={18} />; })}</div>);
    const svgs = container.querySelectorAll('svg.fin-icon');
    expect(svgs.length).toBe(names.length);
    svgs.forEach((svg) => { expect(svg.getAttribute('viewBox')).toBe('0 0 24 24'); expect(svg.getAttribute('aria-hidden')).toBe('true'); });
  });
});
