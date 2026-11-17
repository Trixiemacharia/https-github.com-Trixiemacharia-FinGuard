import { useState } from 'react';
import { CalendarClock, Pause, Pencil, Play, Plus, Repeat, ShieldCheck, Trash2 } from 'lucide-react';
import { savingsApi } from '../../api/services.js';
import { ConfirmDialog, EmptyState, Modal, Panel } from '../../components/dashboard/ui.jsx';
import { day, ksh } from '../../components/dashboard/format.js';
import { amountError, fromCents, localToday, toCents } from './logic.js';

const STATE = {
  authorized: ['Active', 'good', 'Runs automatically'], paused: ['Paused', 'warn', 'Will not run until resumed'],
  draft: ['Draft', 'neutral', 'Not authorized: will never run'], cancelled: ['Deleted', 'neutral', 'Stopped permanently'],
};
const describeLastRun = (rule) => (rule.last_run_at ? `Last run ${day(rule.last_run_at)} · ${rule.last_run_status === 'completed' ? 'completed' : `failed (${(rule.last_run_status || '').replace(/_/g, ' ')}), nothing moved`}` : 'Has not run yet');

function RuleCard({ rule, goalName, onEdit, onAction }) {
  const [label, tone, note] = STATE[rule.status] || [rule.status, 'neutral', ''];
  return <article className={`sv-rule ${rule.status}`}>
    <header><span className="sv-goal-icon sm"><Repeat size={15} /></span><div><h3>{goalName}</h3><small>{note}</small></div><span className={`ins-chip ${tone}`}>{label}</span></header>
    <dl className="sv-rule-facts">
      <div><dt>Amount per run</dt><dd>{ksh(rule.amount)}</dd></div>
      <div><dt>Frequency</dt><dd className="cap">{rule.cadence}</dd></div>
      <div><dt>Start date</dt><dd>{day(rule.start_date)}</dd></div>
      <div><dt>Next run</dt><dd>{rule.status === 'authorized' && rule.next_run_date ? day(rule.next_run_date) : '—'}</dd></div>
    </dl>
    {rule.status === 'authorized' && rule.next_run_date && <p className="sv-next"><CalendarClock size={13} /> On {day(rule.next_run_date)}, {ksh(rule.amount)} moves from your wallet to {goalName} if your wallet balance covers it.</p>}
    <p className="ins-rule">{describeLastRun(rule)}</p>
    {rule.status !== 'cancelled' && <footer>
      {rule.status === 'authorized' && <button className="ins-btn" onClick={() => onAction(rule, 'pause')}><Pause size={14} /> Pause</button>}
      {rule.status === 'paused' && <button className="ins-btn primary" onClick={() => onAction(rule, 'resume')}><Play size={14} /> Resume</button>}
      {rule.status === 'draft' && <button className="ins-btn primary" onClick={() => onAction(rule, 'authorize')}><ShieldCheck size={14} /> Authorize</button>}
      <span className="sv-spacer" />
      <button className="ins-icon-btn" onClick={() => onEdit(rule)} aria-label="Edit rule"><Pencil size={14} /></button>
      <button className="ins-icon-btn" onClick={() => onAction(rule, 'cancel')} aria-label="Delete rule"><Trash2 size={14} /></button>
    </footer>}
  </article>;
}

export function RulesSection({ rules, goals, onCreate, onEdit, onChanged, notify }) {
  const [confirm, setConfirm] = useState(null); const [busy, setBusy] = useState(false); const [showCancelled, setShowCancelled] = useState(false);
  const goalName = (rule) => rule.goal_name || goals.find((g) => String(g.id) === String(rule.goal))?.name || 'Savings goal';
  const ORDER = { authorized: 0, paused: 1, draft: 2 };
  const current = rules.filter((r) => r.status !== 'cancelled').sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const count = (status) => rules.filter((r) => r.status === status).length;
  const cancelled = rules.filter((r) => r.status === 'cancelled');
  const texts = {
    pause: (r) => ['Pause rule', `Pause the ${r.cadence} ${ksh(r.amount)} contribution to ${goalName(r)}? Nothing will move until you resume it.`, 'Pause', 'primary'],
    resume: (r) => ['Resume rule', <>Resume the {r.cadence} {ksh(r.amount)} contribution to {goalName(r)}? This authorizes future automatic contributions from your wallet. It continues from the next scheduled date and does <strong>not</strong> make up for the time it was paused.</>, 'Resume and authorize', 'primary'],
    authorize: (r) => ['Authorize rule', <>Authorize {ksh(r.amount)} {r.cadence} from your wallet to {goalName(r)}, starting {day(r.start_date)}? Money moves automatically on each scheduled date until you pause or delete the rule.</>, 'Authorize', 'primary'],
    cancel: (r) => ['Delete rule', `Delete the ${r.cadence} ${ksh(r.amount)} rule for ${goalName(r)}? It stops permanently. Past contributions stay in your history.`, 'Delete rule', 'danger'],
  };
  async function run() {
    const { rule, action } = confirm; setBusy(true);
    try {
      const body = action === 'resume' || action === 'authorize' ? { authorize: true } : { action };
      const { data } = await savingsApi.updateSchedule(rule.id, body);
      notify('success', { pause: 'Rule paused.', cancel: 'Rule deleted.', resume: `Rule resumed. Next run ${day(data.next_run_date)}.`, authorize: `Rule authorized. First run ${day(data.next_run_date)}.` }[action]);
      setConfirm(null); await onChanged();
    } catch (e) { notify('error', e.message); setConfirm(null); } finally { setBusy(false); }
  }
  const open = confirm && texts[confirm.action](confirm.rule);
  return <Panel title="Automatic savings"
    action={<button className="ins-btn primary" onClick={onCreate} disabled={!goals.some((g) => !g.archived_at)}><Plus size={14} /> New rule</button>}>
    {!rules.filter((r) => r.status !== 'cancelled').length ? <EmptyState icon={Repeat} title="No automatic savings rules" detail="Set a fixed amount to move into a goal every week or month. You review and authorize it before it ever runs." /> :
      <><p className="sv-rule-summary"><span className="ins-chip good">{count('authorized')} active</span><span className="ins-chip warn">{count('paused')} paused</span><span className="ins-chip neutral">{count('draft')} draft{count('draft') === 1 ? '' : 's'}</span></p>
        <div className="sv-rule-grid">{current.map((r) => <RuleCard key={r.id} rule={r} goalName={goalName(r)} onEdit={onEdit} onAction={(rule, action) => setConfirm({ rule, action })} />)}</div></>}
    {cancelled.length > 0 && <div><button className="ins-btn ghost" onClick={() => setShowCancelled((s) => !s)} aria-expanded={showCancelled}>{showCancelled ? 'Hide' : 'Show'} {cancelled.length} deleted rule{cancelled.length === 1 ? '' : 's'}</button>
      {showCancelled && <div className="sv-rule-grid">{cancelled.map((r) => <RuleCard key={r.id} rule={r} goalName={goalName(r)} />)}</div>}</div>}
    {open && <ConfirmDialog title={open[0]} message={open[1]} confirmLabel={open[2]} tone={open[3]} busy={busy} onConfirm={run} onCancel={() => setConfirm(null)} />}
  </Panel>;
}

