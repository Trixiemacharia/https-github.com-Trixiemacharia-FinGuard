import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  dashboard: vi.fn(), categoryTransactions: vi.fn(), categorize: vi.fn(), upcoming: vi.fn(), calendar: vi.fn(),
  detectRecurring: vi.fn(), detectionStatus: vi.fn(), updateRecurring: vi.fn(),
  addCalendarEntry: vi.fn(), updateCalendarEntry: vi.fn(), deleteCalendarEntry: vi.fn(),
}));
vi.mock('../api/services.js', () => ({ insightsApi: mocks }));
vi.mock('../hooks/useChart.js', () => ({ useChart: () => ({ current: null }) }));
import { Insights } from '../pages/Insights.jsx';
import { buildCsv } from '../pages/insights/exportReport.js';

const cmp = (current, previous, change) => ({ current, previous, change_percent: change });
function dashboardData(overrides = {}) {
  return {
    currency: 'KES', generated_at: '2026-11-17T10:00:00Z',
    period: { key: 'last_30_days', from: '2026-10-19', to: '2026-11-17', days: 30, granularity: 'day', previous_from: '2026-09-19', previous_to: '2026-10-18', timezone: 'Africa/Nairobi' },
    kpis: { income: '52000.00', expenses: '5000.00', net_cash_flow: '47000.00', transactions: 5, incoming_count: 2, outgoing_count: 3,
      average_transaction_value: '11400.00', average_outgoing_value: '1666.67', savings_rate: '90.38',
      largest_outgoing: { id: 't3', amount: '3000.00', date: '2026-11-11', category: 'housing', description: 'Rent' } },
    comparison: { income: cmp('52000.00', '40000.00', '30.00'), expenses: cmp('5000.00', '999.00', '400.50'), net_cash_flow: cmp('47000.00', '39001.00', '20.51'), transactions: cmp(5, 2, '150.00') },
    series: [{ start: '2026-11-16', end: '2026-11-16', income: '52000.00', expenses: '5000.00', net: '47000.00' }],
    categories: [
      { category: 'housing', amount: '3000.00', count: 1, share_percent: '60.00', previous_amount: '0.00', change_percent: null },
      { category: 'groceries', amount: '2000.00', count: 2, share_percent: '40.00', previous_amount: '999.00', change_percent: '100.20' },
    ],
    patterns: { available: true, highest_category: { category: 'housing', amount: '3000.00', share_percent: '60.00' },
      largest_transaction: { amount: '3000.00', description: 'Rent', date: '2026-11-11' }, average_outgoing_value: '1666.67',
      most_active_weekday: { weekday: 'Monday', amount: '3000.00', count: 1 },
      expense_change: { change_percent: '400.50' }, category_changes: [{ category: 'housing', change: '3000.00' }] },
    anomalies: { available: false, rule: 'Rule text.', reason: 'Needs at least 8 completed payments; found 3.', items: [] },
    recurring: { items: [], confirmed_count: 0, suggested_count: 0, detection_rule: 'Same description and amount in 3 months.' },
    forecast: { available: false, reason: 'Forecasting needs two complete months of wallet history.', period: { from: '2026-11-17', to: '2026-12-17' }, confirmed_obligations: [], confirmed_obligations_total: '0.00' },
    monthly_reports: [
      { month: '2026-11', from: '2026-11-01', to: '2026-11-17', partial: true, income: '52000.00', expenses: '4000.00', net_cash_flow: '48000.00', transactions: 4 },
      { month: '2026-10', from: '2026-10-19', to: '2026-10-31', partial: true, income: '0.00', expenses: '1000.00', net_cash_flow: '-1000.00', transactions: 1 },
    ],
    data_rules: ['Only completed transactions are counted.'],
    ...overrides,
  };
}

