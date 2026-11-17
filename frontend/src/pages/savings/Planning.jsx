import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Calculator as CalcIcon, ShieldCheck } from 'lucide-react';
import { insightsApi, savingsApi } from '../../api/services.js';
import { EmptyState, Panel } from '../../components/dashboard/ui.jsx';
import { day, ksh } from '../../components/dashboard/format.js';
import { amountError, fromCents, localToday, requiredContribution, scheduledMonthlyCents, toCents } from './logic.js';

// --- calculator ---------------------------------------------------------------------------------------------------

export function SavingsCalculator({ goals }) {
  const [form, setForm] = useState({ target: '', saved: '', date: '' });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: key === 'date' ? e.target.value : e.target.value.replace(/[^\d.]/g, '') }));
  const loadGoal = (id) => { const g = goals.find((x) => String(x.id) === id); if (g) setForm({ target: g.target_amount, saved: g.saved_amount, date: g.target_date || '' }); };
  const targetErr = form.target ? amountError(form.target) : null;
  const savedErr = form.saved && amountError(form.saved) && toCents(form.saved) !== 0 ? amountError(form.saved) : null;
  const remaining = Math.max(0, toCents(form.target) - toCents(form.saved));
  const result = !targetErr && !savedErr && form.target && form.date ? requiredContribution(remaining, form.date) : null;
  return <Panel title="Savings calculator" subtitle="Estimates only. Nothing is scheduled from here.">
    <div className="sv-calc-layout">
    <div className="sv-form sv-calc">
      {goals.some((g) => !g.archived_at) && <label>Start from a goal<select defaultValue="" onChange={(e) => loadGoal(e.target.value)}><option value="">Enter figures manually</option>{goals.filter((g) => !g.archived_at).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>}
      <div className="sv-form-row">
        <label>Target amount (KSh)<input inputMode="decimal" value={form.target} onChange={set('target')} placeholder="0.00" /></label>
        <label>Already saved (KSh)<input inputMode="decimal" value={form.saved} onChange={set('saved')} placeholder="0.00" /></label>
      </div>
      <label>Target date<input type="date" min={localToday()} value={form.date} onChange={set('date')} /></label>
      {(targetErr || savedErr) && <p className="ins-error">{targetErr || savedErr}</p>}
    </div>
    <div className="sv-calc-result">
    {!result ? <EmptyState icon={CalcIcon} title="Enter a target and a date" detail="The contribution needed per day, week and month updates as you type." /> :
      result.done ? <p className="ins-note">The target is already covered by what you have saved.</p> :
        result.days <= 0 ? <p className="ins-error">Choose a date after today.</p> :
          <><div className="ins-forecast">
            <div><span>Per day</span><strong>{ksh(fromCents(result.daily))}</strong></div>
            <div><span>Per week</span><strong>{ksh(fromCents(result.weekly))}</strong></div>
            <div className="total"><span>Per month</span><strong>{ksh(fromCents(result.monthly))}</strong></div>
          </div>
            <p className="ins-rule">Estimate: {ksh(fromCents(remaining))} still needed over {result.days} days, divided evenly and rounded up to the cent. Months are averaged at 30.4 days.</p></>}
    </div>
    </div>
  </Panel>;
}

// --- planning -----------------------------------------------------------------------------------------------------

