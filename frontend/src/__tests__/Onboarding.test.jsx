import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ onboarding: vi.fn(), onboardingAction: vi.fn(), updateOnboardingStatus: vi.fn(), logout: vi.fn() }));
vi.mock('../api/services.js', () => ({ authApi: { onboarding: mocks.onboarding, onboardingAction: mocks.onboardingAction } }));
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