function setup(data = dashboardData()) {
  mocks.dashboard.mockResolvedValue({ data });
  mocks.upcoming.mockResolvedValue({ data: { occurrences: [], status_rule: 'rule' } });
  mocks.calendar.mockResolvedValue({ data: { entries: [] } });
  return render(<MemoryRouter><Insights /></MemoryRouter>);
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Insights dashboard', () => {
  it('shows KPI figures exactly as calculated by the backend', async () => {
    setup();
    const income = (await screen.findByText('Total income', { selector: '.ins-kpi-label' })).closest('article');
    expect(within(income).getByText('KSh 52,000.00')).toBeTruthy();
    expect(within(income).getByText('+30.0%')).toBeTruthy();
    const net = screen.getByText('Net cash flow', { selector: '.ins-kpi-label' }).closest('article');
    expect(within(net).getByText('KSh 47,000.00')).toBeTruthy();
    expect(within(net).getByText('Income exceeded spending')).toBeTruthy();
    expect(mocks.dashboard).toHaveBeenCalledWith({ period: 'last_30_days' });
  });

  it('changes the reporting period and applies a custom range', async () => {
    setup();
    await screen.findByText('Total income', { selector: '.ins-kpi-label' });
    fireEvent.change(screen.getByLabelText('Reporting period'), { target: { value: 'last_6_months' } });
    await waitFor(() => expect(mocks.dashboard).toHaveBeenLastCalledWith({ period: 'last_6_months' }));
    fireEvent.change(screen.getByLabelText('Reporting period'), { target: { value: 'custom' } });
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-03-31' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(mocks.dashboard).toHaveBeenLastCalledWith({ period: 'custom', from: '2026-01-01', to: '2026-03-31' }));
  });

  it('shows empty states, never sample figures, when there is no activity', async () => {
    const zero = { income: '0.00', expenses: '0.00', net_cash_flow: '0.00', transactions: 0, incoming_count: 0, outgoing_count: 0, average_transaction_value: null, average_outgoing_value: null, savings_rate: null, largest_outgoing: null };
    setup(dashboardData({ kpis: zero, categories: [], patterns: { available: false }, series: [], monthly_reports: [{ month: '2026-11', from: '2026-11-01', to: '2026-11-17', partial: true, income: '0.00', expenses: '0.00', net_cash_flow: '0.00', transactions: 0 }],
      comparison: { income: cmp('0.00', '0.00', null), expenses: cmp('0.00', '0.00', null), net_cash_flow: cmp('0.00', '0.00', null), transactions: cmp(0, 0, null) } }));
    expect((await screen.findAllByText('No completed transactions in this period')).length).toBeGreaterThan(0);
    expect(screen.getByText('No outgoing transactions in this period')).toBeTruthy();
    expect(screen.getByText('No recurring payments detected')).toBeTruthy();
    expect(screen.getByText('Not enough history to forecast')).toBeTruthy();
    expect(screen.queryByText(/52,000/)).toBeNull();
  });

  it('opens a category drill-down and persists a category correction', async () => {
    setup();
    mocks.categoryTransactions.mockResolvedValue({ data: { transactions: [{ id: 't9', description: 'Supermarket', amount: '1200.00', created_at: '2026-11-10T08:00:00Z', category: 'groceries', is_manual: false }] } });
    mocks.categorize.mockResolvedValue({ data: {} });
    const table = (await screen.findAllByRole('table'))[0];
    fireEvent.click(within(table).getByText('Groceries'));
    await waitFor(() => expect(mocks.categoryTransactions).toHaveBeenCalledWith({ from: '2026-10-19', to: '2026-11-17', category: 'groceries' }));
    fireEvent.change(await screen.findByLabelText('Category for Supermarket'), { target: { value: 'health' } });
    await waitFor(() => expect(mocks.categorize).toHaveBeenCalledWith('t9', 'health'));
    await waitFor(() => expect(mocks.dashboard.mock.calls.length).toBeGreaterThan(1));
  });

  it('renders the monthly table with negative net cash flow formatting', async () => {
    setup();
    expect(await screen.findByText('−KSh 1,000.00')).toBeTruthy();
    expect(screen.getByText('November 2026')).toBeTruthy();
  });
});

describe('CSV export', () => {
  it('contains exactly the figures shown on the dashboard', () => {
    const csv = buildCsv(dashboardData());
    expect(csv).toContain('Total income,52000.00,40000.00,30.00');
    expect(csv).toContain('2026-11,2026-11-01,2026-11-17,52000.00,4000.00,48000.00,4,yes');
    expect(csv).toContain('Housing,3000.00,60.00,0.00,');
  });
});
