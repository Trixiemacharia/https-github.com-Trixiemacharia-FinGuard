import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  goals: vi.fn(), schedules: vi.fn(), createGoal: vi.fn(), updateGoal: vi.fn(), archiveGoal: vi.fn(), contributions: vi.fn(),
  move: vi.fn(), createSchedule: vi.fn(), updateSchedule: vi.fn(), recommendation: vi.fn(), activity: vi.fn(),
  wallet: vi.fn(), dashboard: vi.fn(),
}));
vi.mock('../api/services.js', () => ({
  savingsApi: mocks, walletApi: { get: mocks.wallet }, insightsApi: { dashboard: mocks.dashboard },
}));
import { Savings } from '../pages/Savings.jsx';
import { amountError, goalStatus, milestoneDates, milestones, requiredContribution, scheduledMonthlyCents } from '../pages/savings/logic.js';

const future = (days) => { const d = new Date(); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10); };
const GOALS = [
  { id: 'g1', name: 'Emergency fund', target_amount: '10000.00', saved_amount: '2500.00', remaining_amount: '7500.00', progress_percent: 25, target_date: future(300), priority: 0, currency: 'KES', archived_at: null, created_at: '2026-01-01T00:00:00Z' },
  { id: 'g2', name: 'Trip to Lamu', target_amount: '4000.00', saved_amount: '0.00', remaining_amount: '4000.00', progress_percent: 0, target_date: null, priority: 1, currency: 'KES', archived_at: null, created_at: '2026-02-01T00:00:00Z' },
];
const RULES = [
  { id: 'r1', goal: 'g1', goal_name: 'Emergency fund', amount: '500.00', cadence: 'monthly', start_date: '2026-01-05', status: 'authorized', next_run_date: future(10), last_run_at: null, last_run_status: '' },
  { id: 'r2', goal: 'g2', goal_name: 'Trip to Lamu', amount: '100.00', cadence: 'weekly', start_date: '2026-03-01', status: 'paused', next_run_date: null, last_run_at: null, last_run_status: '' },
  { id: 'r3', goal: 'g2', goal_name: 'Trip to Lamu', amount: '50.00', cadence: 'weekly', start_date: future(3), status: 'draft', next_run_date: null, last_run_at: null, last_run_status: '' },
];

function setup({ goals = GOALS, rules = RULES, wallet = { balance: '3000.00', currency: 'KES', is_frozen: false }, activity } = {}) {
  mocks.goals.mockResolvedValue({ data: goals });
  mocks.schedules.mockResolvedValue({ data: rules });
  mocks.wallet.mockResolvedValue({ data: wallet });
  mocks.activity.mockResolvedValue({ data: activity || { count: 0, results: [], page: 1, pages: 1, totals: { contributed: '0.00', withdrawn: '0.00', net: '0.00' } } });
  mocks.recommendation.mockResolvedValue({ data: { available: false } });
  mocks.dashboard.mockResolvedValue({ data: { kpis: { expenses: '30000.00', outgoing_count: 12 }, period: { days: 92 } } });
  mocks.contributions.mockResolvedValue({ data: [] });
  return render(<Savings />);
}
const overview = async () => (await screen.findByLabelText('Savings overview'));
beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);

