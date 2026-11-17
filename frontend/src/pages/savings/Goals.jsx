import { useEffect, useState } from 'react';
import { Archive, ArrowDownLeft, ArrowUpRight, CalendarDays, Eye, Pencil, PiggyBank, Repeat, Target, Wallet } from 'lucide-react';
import { savingsApi } from '../../api/services.js';
import { EmptyState, Modal, Skeleton } from '../../components/dashboard/ui.jsx';
import { day, ksh } from '../../components/dashboard/format.js';
import { amountError, fromCents, GOAL_STATUS, goalIcon, goalStatus, localToday, milestoneDates, milestones, requiredContribution, scheduledMonthlyCents, toCents } from './logic.js';

// --- overview -----------------------------------------------------------------------------------------------------

export function SavingsOverview({ goals, wallet }) {
  const active = goals.filter((g) => !g.archived_at);
  const savedCents = goals.reduce((s, g) => s + toCents(g.saved_amount), 0); // archived goals still hold money
  const activeSaved = active.reduce((s, g) => s + toCents(g.saved_amount), 0);
  const targetCents = active.reduce((s, g) => s + toCents(g.target_amount), 0);
  const remaining = active.reduce((s, g) => s + toCents(g.remaining_amount), 0);
  const progress = targetCents ? Math.min(100, (Math.min(activeSaved, targetCents) / targetCents) * 100) : 0;
  const archivedHeld = savedCents - activeSaved;
  return <section className="sv-overview" aria-label="Savings overview">
    <div className="sv-overview-main">
      <span className="sv-eyebrow"><PiggyBank size={14} /> Total savings balance</span>
      <strong className="sv-total">{ksh(fromCents(savedCents))}</strong>
      <div className="sv-progress lg" role="progressbar" aria-label="Overall progress towards active goals" aria-valuenow={Math.round(progress)} aria-valuemin="0" aria-valuemax="100"><span style={{ width: `${progress}%` }} /></div>
      <small>{targetCents ? `${progress.toFixed(1)}% of ${ksh(fromCents(targetCents))} across active goals` : 'Create a goal to track progress'}{archivedHeld > 0 ? ` · ${ksh(fromCents(archivedHeld))} held in archived goals` : ''}</small>
    </div>
    <div className="sv-overview-metric wallet"><span><Wallet size={14} /> Available wallet balance</span><strong>{ksh(wallet?.balance)}</strong><small>{wallet?.is_frozen ? 'Wallet frozen: movements blocked' : 'Spendable; not allocated to savings'}</small></div>
    <div className="sv-overview-metric"><span><Target size={14} /> Active savings goals</span><strong>{active.length}</strong><small>{goals.length - active.length} archived</small></div>
    <div className="sv-overview-metric"><span><CalendarDays size={14} /> Remaining to reach goals</span><strong>{ksh(fromCents(remaining))}</strong><small>Across active goals</small></div>
  </section>;
}

// --- milestones ---------------------------------------------------------------------------------------------------

export function Milestones({ goal, dates }) {
  return <ol className="sv-milestones" aria-label="Milestones">{milestones(goal.saved_amount, goal.target_amount).map((m) =>
    <li key={m.pct} className={m.reached ? 'reached' : ''} title={m.reached ? `${m.pct}% reached` : `${m.pct}% at ${ksh(fromCents(m.amount))}`}>
      <span className="dot" /><strong>{m.pct}%</strong>
      {dates && <small>{m.reached ? (dates[m.pct] ? day(dates[m.pct]) : 'Reached') : ksh(fromCents(m.amount))}</small>}
    </li>)}</ol>;
}

// --- goal cards ---------------------------------------------------------------------------------------------------

