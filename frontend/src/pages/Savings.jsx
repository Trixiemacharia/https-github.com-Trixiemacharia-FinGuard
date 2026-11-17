import { useCallback, useEffect, useState } from 'react';
import { PiggyBank, Plus, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { savingsApi, walletApi } from '../api/services.js';
import { Empty, ErrorState, Loading, PageTitle, StatusPill } from '../components/Feedback.jsx';
import { formatMoney, formatWhen } from '../utils/format.js';
import './savings.css';

const isoDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const idempotencyKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export function Savings() {
  const [goals, setGoals] = useState([]); const [schedules, setSchedules] = useState([]); const [activity, setActivity] = useState([]);
  const [wallet, setWallet] = useState(null); const [recommendation, setRecommendation] = useState(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false); const [goalFormOpen, setGoalFormOpen] = useState(false);
  const [goalForm, setGoalForm] = useState({ name: '', target_amount: '', target_date: '' });
  const [moveForm, setMoveForm] = useState({ goal: '', amount: '', direction: 'contribution' });
  const [scheduleForm, setScheduleForm] = useState({ goal: '', amount: '', cadence: 'monthly', start_date: isoDate(), authorize: false });
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [goalResult, scheduleResult, walletResult, recommendationResult] = await Promise.all([
        savingsApi.goals(), savingsApi.schedules(), walletApi.get(), savingsApi.recommendation(),
      ]);
      const goalRows = goalResult.data.results || goalResult.data;
      setGoals(goalRows); setSchedules(scheduleResult.data.results || scheduleResult.data); setWallet(walletResult.data); setRecommendation(recommendationResult.data);
      const histories = await Promise.all(goalRows.map(async (goal) => {
        const { data } = await savingsApi.contributions(goal.id);
        return (data || []).map((item) => ({ ...item, goal_name: goal.name }));
      }));
      setActivity(histories.flat().sort((a, b) => new Date(b.created_at) - new Date(a.created_at)));
      setMoveForm((current) => ({ ...current, goal: current.goal || goalRows.find((goal) => !goal.archived_at)?.id || '' }));
      setScheduleForm((current) => ({ ...current, goal: current.goal || goalRows.find((goal) => !goal.archived_at)?.id || '' }));
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function createGoal(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try { await savingsApi.createGoal({ ...goalForm, target_date: goalForm.target_date || null }); setGoalForm({ name: '', target_amount: '', target_date: '' }); setGoalFormOpen(false); setMessage('Savings goal created.'); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function move(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const { data } = await savingsApi.move(moveForm.goal, { amount: moveForm.amount, direction: moveForm.direction }, idempotencyKey());
      setMessage(`${moveForm.direction === 'contribution' ? 'Contribution saved' : 'Withdrawal completed'}: ${formatMoney(data.amount, wallet?.currency)}.`);
      setMoveForm((current) => ({ ...current, amount: '' })); await load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function createSchedule(event) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const body = { goal: scheduleForm.goal, amount: scheduleForm.amount, cadence: scheduleForm.cadence, start_date: scheduleForm.start_date, authorize: scheduleForm.authorize };
      await savingsApi.createSchedule(body);
      setMessage(scheduleForm.authorize ? 'Automatic rule enabled. It will run on its start date.' : 'Draft rule saved. It will not move money until you enable it.');
      setScheduleForm((current) => ({ ...current, amount: '', authorize: false })); await load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function scheduleAction(schedule, action) {
    setBusy(true); setError(''); setMessage('');
    try {
      if (action === 'authorize' && !window.confirm(`Enable the ${schedule.cadence} ${formatMoney(schedule.amount, wallet?.currency)} rule for ${schedule.goal_name || 'this goal'}? It may move money on its next run.`)) return;
      await savingsApi.updateSchedule(schedule.id, action === 'authorize' ? { authorize: true } : { action });
      setMessage(action === 'authorize' ? 'Automatic rule enabled.' : `Automatic rule ${action}d.`); await load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function archive(goal) {
    if (!window.confirm(`Archive “${goal.name}”? Its savings balance will remain recorded.`)) return;
    setBusy(true); setError('');
    try { await savingsApi.archiveGoal(goal.id); setMessage('Goal archived. Its saved balance remains recorded.'); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return <><PageTitle eyebrow="PLAN WITH PURPOSE" title="Savings" detail="Track goals and choose exactly when an automatic rule is enabled." action={<button className="icon-text-button" onClick={load}><RefreshCw size={14} /> Refresh</button>} />
    {message && <div className="success-banner"><ShieldCheck size={16} /> {message}<button onClick={() => setMessage('')} aria-label="Dismiss">×</button></div>}
    {loading ? <Loading label="Loading savings" /> : error && !wallet ? <ErrorState error={error} onRetry={load} /> : <>
      {error && <ErrorState error={error} onRetry={load} />}
      <div className="notice-card"><PiggyBank size={18} /><div><strong>Available wallet balance: {formatMoney(wallet?.balance, wallet?.currency)}</strong><p>Contributions move funds from your wallet balance into a separately tracked savings balance. Frozen wallets and insufficient balances are blocked.</p></div></div>
      <section className="section-heading spaced"><div><h2>Your goals</h2><p>Progress is calculated from completed savings contributions and withdrawals.</p></div><button className="primary-button" onClick={() => setGoalFormOpen(!goalFormOpen)}><Plus size={16} /> New goal</button></section>
      {goalFormOpen && <form className="inline-form" onSubmit={createGoal}><label>Goal name<input maxLength="80" required value={goalForm.name} onChange={(e) => setGoalForm({ ...goalForm, name: e.target.value })} /></label><label>Target amount<input type="number" min="0.01" step="0.01" required value={goalForm.target_amount} onChange={(e) => setGoalForm({ ...goalForm, target_amount: e.target.value })} /></label><label>Target date (optional)<input type="date" value={goalForm.target_date} onChange={(e) => setGoalForm({ ...goalForm, target_date: e.target.value })} /></label><button className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Create goal'}</button></form>}
      {!goals.length ? <Empty title="No savings goals yet" detail="Create a goal to start tracking progress." /> : <div className="beneficiary-grid">{goals.map((goal) => <article className="beneficiary-card savings-goal-card" key={goal.id}><div className="beneficiary-avatar"><PiggyBank size={18} /></div><div className="beneficiary-info"><strong>{goal.name}</strong><span>{formatMoney(goal.saved_amount, goal.currency)} of {formatMoney(goal.target_amount, goal.currency)}</span><small>{goal.target_date ? `Target ${goal.target_date}` : 'No target date'}</small></div><div className="savings-progress" role="progressbar" aria-valuenow={goal.progress_percent} aria-valuemin="0" aria-valuemax="100"><span style={{ width: `${goal.progress_percent}%` }} /></div><small>{goal.progress_percent}% complete{goal.archived_at ? ' · archived' : ''}</small>{!goal.archived_at && <button className="text-button" disabled={busy} onClick={() => archive(goal)}>Archive</button>}</article>)}</div>}
      {recommendation && <div className="notice-card"><Sparkles size={18} /><div><strong>{recommendation.available ? `Suggested contribution: ${formatMoney(recommendation.suggested_amount, recommendation.currency)}` : 'No recommendation available yet'}</strong><p>{recommendation.assumptions.method}. Period {recommendation.assumptions.period_from} to (not including) {recommendation.assumptions.period_to_exclusive}; {recommendation.assumptions.completed_deposits} completed deposits across {recommendation.assumptions.months_in_average} months. {recommendation.assumptions.cap}. {recommendation.assumptions.action} {recommendation.reason || ''}</p>{recommendation.available && <button className="text-button" onClick={() => setMoveForm((current) => ({ ...current, direction: 'contribution', amount: recommendation.suggested_amount }))}>Use amount in contribution form</button>}</div></div>}
      <section className="section-heading spaced"><div><h2>Move savings</h2><p>Each movement is checked against your wallet and goal balances.</p></div></section>
      {!goals.some((goal) => !goal.archived_at || (moveForm.direction === 'withdrawal' && Number(goal.saved_amount) > 0)) ? <Empty title="Create a goal before moving savings" /> : <form className="inline-form" onSubmit={move}><label>Goal<select required value={moveForm.goal} onChange={(e) => setMoveForm({ ...moveForm, goal: e.target.value })}>{goals.filter((goal) => moveForm.direction === 'withdrawal' ? Number(goal.saved_amount) > 0 : !goal.archived_at).map((goal) => <option key={goal.id} value={goal.id}>{goal.name}{goal.archived_at ? ' (archived)' : ''}</option>)}</select></label><label>Movement<select value={moveForm.direction} onChange={(e) => setMoveForm({ ...moveForm, direction: e.target.value })}><option value="contribution">Contribute</option><option value="withdrawal">Withdraw</option></select></label><label>Amount<input type="number" min="0.01" step="0.01" required value={moveForm.amount} onChange={(e) => setMoveForm({ ...moveForm, amount: e.target.value })} /></label><button className="primary-button" disabled={busy}>{busy ? 'Processing…' : moveForm.direction === 'contribution' ? 'Contribute' : 'Withdraw'}</button></form>}
      <section className="section-heading spaced"><div><h2>Automatic rules</h2><p>Draft rules never run. Enabling one authorizes future contributions at the selected cadence.</p></div></section>
      <form className="inline-form" onSubmit={createSchedule}><label>Goal<select required value={scheduleForm.goal} onChange={(e) => setScheduleForm({ ...scheduleForm, goal: e.target.value })}>{goals.filter((goal) => !goal.archived_at).map((goal) => <option key={goal.id} value={goal.id}>{goal.name}</option>)}</select></label><label>Amount per run<input type="number" min="0.01" step="0.01" required value={scheduleForm.amount} onChange={(e) => setScheduleForm({ ...scheduleForm, amount: e.target.value })} /></label><label>Cadence<select value={scheduleForm.cadence} onChange={(e) => setScheduleForm({ ...scheduleForm, cadence: e.target.value })}><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></label><label>Start date<input type="date" required value={scheduleForm.start_date} onChange={(e) => setScheduleForm({ ...scheduleForm, start_date: e.target.value })} /></label><label className="checkbox-label"><input type="checkbox" checked={scheduleForm.authorize} onChange={(e) => setScheduleForm({ ...scheduleForm, authorize: e.target.checked })} /> Enable automatic contributions</label><button className="primary-button" disabled={busy}>{busy ? 'Saving…' : scheduleForm.authorize ? 'Create and enable rule' : 'Save draft rule'}</button></form>
      {!schedules.length ? <Empty title="No automatic rules" detail="Create a draft or explicitly enable an automatic contribution rule." /> : <div className="transaction-list">{schedules.map((schedule) => <article className="transaction-row" key={schedule.id}><div className="transaction-main"><strong>{schedule.goal_name || goals.find((goal) => goal.id === schedule.goal)?.name} · {formatMoney(schedule.amount, wallet?.currency)} {schedule.cadence}</strong><small>Next run: {schedule.next_run_date || 'not enabled'}{schedule.last_run_at ? ` · Last run ${formatWhen(schedule.last_run_at)}` : ''}{schedule.last_run_status ? ` · ${schedule.last_run_status}` : ''}</small></div><StatusPill value={schedule.status} />{schedule.status === 'draft' || schedule.status === 'paused' ? <button className="secondary-button" disabled={busy} onClick={() => scheduleAction(schedule, 'authorize')}>Enable</button> : schedule.status === 'authorized' ? <button className="secondary-button" disabled={busy} onClick={() => scheduleAction(schedule, 'pause')}>Pause</button> : null}{schedule.status !== 'cancelled' && <button className="text-button" disabled={busy} onClick={() => scheduleAction(schedule, 'cancel')}>Cancel</button>}</article>)}</div>}
      <section className="section-heading spaced"><div><h2>Contribution history</h2><p>Completed contributions and withdrawals for your goals.</p></div></section>
      {!activity.length ? <Empty title="No savings movements yet" detail="Contributions and withdrawals will be listed here." /> : <div className="transaction-list">{activity.map((item) => <article className="transaction-row" key={item.id}><div className="transaction-main"><strong>{item.goal_name}</strong><small>{formatWhen(item.created_at)} · {item.direction}</small></div><span>{formatMoney(item.amount, wallet?.currency)}</span></article>)}</div>}
    </>}
  </>;
}