describe('Savings page', () => {
  it('separates savings from the wallet balance using real records', async () => {
    setup();
    const o = await overview();
    expect(within(o).getByText('KSh 2,500.00')).toBeTruthy();        // total savings
    expect(within(o).getByText('KSh 3,000.00')).toBeTruthy();        // wallet, separate
    expect(within(o).getByText('KSh 11,500.00')).toBeTruthy();       // 7,500 + 4,000 remaining
    expect(within(o).getByText('2')).toBeTruthy();
  });

  it('reviews a contribution with resulting balances and only moves money on confirm', async () => {
    setup();
    mocks.move.mockResolvedValue({ data: { amount: '1000.00' } });
    await overview();
    fireEvent.click(screen.getByRole('button', { name: /move money/i }));
    const dialog = await screen.findByRole('dialog', { name: 'Move money' });
    fireEvent.change(within(dialog).getByLabelText('Savings goal'), { target: { value: 'g1' } });
    fireEvent.change(within(dialog).getByLabelText('Amount (KSh)'), { target: { value: '1000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    const review = await screen.findByRole('dialog', { name: 'Review movement' });
    expect(within(review).getByText('KSh 2,000.00')).toBeTruthy(); // wallet after
    expect(within(review).getByText('KSh 3,500.00')).toBeTruthy(); // goal after
    expect(mocks.move).not.toHaveBeenCalled();
    fireEvent.click(within(review).getByRole('button', { name: 'Confirm contribution' }));
    await screen.findByRole('dialog', { name: 'Movement complete' });
    expect(mocks.move).toHaveBeenCalledWith('g1', { amount: '1000.00', direction: 'contribution' }, expect.any(String));
  });

  it('blocks amounts above the wallet or goal balance before review', async () => {
    setup();
    await overview();
    fireEvent.click(screen.getByRole('button', { name: /move money/i }));
    let dialog = await screen.findByRole('dialog', { name: 'Move money' });
    fireEvent.change(within(dialog).getByLabelText('Savings goal'), { target: { value: 'g1' } });
    fireEvent.change(within(dialog).getByLabelText('Amount (KSh)'), { target: { value: '5000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    expect(await within(dialog).findByText(/more than your available wallet balance/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('radio', { name: /withdraw/i }));
    dialog = screen.getByRole('dialog', { name: 'Move money' });
    expect(within(dialog).queryByText(/Trip to Lamu/)).toBeNull(); // nothing to withdraw from an empty goal
    fireEvent.change(within(dialog).getByLabelText('Savings goal'), { target: { value: 'g1' } });
    fireEvent.change(within(dialog).getByLabelText('Amount (KSh)'), { target: { value: '2600' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    expect(await within(dialog).findByText(/withdraw at most KSh 2,500.00/)).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Review movement' })).toBeNull();
  });

  it('retries a failed movement with the same idempotency key', async () => {
    setup();
    mocks.move.mockRejectedValueOnce(new Error('Network error')).mockResolvedValueOnce({ data: { amount: '100.00' } });
    await overview();
    fireEvent.click(screen.getByRole('button', { name: /move money/i }));
    const dialog = await screen.findByRole('dialog', { name: 'Move money' });
    fireEvent.change(within(dialog).getByLabelText('Savings goal'), { target: { value: 'g1' } });
    fireEvent.change(within(dialog).getByLabelText('Amount (KSh)'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm contribution' }));
    expect(await screen.findByText(/No money was moved/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm contribution' }));
    await screen.findByRole('dialog', { name: 'Movement complete' });
    expect(mocks.move.mock.calls[0][2]).toBe(mocks.move.mock.calls[1][2]);
  });

  it('creates a goal with validation', async () => {
    setup();
    mocks.createGoal.mockResolvedValue({ data: { id: 'g3', name: 'Laptop' } });
    await overview();
    fireEvent.click(screen.getAllByRole('button', { name: /new goal/i })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'New savings goal' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create goal' }));
    expect(await within(dialog).findByText('Give the goal a name.')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('Goal name'), { target: { value: 'Laptop' } });
    fireEvent.change(within(dialog).getByLabelText('Target amount (KSh)'), { target: { value: '85000.5' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create goal' }));
    await waitFor(() => expect(mocks.createGoal).toHaveBeenCalledWith({ name: 'Laptop', target_amount: '85000.50', target_date: null }));
  });

  it('edits and archives a goal after confirmation', async () => {
    setup();
    mocks.updateGoal.mockResolvedValue({ data: { ...GOALS[0], name: 'Rainy day' } });
    mocks.archiveGoal.mockResolvedValue({ data: null });
    await overview();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Emergency fund' }));
    const edit = await screen.findByRole('dialog', { name: 'Edit goal' });
    fireEvent.change(within(edit).getByLabelText('Goal name'), { target: { value: 'Rainy day' } });
    fireEvent.click(within(edit).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(mocks.updateGoal).toHaveBeenCalledWith('g1', expect.objectContaining({ name: 'Rainy day' })));
    fireEvent.click(await screen.findByRole('button', { name: 'Archive Emergency fund' }));
    const confirm = await screen.findByRole('dialog', { name: 'Archive Emergency fund?' });
    expect(within(confirm).getByText(/1 active automatic rule is paused/)).toBeTruthy();
    fireEvent.click(within(confirm).getByRole('button', { name: 'Archive goal' }));
    await waitFor(() => expect(mocks.archiveGoal).toHaveBeenCalledWith('g1'));
  });

  it('distinguishes active, paused and draft rules and confirms pause/resume/authorize', async () => {
    setup();
    mocks.updateSchedule.mockResolvedValue({ data: { next_run_date: future(7) } });
    await overview();
    expect(screen.getByText('1 active')).toBeTruthy();
    expect(screen.getByText('1 paused')).toBeTruthy();
    expect(screen.getByText('1 draft')).toBeTruthy();
    expect(screen.getByText('Not authorized: will never run')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /pause/i }));
    fireEvent.click(within(await screen.findByRole('dialog', { name: 'Pause rule' })).getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(mocks.updateSchedule).toHaveBeenCalledWith('r1', { action: 'pause' }));
    fireEvent.click(screen.getByRole('button', { name: /resume/i }));
    const resume = await screen.findByRole('dialog', { name: 'Resume rule' });
    expect(within(resume).getByText(/not/)).toBeTruthy();
    fireEvent.click(within(resume).getByRole('button', { name: 'Resume and authorize' }));
    await waitFor(() => expect(mocks.updateSchedule).toHaveBeenCalledWith('r2', { authorize: true }));
  });

  it('saves a new rule as a draft unless the authorization box is ticked', async () => {
    setup();
    mocks.createSchedule.mockResolvedValue({ data: { status: 'draft' } });
    await overview();
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }));
    let dialog = await screen.findByRole('dialog', { name: 'New automatic savings rule' });
    fireEvent.change(within(dialog).getByLabelText('Amount per run (KSh)'), { target: { value: '250' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save as draft' }));
    await waitFor(() => expect(mocks.createSchedule).toHaveBeenLastCalledWith(expect.objectContaining({ amount: '250.00', authorize: false })));
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }));
    dialog = await screen.findByRole('dialog', { name: 'New automatic savings rule' });
    fireEvent.change(within(dialog).getByLabelText('Amount per run (KSh)'), { target: { value: '250' } });
    fireEvent.click(within(dialog).getByRole('checkbox'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save and authorize' }));
    await waitFor(() => expect(mocks.createSchedule).toHaveBeenLastCalledWith(expect.objectContaining({ authorize: true })));
  });

  it('shows an empty activity state and filters on the server', async () => {
    setup();
    expect(await screen.findByText('No savings activity yet')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Transaction type'), { target: { value: 'withdrawal' } });
    await waitFor(() => expect(mocks.activity).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'withdrawal', page: 1 })));
    expect(await screen.findByText('No activity matches these filters')).toBeTruthy();
  });

  it('shows the empty goals state for a new user', async () => {
    setup({ goals: [], rules: [] });
    expect(await screen.findByText('No savings goals yet')).toBeTruthy();
    expect(screen.getByText('No automatic savings rules')).toBeTruthy();
  });
});

describe('savings calculations', () => {
  it('validates amounts', () => {
    expect(amountError('')).toBeTruthy(); expect(amountError('0')).toBeTruthy(); expect(amountError('1.234')).toBeTruthy();
    expect(amountError('-5')).toBeTruthy(); expect(amountError('1500.5')).toBeNull();
  });
  it('computes required contributions per day, week and month', () => {
    const r = requiredContribution(36525, '2026-12-31', '2025-12-31'); // KSh 365.25 over 365 days
    expect(r).toMatchObject({ days: 365, daily: 101, weekly: 701, monthly: 3046 });
    expect(requiredContribution(1000, null)).toBeNull();
    expect(requiredContribution(1000, '2025-01-01', '2025-02-01').days).toBeLessThan(0);
  });
  it('marks milestones and the dates they were reached', () => {
    expect(milestones('5000.00', '10000.00').map((m) => m.reached)).toEqual([true, true, false, false]);
    const dates = milestoneDates([
      { created_at: '2026-01-01', direction: 'contribution', amount: '3000' },
      { created_at: '2026-02-01', direction: 'withdrawal', amount: '1000' },
      { created_at: '2026-03-01', direction: 'contribution', amount: '4000' },
    ], '8000');
    expect(dates).toEqual({ 25: '2026-01-01', 50: '2026-03-01', 75: '2026-03-01' });
  });
  it('derives goal status from rules and dates', () => {
    const base = { id: 'x', archived_at: null, saved_amount: '0.00', target_amount: '1200.00', remaining_amount: '1200.00', target_date: '2027-01-01' };
    const rule = (amount) => [{ goal: 'x', status: 'authorized', cadence: 'monthly', amount }];
    expect(goalStatus(base, rule('200.00'), '2026-01-01')).toBe('on_track');
    expect(goalStatus(base, rule('50.00'), '2026-01-01')).toBe('behind');
    expect(goalStatus(base, [], '2027-02-01')).toBe('overdue');
    expect(goalStatus({ ...base, saved_amount: '1200.00' }, [], '2026-01-01')).toBe('completed');
    expect(scheduledMonthlyCents([{ goal: 'x', status: 'authorized', cadence: 'weekly', amount: '120.00' }, { goal: 'x', status: 'draft', cadence: 'weekly', amount: '999' }], 'x')).toBe(52000);
  });
});