export function GoalCard({ goal, rules, onView, onEdit, onArchive, onMove }) {
  const Icon = goalIcon(goal.name);
  const status = goalStatus(goal, rules);
  const [label, tone] = GOAL_STATUS[status];
  const progress = Math.min(100, Number(goal.progress_percent));
  const need = requiredContribution(toCents(goal.remaining_amount), goal.target_date, localToday());
  return <article className={`sv-goal ${goal.archived_at ? 'archived' : ''}`}>
    <header>
      <span className="sv-goal-icon"><Icon size={18} /></span>
      <div className="sv-goal-title"><h3>{goal.name}</h3><span className={`ins-chip ${tone}`}>{label}</span></div>
      <span className="sv-goal-tools">
        <button className="ins-icon-btn" onClick={() => onView(goal)} aria-label={`View ${goal.name} details`} title="View details"><Eye size={15} /></button>
        {!goal.archived_at && <><button className="ins-icon-btn" onClick={() => onEdit(goal)} aria-label={`Edit ${goal.name}`}><Pencil size={14} /></button>
          <button className="ins-icon-btn" onClick={() => onArchive(goal)} aria-label={`Archive ${goal.name}`}><Archive size={14} /></button></>}
      </span>
    </header>
    <div className="sv-goal-amounts"><strong>{ksh(goal.saved_amount)}</strong><span>of {ksh(goal.target_amount)}</span></div>
    <div className="sv-progress" role="progressbar" aria-label={`${goal.name} progress`} aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100"><span style={{ width: `${progress}%` }} /></div>
    <div className="sv-goal-meta"><span>{progress.toFixed(progress % 1 ? 1 : 0)}% complete</span><span>{toCents(goal.remaining_amount) > 0 ? `${ksh(goal.remaining_amount)} to go` : 'Target reached'}</span></div>
    <Milestones goal={goal} />
    <div className="sv-goal-foot">
      <span><CalendarDays size={13} /> {goal.target_date ? `${day(goal.target_date)}${need && need.days > 0 && !need.done ? ` · ${ksh(fromCents(need.monthly))}/month needed` : ''}` : 'No target date'}</span>
      {scheduledMonthlyCents(rules, goal.id) > 0 && <span><Repeat size={13} /> {ksh(fromCents(scheduledMonthlyCents(rules, goal.id)))}/month automatic</span>}
    </div>
    <footer>
      {!goal.archived_at && <button className="ins-btn primary" onClick={() => onMove(goal, 'contribution')}><ArrowUpRight size={14} /> Add money</button>}
      {toCents(goal.saved_amount) > 0 && <button className="ins-btn" onClick={() => onMove(goal, 'withdrawal')}><ArrowDownLeft size={14} /> Withdraw</button>}
    </footer>
  </article>;
}

export function GoalGrid({ goals, rules, showArchived, onToggleArchived, onCreate, ...handlers }) {
  const active = goals.filter((g) => !g.archived_at).sort((a, b) => (a.priority - b.priority) || (new Date(a.created_at) - new Date(b.created_at)));
  const archived = goals.filter((g) => g.archived_at);
  if (!goals.length) {
    return <EmptyState icon={Target} title="No savings goals yet" detail="Create a goal with a target amount and, optionally, a date. Progress, milestones and required contributions are calculated for you."
      action={<button className="ins-btn primary" onClick={onCreate}>Create your first goal</button>} />;
  }
  return <>
    {active.length ? <div className="sv-goal-grid">{active.map((g) => <GoalCard key={g.id} goal={g} rules={rules} {...handlers} />)}</div>
      : <EmptyState icon={Target} title="No active goals" detail="All your goals are archived." action={<button className="ins-btn primary" onClick={onCreate}>New goal</button>} />}
    {archived.length > 0 && <div className="sv-archived">
      <button className="ins-btn ghost" onClick={onToggleArchived} aria-expanded={showArchived}>{showArchived ? 'Hide' : 'Show'} {archived.length} archived goal{archived.length === 1 ? '' : 's'}</button>
      {showArchived && <div className="sv-goal-grid">{archived.map((g) => <GoalCard key={g.id} goal={g} rules={rules} {...handlers} />)}</div>}
    </div>}
  </>;
}

