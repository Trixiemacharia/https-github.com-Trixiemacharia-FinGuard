import { useCallback, useEffect, useState } from 'react';
import { CalendarDays, Pencil, Plus, Trash2, X } from 'lucide-react';
import { insightsApi } from '../../api/services.js';
import { CATEGORY_KEYS, categoryLabel, day, ksh } from '../../components/dashboard/format.js';
import { EmptyState, Panel, Skeleton } from '../../components/dashboard/ui.jsx';

const STATUS = {
  expected: ['Expected income', 'info'], received: ['Received', 'good'], not_received: ['Not received', 'bad'],
  upcoming: ['Upcoming bill', 'warn'], paid: ['Paid', 'good'], no_matching_payment: ['No wallet payment found', 'neutral'],
  scheduled: ['Scheduled saving', 'info'], past: ['Saving (past)', 'neutral'],
};
const SOURCE = { calendar_entry: 'Calendar', recurring_payment: 'Recurring', savings_schedule: 'Savings rule' };
const blank = { kind: 'bill', title: '', category: 'housing', amount: '', due_date: '', recurrence: 'monthly' };

export function CalendarSection({ refreshKey }) {
  const [schedule, setSchedule] = useState(null);
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState('');
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    setError('');
    try {
      const [upcoming, list] = await Promise.all([insightsApi.upcoming(60, 30), insightsApi.calendar()]);
      setSchedule(upcoming.data); setEntries(list.data.entries);
    } catch (e) { setError(e.message); setSchedule((current) => current || { occurrences: [] }); }
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  async function save(event) {
    event.preventDefault(); setSaving(true); setError('');
    const body = { kind: form.kind, title: form.title, category: form.category, amount: form.amount, due_date: form.due_date, recurrence: form.recurrence };
    try { if (form.id) await insightsApi.updateCalendarEntry(form.id, body); else await insightsApi.addCalendarEntry(body); setForm(null); await load(); }
    catch (e) { setError(e.message); } finally { setSaving(false); }
  }
  async function remove(entry) {
    if (!window.confirm(`Remove "${entry.title}" from your calendar?`)) return;
    setError('');
    try { await insightsApi.deleteCalendarEntry(entry.id); await load(); } catch (e) { setError(e.message); }
  }
  // The server decides what is past or upcoming (in the wallet's timezone) through each item's status.
  const UPCOMING = new Set(['expected', 'upcoming', 'scheduled']);
  const occurrences = schedule?.occurrences || [];
  const past = occurrences.filter((o) => !UPCOMING.has(o.status)).reverse();
  const upcoming = occurrences.filter((o) => UPCOMING.has(o.status));

  const row = (o) => {
    const [label, tone] = STATUS[o.status] || [o.status, 'neutral'];
    const entry = o.source === 'calendar_entry' ? entries.find((e) => String(e.id) === String(o.source_id)) : null;
    return <li key={`${o.source}-${o.source_id}-${o.due_date}`} className={`ins-cal-row ${o.kind}`}>
      <span className="ins-cal-date"><strong>{day(o.due_date, { day: 'numeric' })}</strong>{day(o.due_date, { month: 'short' })}</span>
      <div className="ins-cal-main"><strong>{o.title}</strong><small>{o.kind === 'income' ? 'Income' : o.kind === 'savings' ? 'Savings' : categoryLabel(o.category)} · {entry ? entry.recurrence : SOURCE[o.source]}</small></div>
      <span className={`ins-cal-amount ${o.kind === 'income' ? 'pos' : ''}`}>{o.kind === 'income' ? '+' : '−'}{ksh(o.amount)}</span>
      <span className={`ins-chip ${tone}`}>{label}</span>
      <span className="ins-actions">{entry && <><button className="ins-icon-btn" aria-label={`Edit ${o.title}`} onClick={() => setForm({ ...entry })}><Pencil size={14} /></button><button className="ins-icon-btn" aria-label={`Remove ${o.title}`} onClick={() => remove(entry)}><Trash2 size={14} /></button></>}</span>
    </li>;
  };

  return <Panel id="financial-calendar" title="Financial calendar" subtitle="Planned bills and expected income. Expected items are never counted as completed transactions."
    action={<button className="ins-btn primary" onClick={() => setForm(form ? null : { ...blank })}>{form ? <><X size={14} /> Close</> : <><Plus size={14} /> Add entry</>}</button>}>
    {error && <p className="ins-error">{error}</p>}
    {form && <form className="ins-cal-form" onSubmit={save}>
      <label>Type<select value={form.kind} onChange={set('kind')}><option value="bill">Bill or obligation</option><option value="income">Expected income</option></select></label>
      <label>Description<input required maxLength="80" value={form.title} onChange={set('title')} placeholder="e.g. Rent" /></label>
      <label>Category<select value={form.category} onChange={set('category')}>{CATEGORY_KEYS.map((key) => <option key={key} value={key}>{categoryLabel(key)}</option>)}</select></label>
      <label>Amount (KSh)<input required type="number" min="0.01" step="0.01" value={form.amount} onChange={set('amount')} /></label>
      <label>Due date<input required type="date" value={form.due_date} onChange={set('due_date')} /></label>
      <label>Frequency<select value={form.recurrence} onChange={set('recurrence')}><option value="once">Once</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></label>
      <button className="ins-btn primary" type="submit" disabled={saving}>{saving ? 'Saving…' : form.id ? 'Save changes' : 'Add to calendar'}</button>
    </form>}
    {schedule === null ? <><Skeleton height={44} /><Skeleton height={44} /></> : <div className="ins-grid-2 tight">
      <div><h3 className="ins-subhead">Next 60 days</h3>
        {upcoming.length ? <ul className="ins-cal-list">{upcoming.map(row)}</ul> : <EmptyState icon={CalendarDays} title="No upcoming commitments" detail="Add rent, regular bills or your salary date to plan ahead." />}</div>
      <div><h3 className="ins-subhead">Last 30 days</h3>
        {past.length ? <ul className="ins-cal-list">{past.map(row)}</ul> : <EmptyState icon={CalendarDays} title="Nothing was due in the last 30 days" />}</div>
    </div>}
    {schedule?.status_rule && <p className="ins-rule">{schedule.status_rule}</p>}
  </Panel>;
}
