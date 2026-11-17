import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ capabilities: vi.fn(), startRun: vi.fn(), run: vi.fn() }));
vi.mock('../api/services.js', () => ({ assistantApi: { capabilities: mocks.capabilities, startRun: mocks.startRun, run: mocks.run } }));
import { Assistant } from '../pages/Assistant.jsx';

const steps = (a, b, c) => [
  { key: 'understand', label: 'Understand the question', status: a },
  { key: 'analyse', label: 'Check balance, upcoming bills, savings rules and typical spending', status: b },
  { key: 'compose', label: 'Write the decision brief', status: c },
];

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Assistant', () => {
  it('shows live step statuses while polling and then the verdict, figures and scope', async () => {
    mocks.capabilities.mockResolvedValue({ data: { mode: 'read_only', language_provider_available: false } });
    mocks.startRun.mockResolvedValue({ data: { run_id: 'r1', conversation_id: 'c1', status: 'running', steps: steps('completed', 'running', 'pending') } });
    mocks.run.mockResolvedValue({ data: { run_id: 'r1', status: 'completed', steps: steps('completed', 'completed', 'completed'), result: {
      verdict: 'tight', confidence: 'medium', answer: 'Verdict: TIGHT. This analysis covers your FinGuard wallet only, not cash or other accounts.',
      steps: steps('completed', 'completed', 'completed'), provider: { phrasing: 'deterministic_template' },
      key_figures: [{ key: 'result', label: 'Left after everything (conservative)', amount: '8500.00', currency: 'KES' }],
      reasoning: { conclusion: 'Only just.', insights: [], steps: [{ text: 'Then the purchase itself.', calc: '43,500.00 − 35,000.00 = 8,500.00' }] },
      assumptions: ['Buffer = 2 x average weekly spending.'], missing_inputs: [], proposed_actions: [], citations: [], citation_count: 0,
      suggested_followups: ['What about a smaller amount?'],
    } } });
    render(<MemoryRouter><Assistant /></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText(/ask a money question/i), { target: { value: 'Can I afford 35k?' } });
    fireEvent.click(screen.getByRole('button', { name: /^ask$/i }));
    expect((await screen.findAllByText('running')).length).toBeGreaterThan(0);
    expect(await screen.findByText('Tight', {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByText(/covers your FinGuard wallet only/i)).toBeTruthy();
    expect(screen.getByText('Left after everything (conservative)')).toBeTruthy();
    expect(screen.getByText('43,500.00 − 35,000.00 = 8,500.00')).toBeTruthy();
    expect(mocks.startRun).toHaveBeenCalledWith('Can I afford 35k?', null);
  });

  it('offers no canned example questions', async () => {
    mocks.capabilities.mockResolvedValue({ data: { mode: 'read_only' } });
    render(<MemoryRouter><Assistant /></MemoryRouter>);
    await screen.findByLabelText(/ask a money question/i);
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Ask']);
  });

  it('shows the answer straight away when the run completes in the first response (no polling)', async () => {
    mocks.capabilities.mockResolvedValue({ data: { mode: 'read_only' } });
    mocks.startRun.mockResolvedValue({ data: { run_id: 'r2', conversation_id: 'c2', status: 'completed', steps: steps('completed', 'completed', 'completed'), result: {
      verdict: 'not_affordable', confidence: 'high', answer: 'Verdict: NOT AFFORDABLE. Your wallet balance is KES 25.00.', steps: steps('completed', 'completed', 'completed'),
      provider: { phrasing: 'deterministic_template' }, key_figures: [], assumptions: [], missing_inputs: [], proposed_actions: [], citations: [], citation_count: 0, suggested_followups: [],
    } } });
    render(<MemoryRouter><Assistant /></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText(/ask a money question/i), { target: { value: 'Can I afford 35k?' } });
    fireEvent.click(screen.getByRole('button', { name: /^ask$/i }));
    expect(await screen.findByText(/Your wallet balance is KES 25.00/)).toBeTruthy();
    expect(mocks.run).not.toHaveBeenCalled();
  });
});