export function FinancialPlanning({ goals, rules, onCreateGoal, onChanged, notify }) {
  const active = useMemo(() => goals.filter((g) => !g.archived_at).sort((a, b) => (a.priority - b.priority) || (new Date(a.created_at) - new Date(b.created_at))), [goals]);
  const [order, setOrder] = useState(active.map((g) => g.id));
  const [dates, setDates] = useState({});
  const [budget, setBudget] = useState('');
  const [months, setMonths] = useState(3);
  const [expenses, setExpenses] = useState(null);
  const [manualExpenses, setManualExpenses] = useState('');
  const [recommendation, setRecommendation] = useState(null);
  const [saving, setSaving] = useState('');
  useEffect(() => { setOrder(active.map((g) => g.id)); }, [active]);
  useEffect(() => {
    insightsApi.dashboard({ period: 'last_3_months' }).then(({ data }) => setExpenses({ total: data.kpis.expenses, days: data.period.days, count: data.kpis.outgoing_count })).catch(() => setExpenses({ total: null }));
    savingsApi.recommendation().then(({ data }) => setRecommendation(data)).catch(() => setRecommendation(null));
  }, []);

  const ordered = order.map((id) => active.find((g) => g.id === id)).filter(Boolean);
  const changedOrder = ordered.some((g, i) => g.priority !== i);
  const move = (index, delta) => setOrder((o) => { const next = [...o]; const [item] = next.splice(index, 1); next.splice(index + delta, 0, item); return next; });

  async function saveOrder() {
    setSaving('order');
    try { await Promise.all(ordered.map((g, i) => (g.priority !== i ? savingsApi.updateGoal(g.id, { priority: i }) : null))); notify('success', 'Goal priorities saved.'); await onChanged(); }
    catch (e) { notify('error', e.message); } finally { setSaving(''); }
  }
  async function saveDate(goal) {
    setSaving(goal.id);
    try { await savingsApi.updateGoal(goal.id, { target_date: dates[goal.id] || null }); setDates((d) => { const n = { ...d }; delete n[goal.id]; return n; }); notify('success', `Target date for ${goal.name} updated.`); await onChanged(); }
    catch (e) { notify('error', e.message); } finally { setSaving(''); }
  }

  // Monthly average from the last 3 months of completed payments (Insights), or the user's own figure.
  const observedMonthly = expenses?.total != null && Number(expenses.total) > 0 ? Math.round(toCents(expenses.total) / (expenses.days / (365.25 / 12))) : null;
  const monthlyCents = manualExpenses && !amountError(manualExpenses) ? toCents(manualExpenses) : observedMonthly;
  const emergencyTarget = monthlyCents ? monthlyCents * months : null;
  const emergencyGoal = active.find((g) => /emergenc|rainy/i.test(g.name));

  // Deterministic waterfall: the monthly budget funds each dated goal's requirement in priority order.
  const budgetCents = budget && !amountError(budget) ? toCents(budget) : null;
  let left = budgetCents ?? 0;
  const rows = ordered.map((g) => {
    const need = requiredContribution(toCents(g.remaining_amount), dates[g.id] ?? g.target_date);
    const required = need && need.days > 0 && !need.done ? need.monthly : 0;
    const scheduled = scheduledMonthlyCents(rules, g.id);
    const allocated = budgetCents === null ? null : Math.min(left, required);
    if (allocated !== null) left -= allocated;
    return { goal: g, need, required, scheduled, allocated };
  });
  const totalRequired = rows.reduce((s, r) => s + r.required, 0);
  const totalScheduled = rows.reduce((s, r) => s + r.scheduled, 0);

  return <Panel title="Financial planning" subtitle="Deterministic calculations from your targets and actual savings. Nothing here moves money.">
    <div className="sv-plan-grid">
      <section className="sv-plan-card">
        <h3><ShieldCheck size={15} /> Emergency fund</h3>
        <p className="sv-small">A common rule of thumb is 3 to 6 months of essential spending.</p>
        <div className="sv-segment small" role="radiogroup" aria-label="Months of spending">{[3, 6].map((m) => <button key={m} type="button" role="radio" aria-checked={months === m} className={months === m ? 'on' : ''} onClick={() => setMonths(m)}>{m} months</button>)}</div>
        <div className="sv-form"><label>Monthly spending (KSh)<input inputMode="decimal" placeholder={observedMonthly ? fromCents(observedMonthly) : 'Enter your monthly spending'} value={manualExpenses} onChange={(e) => setManualExpenses(e.target.value.replace(/[^\d.]/g, ''))} /></label></div>
        <p className="ins-rule">{observedMonthly ? `Default: ${ksh(fromCents(observedMonthly))} a month, the average of your completed wallet payments over the last 3 months (${expenses.count} payments). Wallet only, so add cash spending if you have any.` : expenses === null ? 'Loading your recent spending…' : 'No completed wallet payments in the last 3 months. Enter your monthly spending.'}</p>
        {emergencyTarget ? <>
          <div className="sv-plan-figure"><span>Suggested target</span><strong>{ksh(fromCents(emergencyTarget))}</strong></div>
          {emergencyGoal ? <p className="sv-small">Your “{emergencyGoal.name}” goal has {ksh(emergencyGoal.saved_amount)} of {ksh(emergencyGoal.target_amount)}.{toCents(emergencyGoal.target_amount) !== emergencyTarget && <> <button className="ins-btn ghost sv-link" disabled={saving === 'ef'} onClick={async () => { setSaving('ef'); try { await savingsApi.updateGoal(emergencyGoal.id, { target_amount: fromCents(emergencyTarget) }); notify('success', 'Emergency fund target updated.'); await onChanged(); } catch (e) { notify('error', e.message); } finally { setSaving(''); } }}>Set its target to {ksh(fromCents(emergencyTarget))}</button></>}</p>
            : <button className="ins-btn primary" onClick={() => onCreateGoal({ name: 'Emergency fund', target_amount: fromCents(emergencyTarget) })}>Create emergency fund goal</button>}
        </> : null}
      </section>
      <section className="sv-plan-card">
        <h3>Monthly savings budget</h3>
        <p className="sv-small">Enter what you can save each month to see how it covers your goals, highest priority first.</p>
        <div className="sv-form"><label>Monthly amount (KSh)<input inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^\d.]/g, ''))} placeholder="0.00" /></label></div>
        <div className="sv-plan-figure"><span>Needed each month for dated goals</span><strong>{ksh(fromCents(totalRequired))}</strong></div>
        <p className="ins-rule">Authorized automatic rules already cover {ksh(fromCents(totalScheduled))} a month.{budgetCents !== null && <> Your budget {budgetCents >= totalRequired ? `covers every dated goal with ${ksh(fromCents(budgetCents - totalRequired))} spare.` : `falls ${ksh(fromCents(totalRequired - budgetCents))} short; lower-priority goals are funded last.`}</>}</p>
        {recommendation?.available && <p className="ins-rule">Existing suggestion: {ksh(recommendation.suggested_amount)} ({recommendation.assumptions.method}).</p>}
      </section>
    </div>
    <h3 className="ins-subhead">Priorities and target dates</h3>
    {!ordered.length ? <EmptyState title="No active goals to plan" detail="Create a goal to plan contributions." /> : <>
      <div className="ins-table-wrap"><table className="ins-table stack sv-plan-table">
        <thead><tr><th>Priority</th><th>Goal</th><th>Target date</th><th className="n">Remaining</th><th className="n">Needed / month</th><th className="n">Automatic / month</th>{budgetCents !== null && <th className="n">From budget</th>}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.goal.id}>
          <td><span className="ins-actions sv-priority"><strong>{i + 1}</strong>
            <button className="ins-icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${r.goal.name} up`}><ArrowUp size={14} /></button>
            <button className="ins-icon-btn" disabled={i === rows.length - 1} onClick={() => move(i, 1)} aria-label={`Move ${r.goal.name} down`}><ArrowDown size={14} /></button></span></td>
          <td data-label="Goal">{r.goal.name}</td>
          <td data-label="Target date"><span className="ins-actions"><input type="date" aria-label={`Target date for ${r.goal.name}`} min={localToday()} value={dates[r.goal.id] ?? r.goal.target_date ?? ''} onChange={(e) => setDates((d) => ({ ...d, [r.goal.id]: e.target.value }))} />
            {r.goal.id in dates && dates[r.goal.id] !== (r.goal.target_date || '') && <button className="ins-btn" disabled={saving === r.goal.id} onClick={() => saveDate(r.goal)}>Save</button>}</span></td>
          <td data-label="Remaining" className="n">{ksh(r.goal.remaining_amount)}</td>
          <td data-label="Needed / month" className="n">{r.need === null ? <span className="ins-muted">No date</span> : r.need.done ? 'Reached' : r.need.days <= 0 ? <span className="neg">Date passed</span> : ksh(fromCents(r.required))}</td>
          <td data-label="Automatic / month" className={`n ${r.required && r.scheduled < r.required ? 'neg' : ''}`}>{ksh(fromCents(r.scheduled))}</td>
          {budgetCents !== null && <td data-label="From budget" className={`n ${r.required && r.allocated < r.required ? 'neg' : 'pos'}`}>{r.required ? ksh(fromCents(r.allocated)) : '—'}</td>}
        </tr>)}</tbody></table></div>
      {changedOrder && <div className="sv-plan-actions"><button className="ins-btn ghost" onClick={() => setOrder(active.map((g) => g.id))}>Reset</button><button className="ins-btn primary" disabled={saving === 'order'} onClick={saveOrder}>{saving === 'order' ? 'Saving…' : 'Save priority order'}</button></div>}
      <p className="ins-rule">Needed per month = remaining ÷ months until the target date (changes to dates above are reflected before you save). Automatic per month counts authorized rules only (weekly × 52 ÷ 12). Today is {day(localToday())}.</p>
    </>}
  </Panel>;
}