export function RuleFormModal({ rule, goals, presetGoal, onClose, onSaved }) {
  const editing = Boolean(rule);
  const active = goals.filter((g) => !g.archived_at);
  const [form, setForm] = useState({ goal: rule?.goal || presetGoal?.id || active[0]?.id || '', amount: rule?.amount || '', cadence: rule?.cadence || 'monthly', start_date: rule?.start_date || localToday() });
  const [authorize, setAuthorize] = useState(false);
  const [touched, setTouched] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const mustReauthorize = editing && rule.status === 'authorized';
  const errors = {
    goal: form.goal ? null : 'Select a goal.', amount: amountError(form.amount),
    start_date: !form.start_date ? 'Choose a start date.' : (!editing || form.start_date !== rule.start_date) && form.start_date < localToday() ? 'Choose today or a later date.' : null,
    authorize: mustReauthorize && !authorize ? 'Changes to an active rule need your authorization again.' : null,
  };
  const valid = !Object.values(errors).some(Boolean);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const goal = goals.find((g) => String(g.id) === String(form.goal));
  async function save(event) {
    event.preventDefault(); setTouched(true);
    if (!valid) return;
    setBusy(true); setError('');
    const body = { goal: form.goal, amount: fromCents(toCents(form.amount)), cadence: form.cadence, start_date: form.start_date, authorize };
    try { const { data } = editing ? await savingsApi.updateSchedule(rule.id, body) : await savingsApi.createSchedule(body); onSaved(data, editing); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const monthly = !amountError(form.amount) ? (form.cadence === 'weekly' ? Math.round(toCents(form.amount) * 52 / 12) : toCents(form.amount)) : 0;
  return <Modal title={editing ? 'Edit automatic rule' : 'New automatic savings rule'} subtitle="A fixed amount from your wallet to one goal, on a schedule." onClose={onClose} busy={busy}
    footer={<><button className="ins-btn ghost" onClick={onClose} disabled={busy}>Cancel</button><button className="ins-btn primary" type="submit" form="sv-rule-form" disabled={busy}>{busy ? 'Saving…' : authorize ? 'Save and authorize' : 'Save as draft'}</button></>}>
    <form id="sv-rule-form" className="sv-form" onSubmit={save} noValidate>
      <label>Goal<select value={form.goal} onChange={set('goal')}>{!form.goal && <option value="">Select a goal</option>}{active.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
      {touched && errors.goal && <p className="ins-error">{errors.goal}</p>}
      <div className="sv-form-row">
        <label>Amount per run (KSh)<input inputMode="decimal" value={form.amount} onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value.replace(/[^\d.]/g, '') }))} placeholder="0.00" /></label>
        <label>Frequency<select value={form.cadence} onChange={set('cadence')}><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></label>
      </div>
      {touched && errors.amount && <p className="ins-error">{errors.amount}</p>}
      <label>Start date<input type="date" min={localToday()} value={form.start_date} onChange={set('start_date')} /></label>
      {touched && errors.start_date && <p className="ins-error">{errors.start_date}</p>}
      {monthly > 0 && goal && <p className="sv-small">About {ksh(fromCents(monthly))} a month into {goal.name}.</p>}
      <label className="sv-check"><input type="checkbox" checked={authorize} onChange={(e) => setAuthorize(e.target.checked)} />
        <span>I authorize FinGuard to move {amountError(form.amount) ? 'this amount' : ksh(fromCents(toCents(form.amount)))} from my wallet to {goal?.name || 'this goal'} {form.cadence === 'weekly' ? 'every week' : 'every month'}, starting {form.start_date ? day(form.start_date) : 'on the start date'}, until I pause or delete the rule.</span></label>
      {!authorize && !mustReauthorize && <p className="ins-rule">Leave unticked to save a draft. Drafts never move money.</p>}
      {touched && errors.authorize && <p className="ins-error">{errors.authorize}</p>}
      {error && <p className="ins-error" role="alert">{error}</p>}
    </form>
  </Modal>;
}
