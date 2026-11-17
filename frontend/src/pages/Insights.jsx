import { useCallback, useEffect, useState } from 'react';
import { ChartNoAxesCombined, RefreshCw, Sparkles } from 'lucide-react';
import { insightsApi } from '../api/services.js';
import { Empty, ErrorState, Loading, PageTitle, StatusPill } from '../components/Feedback.jsx';
import { formatMoney, formatWhen } from '../utils/format.js';
import { FinancialCalendar } from './FinancialCalendar.jsx';

const categories = ['groceries', 'transport', 'utilities', 'housing', 'health', 'education', 'shopping', 'dining', 'transfers', 'other'];

export function Insights() {
  const [data, setData] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [detecting, setDetecting] = useState(false);
  const [saving, setSaving] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [overview, activity] = await Promise.all([insightsApi.overview(), insightsApi.transactions()]);
      setData(overview.data); setTransactions(activity.data.transactions || []);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function changeCategory(transaction, category) {
    setSaving(transaction.id); setError(''); setMessage('');
    try { await insightsApi.categorize(transaction.id, category); setMessage('Spending category updated.'); await load(); }
    catch (e) { setError(e.message); }
    finally { setSaving(''); }
  }
  async function detectRecurring() {
    setDetecting(true); setError(''); setMessage('');
    try {
      const { data: queued } = await insightsApi.detectRecurring();
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const { data: status } = await insightsApi.detectionStatus(queued.task_id);
        if (status.status === 'complete') { setMessage(`${status.suggestions_found} recurring payment suggestion${status.suggestions_found === 1 ? '' : 's'} found.`); await load(); return; }
        if (status.status === 'error') throw new Error(status.detail || 'Recurring payment detection failed.');
      }
      setMessage('Detection is still running. Refresh later to see suggestions.');
    } catch (e) { setError(e.message); }
    finally { setDetecting(false); }
  }
  async function updateRecurring(item, action) {
    setSaving(`recurring-${item.id}`); setError(''); setMessage('');
    try {
      const next_due = action === 'confirm' ? window.prompt('Next expected payment date (YYYY-MM-DD), optional:') : undefined;
      const body = { action, ...(next_due ? { next_due } : {}) };
      await insightsApi.updateRecurring(item.id, body); setMessage(action === 'confirm' ? 'Recurring payment confirmed.' : 'Suggestion dismissed.'); await load();
    } catch (e) { setError(e.message); }
    finally { setSaving(''); }
  }

  return <><PageTitle eyebrow="ACCOUNT ACTIVITY" title="Financial insights" detail="Clear summaries calculated from your completed wallet transactions." action={<button className="icon-text-button" onClick={load}><RefreshCw size={14} /> Refresh</button>} />
    {message && <div className="success-banner"><Sparkles size={16} /> {message}<button onClick={() => setMessage('')} aria-label="Dismiss">×</button></div>}
    {loading ? <Loading label="Loading financial insights" /> : error && !data ? <ErrorState error={error} onRetry={load} /> : data && <>
      {error && <ErrorState error={error} onRetry={load} />}
      <section className="section-heading spaced"><div><h2>Month over month</h2><p>Completed incoming and outgoing wallet activity</p></div></section>
      <div className="stats-grid"><article className="stat-card"><span>Monthly spending</span><strong>{formatMoney(data.month_over_month.spending.current, data.currency)}</strong><small>Change {formatMoney(data.month_over_month.spending.change, data.currency)} {data.month_over_month.spending.change_percent == null ? '(no previous month)' : `(${Number(data.month_over_month.spending.change_percent).toFixed(1)}%)`}</small></article><article className="stat-card"><span>Monthly income</span><strong>{formatMoney(data.month_over_month.income.current, data.currency)}</strong><small>Change {formatMoney(data.month_over_month.income.change, data.currency)}</small></article></div>
      <div className="section-heading spaced"><div><h2>Spending categories</h2><p>Suggested from transaction descriptions. You can correct any category.</p></div></div>
      {transactions.length === 0 ? <Empty title="No completed spending yet" detail="Completed outgoing wallet transactions will be categorized here." /> : <div className="transaction-list">{transactions.map((item) => <article className="transaction-row" key={item.id}><div className="transaction-icon"><ChartNoAxesCombined size={16} /></div><div className="transaction-main"><strong>{item.description}</strong><small>{formatWhen(item.created_at)} · {formatMoney(item.amount, item.currency)}{item.is_manual ? ' · corrected' : ''}</small></div><select aria-label={`Category for ${item.description}`} value={item.category} disabled={saving === item.id} onChange={(event) => changeCategory(item, event.target.value)}>{categories.map((category) => <option key={category} value={category}>{category}</option>)}</select></article>)}</div>}
      <div className="section-heading spaced"><div><h2>Cash-flow forecast</h2><p>Historical estimate and obligations you confirmed</p></div></div>
      <div className="notice-card"><ChartNoAxesCombined size={18} /><div><strong>Predicted spending {formatMoney(data.forecast.predicted_spending, data.currency)}</strong><p>Confirmed obligations: {formatMoney(data.forecast.confirmed_obligations_total, data.currency)}. Total projected outgoing: {formatMoney(data.forecast.predicted_total_outgoing, data.currency)}. Predicted spending uses completed outflows in the last two full months.</p></div></div>
      <section className="section-heading spaced"><div><h2>Recurring payments</h2><p>Suggestions require your confirmation before they count as obligations.</p></div><button className="primary-button" disabled={detecting} onClick={detectRecurring}>{detecting ? 'Checking…' : 'Detect recurring payments'}</button></section>
      {!data.recurring_payments.length ? <Empty title="No recurring payment records" detail="Run detection to look for same-description, same-amount payments across three or more months." /> : <div className="transaction-list">{data.recurring_payments.map((item) => <article className="transaction-row" key={item.id}><div className="transaction-icon"><Sparkles size={16} /></div><div className="transaction-main"><strong>{item.description}</strong><small>{formatMoney(item.amount, data.currency)} · {item.frequency}{item.next_due ? ` · next due ${item.next_due}` : ''}</small></div><StatusPill value={item.status} />{item.status === 'suggested' && <><button className="secondary-button" disabled={saving === `recurring-${item.id}`} onClick={() => updateRecurring(item, 'confirm')}>Confirm</button><button className="text-button" disabled={saving === `recurring-${item.id}`} onClick={() => updateRecurring(item, 'dismiss')}>Dismiss</button></>}</article>)}</div>}
      <div className="section-heading spaced"><div><h2>Monthly reports</h2><p>Recent transaction totals, including a truthful category breakdown.</p></div></div>
      {!data.reports.length ? <Empty title="No monthly reports yet" /> : <div className="transaction-list">{data.reports.map((report) => <article className="transaction-row" key={`${report.period.year}-${report.period.month}`}><div className="transaction-main"><strong>{new Date(report.period.year, report.period.month - 1).toLocaleString(undefined, { month: 'long', year: 'numeric' })}</strong><small>{report.completed_transaction_count} completed transactions</small></div><span>In {formatMoney(report.incoming, data.currency)} · Out {formatMoney(report.outgoing, data.currency)}</span></article>)}</div>}
      <FinancialCalendar />
    </>}
  </>;
}