// --- create / edit ------------------------------------------------------------------------------------------------

export function GoalFormModal({ goal, prefill, onClose, onSaved }) {
  const editing = Boolean(goal);
  const [form, setForm] = useState({ name: goal?.name || prefill?.name || '', target_amount: goal?.target_amount || prefill?.target_amount || '', target_date: goal?.target_date || prefill?.target_date || '' });
  const [touched, setTouched] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const today = localToday();
  const errors = {
    name: !form.name.trim() ? 'Give the goal a name.' : form.name.length > 80 ? 'Use at most 80 characters.' : null,
    target_amount: amountError(form.target_amount),
    target_date: form.target_date && form.target_date < today && form.target_date !== goal?.target_date ? 'Choose today or a later date.' : null,
  };
  const valid = !Object.values(errors).some(Boolean);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  async function save(event) {
    event.preventDefault(); setTouched(true);
    if (!valid) return;
    setBusy(true); setError('');
    const body = { name: form.name.trim(), target_amount: fromCents(toCents(form.target_amount)), target_date: form.target_date || null };
    try { const { data } = editing ? await savingsApi.updateGoal(goal.id, body) : await savingsApi.createGoal(body); onSaved(data, editing); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <Modal title={editing ? 'Edit goal' : 'New savings goal'} subtitle={editing ? 'Saved amounts are changed only by contributions and withdrawals.' : 'You can add money now or later.'} onClose={onClose} busy={busy}
    footer={<><button className="ins-btn ghost" onClick={onClose} disabled={busy}>Cancel</button><button className="ins-btn primary" type="submit" form="sv-goal-form" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Create goal'}</button></>}>
    <form id="sv-goal-form" className="sv-form" onSubmit={save} noValidate>
      <label>Goal name<input maxLength="80" value={form.name} onChange={set('name')} placeholder="e.g. Emergency fund" aria-invalid={touched && !!errors.name} /></label>
      {touched && errors.name && <p className="ins-error">{errors.name}</p>}
      <label>Target amount (KSh)<input inputMode="decimal" value={form.target_amount} onChange={(e) => setForm((f) => ({ ...f, target_amount: e.target.value.replace(/[^\d.]/g, '') }))} placeholder="0.00" aria-invalid={touched && !!errors.target_amount} /></label>
      {touched && errors.target_amount && <p className="ins-error">{errors.target_amount}</p>}
      <label>Target date <span className="ins-muted">(optional)</span><input type="date" min={today} value={form.target_date || ''} onChange={set('target_date')} /></label>
      {touched && errors.target_date && <p className="ins-error">{errors.target_date}</p>}
      {error && <p className="ins-error" role="alert">{error}</p>}
    </form>
  </Modal>;
}

// --- detail view --------------------------------------------------------------------------------------------------

export function GoalDetail({ goal, rules, onClose, onMove, onEdit, onArchive, onManageRules }) {
  const [history, setHistory] = useState(null); const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    savingsApi.contributions(goal.id).then(({ data }) => { if (live) setHistory(data); }).catch((e) => { if (live) { setError(e.message); setHistory([]); } });
    return () => { live = false; };
  }, [goal.id, goal.saved_amount]);
  const Icon = goalIcon(goal.name);
  const [label, tone] = GOAL_STATUS[goalStatus(goal, rules)];
  const need = requiredContribution(toCents(goal.remaining_amount), goal.target_date);
  const goalRules = rules.filter((r) => String(r.goal) === String(goal.id) && r.status !== 'cancelled');
  const list = (direction) => (history || []).filter((h) => h.direction === direction);
  const historyList = (direction, emptyText) => {
    const rows = list(direction);
    if (history === null) return <Skeleton height={34} />;
    if (!rows.length) return <p className="ins-muted sv-small">{emptyText}</p>;
    const total = rows.reduce((s, r) => s + toCents(r.amount), 0);
    return <><ul className="ins-list compact">{rows.slice(0, 8).map((r) => <li key={r.id}><div><strong>{ksh(r.amount)}</strong><small>{day(r.created_at)}</small></div></li>)}</ul>
      <p className="ins-rule">{rows.length} total · {ksh(fromCents(total))}{rows.length > 8 ? ' · see Savings activity for the full list' : ''}</p></>;
  };
  return <Modal title={goal.name} subtitle={goal.archived_at ? `Archived ${day(goal.archived_at)}` : `Created ${day(goal.created_at)}`} onClose={onClose} width={720}
    footer={<>{!goal.archived_at && <button className="ins-btn ghost" onClick={() => onArchive(goal)}><Archive size={14} /> Archive</button>}
      {!goal.archived_at && <button className="ins-btn" onClick={() => onEdit(goal)}><Pencil size={14} /> Edit</button>}
      {toCents(goal.saved_amount) > 0 && <button className="ins-btn" onClick={() => onMove(goal, 'withdrawal')}><ArrowDownLeft size={14} /> Withdraw</button>}
      {!goal.archived_at && <button className="ins-btn primary" onClick={() => onMove(goal, 'contribution')}><ArrowUpRight size={14} /> Add money</button>}</>}>
    <div className="sv-detail-head"><span className="sv-goal-icon lg"><Icon size={22} /></span><span className={`ins-chip ${tone}`}>{label}</span></div>
    <div className="ins-forecast sv-detail-stats">
      <div><span>Current balance</span><strong>{ksh(goal.saved_amount)}</strong></div>
      <div><span>Target</span><strong>{ksh(goal.target_amount)}</strong></div>
      <div><span>Remaining</span><strong>{ksh(goal.remaining_amount)}</strong></div>
    </div>
    <div className="sv-progress lg" role="progressbar" aria-valuenow={Number(goal.progress_percent)} aria-valuemin="0" aria-valuemax="100"><span style={{ width: `${Math.min(100, Number(goal.progress_percent))}%` }} /></div>
    <p className="sv-small">{Number(goal.progress_percent).toFixed(1)}% complete · {goal.target_date ? <>target {day(goal.target_date)}{need && need.days > 0 && !need.done ? <> · {need.days} days left · about {ksh(fromCents(need.monthly))} a month ({ksh(fromCents(need.weekly))} a week) needed</> : need && need.days <= 0 && !need.done ? ' · target date has passed' : ''}</> : 'no target date'}</p>
    <h3 className="ins-subhead">Milestones</h3>
    <Milestones goal={goal} dates={history ? milestoneDates(history, goal.target_amount) : null} />
    {error && <p className="ins-error">{error}</p>}
    <div className="ins-grid-2 tight">
      <div><h3 className="ins-subhead">Contributions</h3>{historyList('contribution', 'No contributions yet.')}</div>
      <div><h3 className="ins-subhead">Withdrawals</h3>{historyList('withdrawal', 'No withdrawals.')}</div>
    </div>
    <h3 className="ins-subhead">Automatic savings</h3>
    {goalRules.length ? <ul className="ins-list compact">{goalRules.map((r) => <li key={r.id}><span className="ins-list-icon"><Repeat size={14} /></span><div><strong>{ksh(r.amount)} {r.cadence}</strong><small>{r.status === 'authorized' ? `Next run ${day(r.next_run_date)}` : r.status === 'draft' ? 'Draft: not authorized, will not run' : 'Paused'}</small></div></li>)}</ul>
      : <p className="ins-muted sv-small">No automatic rule for this goal.</p>}
    {!goal.archived_at && <button className="ins-btn ghost sv-link" onClick={() => onManageRules(goal)}>{goalRules.length ? 'Manage automatic savings' : 'Set up automatic savings'}</button>}
  </Modal>;
}
