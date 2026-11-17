import { useCallback, useEffect, useState } from 'react';
import { CalendarDays, Trash2 } from 'lucide-react';
import { insightsApi } from '../api/services.js';
import { Empty, ErrorState, Loading } from '../components/Feedback.jsx';
import { formatMoney } from '../utils/format.js';

const categories = ['housing', 'utilities', 'groceries', 'transport', 'health', 'education', 'shopping', 'dining', 'transfers', 'other'];
const blank = { kind: 'bill', title: '', category: 'housing', amount: '', due_date: '', recurrence: 'monthly' };

/** Planned bills and expected income. Planning data only: nothing here moves money. */
export function FinancialCalendar({ prefill }) {
  const [entries, setEntries] = useState(null); const [error, setError] = useState('');
  const [form, setForm] = useState({ ...blank, ...(prefill || {}) }); const [saving, setSaving] = useState(false);
  const load = useCallback(() => insightsApi.calendar().then(({ data }) => setEntries(data.entries)).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  async function submit(event) {
    event.preventDefault(); setSaving(true); setError('');
    try { await insightsApi.addCalendarEntry(form); setForm({ ...blank }); await load(); } catch (e) { setError(e.message); } finally { setSaving(false); }
  }
  async function remove(id) { setError(''); try { await insightsApi.deleteCalendarEntry(id); await load(); } catch (e) { setError(e.message); } }
  return <>
    <section className="section-heading spaced" id="financial-calendar"><div><h2>Financial calendar</h2><p>Rent, bills and expected income you record here are used by the assistant. Nothing is paid from this list.</p></div></section>
    {error && <ErrorState error={error} />}
    <form className="calendar-form" onSubmit={submit}>
      <select aria-label="Entry type" value={form.kind} onChange={set('kind')}><option value="bill">Bill</option><option value="income">Expected income</option></select>
      <input aria-label="Title" required maxLength="80" placeholder="e.g. Rent" value={form.title} onChange={set('title')} />
      <select aria-label="Category" value={form.category} onChange={set('category')}>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select>
      <input aria-label="Amount" required type="number" min="0.01" step="0.01" placeholder="Amount" value={form.amount} onChange={set('amount')} />
      <input aria-label="Due date" required type="date" value={form.due_date} onChange={set('due_date')} />
      <select aria-label="Repeats" value={form.recurrence} onChange={set('recurrence')}><option value="once">Once</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
      <button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Add'}</button>
    </form>
    {entries === null ? <Loading label="Loading calendar" /> : !entries.length ? <Empty title="No planned bills or income" detail="Add your rent, regular bills and salary date for more accurate assistant answers." /> :
      <div className="transaction-list">{entries.map((item) => <article className="transaction-row" key={item.id}><div className="transaction-icon"><CalendarDays size={16} /></div><div className="transaction-main"><strong>{item.title}</strong><small>{item.kind === 'income' ? 'Expected income' : `Bill · ${item.category}`} · {item.recurrence} · from {item.due_date}</small></div><span>{formatMoney(item.amount, item.currency)}</span><button className="text-button" aria-label={`Remove ${item.title}`} onClick={() => remove(item.id)}><Trash2 size={14} /></button></article>)}</div>}
  </>;
}
