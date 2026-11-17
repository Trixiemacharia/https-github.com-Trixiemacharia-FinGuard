import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, CalendarClock, ChevronRight, FileText, PieChart, Repeat, ScanSearch, X } from 'lucide-react';
import { insightsApi } from '../../api/services.js';
import { CategoryDoughnut } from './Charts.jsx';
import { CATEGORY_COLORS, CATEGORY_KEYS, categoryLabel, day, ksh, monthLabel, pct } from '../../components/dashboard/format.js';
import { EmptyState, Panel, Skeleton, Trend } from '../../components/dashboard/ui.jsx';

// --- Section 4: spending categories ---------------------------------------------------------------------------------

export function CategoryAnalytics({ data, onChanged }) {
  const [selected, setSelected] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState('');
  const { categories, period } = data;
  const loadRows = useCallback(async (category) => {
    setRows(null); setError('');
    try { setRows((await insightsApi.categoryTransactions({ from: period.from, to: period.to, category })).data.transactions); }
    catch (e) { setError(e.message); setRows([]); }
  }, [period.from, period.to]);
  useEffect(() => { if (selected) loadRows(selected); }, [selected, loadRows]);
  useEffect(() => { setSelected(null); }, [period.from, period.to]);
  const select = useCallback((category) => setSelected((current) => (current === category ? null : category)), []);

  async function recategorize(row, category) {
    setSaving(row.id); setError('');
    try { await insightsApi.categorize(row.id, category); await onChanged(); await loadRows(selected); }
    catch (e) { setError(e.message); }
    finally { setSaving(''); }
  }

  if (!categories.length) {
    return <Panel title="Spending by category" subtitle="Completed payments sent from your wallet">
      <EmptyState icon={PieChart} title="No outgoing transactions in this period" detail="Category analytics appear once you make a completed payment. Try a longer reporting period." />
    </Panel>;
  }
  return <Panel title="Spending by category" subtitle="Select a category to see the payments behind it">
    <div className="ins-category-layout">
      <div className="ins-doughnut-wrap">
        <CategoryDoughnut categories={categories} selected={selected} onSelect={select} />
        <div className="ins-doughnut-center"><span>Total spent</span><strong>{ksh(data.kpis.expenses)}</strong></div>
      </div>
      <div className="ins-table-wrap">
        <table className="ins-table stack">
          <thead><tr><th>Category</th><th className="n">Amount</th><th className="n">Share</th><th className="n">vs previous</th></tr></thead>
          <tbody>{categories.map((c) => <tr key={c.category} className={`clickable ${selected === c.category ? 'selected' : ''}`} onClick={() => select(c.category)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(c.category); } }} aria-selected={selected === c.category}>
            <td><span className="ins-swatch" style={{ background: CATEGORY_COLORS[c.category] || '#C9D2D8' }} />{categoryLabel(c.category)}<small className="ins-muted"> · {c.count}</small></td>
            <td className="n" data-label="Amount">{ksh(c.amount)}</td>
            <td className="n" data-label="Share"><span className="ins-share"><span style={{ width: `${Math.min(100, Number(c.share_percent))}%`, background: CATEGORY_COLORS[c.category] || '#C9D2D8' }} /></span>{Number(c.share_percent).toFixed(1)}%</td>
            <td className="n" data-label="vs previous">{c.change_percent === null ? <span className="ins-muted">{Number(c.previous_amount) ? '—' : 'New'}</span> : <Trend value={c.change_percent} goodWhen="down" suffix="" />}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </div>
    {selected && <div className="ins-drilldown">
      <header><h3>{categoryLabel(selected)} payments · {day(period.from)} – {day(period.to)}</h3><button className="ins-icon-btn" onClick={() => setSelected(null)} aria-label="Close category transactions"><X size={15} /></button></header>
      {error && <p className="ins-error">{error}</p>}
      {rows === null ? <><Skeleton height={36} /><Skeleton height={36} /></> : !rows.length ? <EmptyState icon={ScanSearch} title="No payments left in this category" detail="They may have been moved to another category." /> :
        <div className="ins-table-wrap"><table className="ins-table compact"><thead><tr><th>Description</th><th>Date</th><th className="n">Amount</th><th>Category</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}><td>{row.description}{row.is_manual && <small className="ins-muted"> · corrected</small>}</td><td>{day(row.created_at)}</td><td className="n">{ksh(row.amount)}</td>
            <td><select aria-label={`Category for ${row.description}`} value={row.category} disabled={saving === row.id} onChange={(e) => recategorize(row, e.target.value)}>{CATEGORY_KEYS.map((key) => <option key={key} value={key}>{categoryLabel(key)}</option>)}</select></td></tr>)}</tbody></table></div>}
    </div>}
  </Panel>;
}

// --- Section 5: rule-based analytics ------------------------------------------------------------------------------

export function RuleAnalytics({ data }) {
  const p = data.patterns; const a = data.anomalies;
  return <div className="ins-grid-2">
    <Panel title="Spending patterns" subtitle="Calculated from completed payments in this period">
      {!p.available ? <EmptyState icon={BarChart3} title="No spending to analyse" detail="Patterns appear once there are completed payments in the selected period." /> :
        <dl className="ins-facts">
          <div><dt>Highest category</dt><dd>{categoryLabel(p.highest_category.category)}<small>{ksh(p.highest_category.amount)} · {Number(p.highest_category.share_percent).toFixed(1)}% of spending</small></dd></div>
          <div><dt>Largest payment</dt><dd>{ksh(p.largest_transaction.amount)}<small>{p.largest_transaction.description} · {day(p.largest_transaction.date)}</small></dd></div>
          <div><dt>Average payment</dt><dd>{ksh(p.average_outgoing_value)}<small>{data.kpis.outgoing_count} completed payments</small></dd></div>
          <div><dt>Most active day</dt><dd>{p.most_active_weekday.weekday}s<small>{ksh(p.most_active_weekday.amount)} across {p.most_active_weekday.count} payment{p.most_active_weekday.count === 1 ? '' : 's'}</small></dd></div>
          <div className="wide"><dt>Change in spending</dt><dd>{p.expense_change.change_percent === null ? 'No spending in the previous period to compare' : <>{pct(p.expense_change.change_percent)} vs previous period</>}
            <small>{p.category_changes.length ? p.category_changes.map((c) => `${categoryLabel(c.category)} ${Number(c.change) > 0 ? '+' : ''}${ksh(c.change)}`).join(' · ') : 'No category changes'}</small></dd></div>
        </dl>}
    </Panel>
    <Panel title="Unusually large payments" subtitle="Compared with your own payment history">
      {!a.available ? <EmptyState icon={ScanSearch} title="Not enough history yet" detail={a.reason} /> :
        !a.items.length ? <EmptyState icon={ScanSearch} title="Nothing unusual in this period" detail={`No payment reached the ${ksh(a.threshold)} threshold.`} /> :
          <ul className="ins-list">{a.items.map((item) => <li key={item.id}><span className="ins-list-icon warn"><AlertTriangle size={14} /></span>
            <div><strong>{ksh(item.amount)}</strong><small>{item.description} · {categoryLabel(item.category)} · {day(item.date)}</small></div>
            <span className="ins-chip warn">{Number(item.times_median).toFixed(1)}× median</span></li>)}</ul>}
      <p className="ins-rule">{a.rule}{a.available && <> Median {ksh(a.median)}, 95th percentile {ksh(a.p95)}, from {a.history_count} payments.</>}</p>
    </Panel>
  </div>;
}

// --- Section 5C: recurring payments ---------------------------------------------------------------------------------

export function RecurringSection({ data, onChanged }) {
  const [detecting, setDetecting] = useState(false);
  const [saving, setSaving] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const { items, detection_rule: rule } = data.recurring;

  async function detect() {
    setDetecting(true); setError(''); setMessage('');
    try {
      const { data: queued } = await insightsApi.detectRecurring();
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const { data: status } = await insightsApi.detectionStatus(queued.task_id);
        if (status.status === 'complete') { setMessage(`${status.suggestions_found} recurring payment suggestion${status.suggestions_found === 1 ? '' : 's'} found.`); await onChanged(); return; }
        if (status.status === 'error') throw new Error(status.detail || 'Recurring payment detection failed.');
      }
      setMessage('Detection is still running. Refresh later to see suggestions.');
    } catch (e) { setError(e.message); }
    finally { setDetecting(false); }
  }
  async function update(item, action) {
    setSaving(item.id); setError(''); setMessage('');
    try {
      const nextDue = action === 'confirm' ? window.prompt('Next expected payment date (YYYY-MM-DD), optional:') : undefined;
      await insightsApi.updateRecurring(item.id, { action, ...(nextDue ? { next_due: nextDue } : {}) });
      setMessage(action === 'confirm' ? 'Recurring payment confirmed.' : 'Suggestion dismissed.');
      await onChanged();
    } catch (e) { setError(e.message); }
    finally { setSaving(''); }
  }
  return <Panel title="Recurring payments" subtitle="Suggestions only count as obligations after you confirm them"
    action={<button className="ins-btn primary" disabled={detecting} onClick={detect}>{detecting ? 'Checking…' : 'Detect recurring payments'}</button>}>
    {message && <p className="ins-note">{message}</p>}{error && <p className="ins-error">{error}</p>}
    {!items.length ? <EmptyState icon={Repeat} title="No recurring payments detected" detail="Run detection to look for payments with the same description and amount across three or more months." /> :
      <div className="ins-table-wrap"><table className="ins-table stack">
        <thead><tr><th>Payment</th><th className="n">Amount</th><th>Frequency</th><th>Last paid</th><th>Status</th><th /></tr></thead>
        <tbody>{items.map((item) => <tr key={item.id}>
          <td>{item.description}<small className="ins-muted"> · seen {item.occurrences}×</small></td>
          <td className="n" data-label="Amount">{ksh(item.amount)}</td><td className="cap" data-label="Frequency">{item.frequency}</td>
          <td data-label="Last paid">{day(item.last_transaction_date)}{item.next_due && <small className="ins-muted"> · next {day(item.next_due, { day: 'numeric', month: 'short' })}</small>}</td>
          <td data-label="Status"><span className={`ins-chip ${item.is_confirmed ? 'good' : 'info'}`}>{item.is_confirmed ? 'Confirmed obligation' : 'Detected suggestion'}</span></td>
          <td className="n">{!item.is_confirmed && <span className="ins-actions"><button className="ins-btn" disabled={saving === item.id} onClick={() => update(item, 'confirm')}>Confirm</button><button className="ins-btn ghost" disabled={saving === item.id} onClick={() => update(item, 'dismiss')}>Dismiss</button></span>}</td>
        </tr>)}</tbody></table></div>}
    <p className="ins-rule">Detection rule: {rule}</p>
  </Panel>;
}

// --- Section 5D: forecast -------------------------------------------------------------------------------------------

export function ForecastSection({ data }) {
  const f = data.forecast;
  return <Panel title="Cash-flow forecast" subtitle={`Next 30 days · ${day(f.period.from)} – ${day(f.period.to)}`}>
    {f.available ? <div className="ins-forecast">
      <div><span>Estimated other spending</span><strong>{ksh(f.estimated_other_spending)}</strong><small className="ins-chip info">Estimate</small></div>
      <div><span>Confirmed obligations</span><strong>{ksh(f.confirmed_obligations_total)}</strong><small className="ins-chip good">From your records</small></div>
      <div className="total"><span>Projected outgoing</span><strong>{ksh(f.projected_total_outgoing)}</strong><small>Estimate + confirmed</small></div>
    </div> : <EmptyState icon={CalendarClock} title="Not enough history to forecast" detail={f.reason} />}
    {f.available && <p className="ins-rule">Basis: {f.basis.method} ({f.historical_months.map((m) => `${monthLabel(m.month)} ${ksh(m.outgoing)}`).join(', ')}; average {ksh(f.historical_monthly_average)}). Confirmed obligations are subtracted from the average so they are not counted twice.</p>}
    {f.confirmed_obligations.length > 0 && <ul className="ins-list compact">{f.confirmed_obligations.map((o) => <li key={`${o.source}-${o.source_id}-${o.due_date}`}><span className="ins-list-icon"><CalendarClock size={14} /></span><div><strong>{o.title}</strong><small>{day(o.due_date)} · {categoryLabel(o.category)}</small></div><span>{ksh(o.amount)}</span></li>)}</ul>}
  </Panel>;
}

// --- Section 6: monthly reports ---------------------------------------------------------------------------------------

export function MonthlyReports({ data, onExportCsv, onExportPdf }) {
  const [detail, setDetail] = useState(null);
  const months = data.monthly_reports;
  async function open(month) {
    setDetail({ month, data: null, error: '' });
    try { setDetail({ month, data: (await insightsApi.dashboard({ period: 'custom', from: month.from, to: month.to })).data, error: '' }); }
    catch (e) { setDetail({ month, data: null, error: e.message }); }
  }
  return <Panel title="Monthly financial reports" subtitle="Months within the selected period, most recent first"
    action={<span className="ins-actions"><button className="ins-btn" onClick={onExportCsv}>CSV</button><button className="ins-btn" onClick={onExportPdf}>PDF</button></span>}>
    {!months.some((m) => m.transactions) ? <EmptyState icon={FileText} title="No completed transactions in this period" detail="Monthly reports are built from completed wallet transactions." /> :
      <div className="ins-table-wrap"><table className="ins-table stack">
        <thead><tr><th>Month</th><th className="n">Total income</th><th className="n">Total expenses</th><th className="n">Net cash flow</th><th className="n">Transactions</th><th /></tr></thead>
        <tbody>{months.map((m) => <tr key={m.month} className="clickable" onClick={() => open(m)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') open(m); }}>
          <td>{monthLabel(m.month)}{m.partial && <small className="ins-muted"> · {day(m.from, { day: 'numeric', month: 'short' })}–{day(m.to, { day: 'numeric', month: 'short' })}</small>}</td>
          <td className="n" data-label="Total income">{ksh(m.income)}</td><td className="n" data-label="Total expenses">{ksh(m.expenses)}</td>
          <td data-label="Net cash flow" className={`n ${Number(m.net_cash_flow) < 0 ? 'neg' : Number(m.net_cash_flow) > 0 ? 'pos' : ''}`}>{ksh(m.net_cash_flow)}</td>
          <td className="n" data-label="Transactions">{m.transactions}</td><td className="n hide-stack"><ChevronRight size={15} className="ins-muted" /></td>
        </tr>)}</tbody></table></div>}
    {detail && <div className="ins-modal" role="dialog" aria-modal="true" aria-label={`${monthLabel(detail.month.month)} report`} onClick={(e) => { if (e.target === e.currentTarget) setDetail(null); }}>
      <div className="ins-modal-card">
        <header><div><h2>{monthLabel(detail.month.month)}</h2><p>{day(detail.month.from)} – {day(detail.month.to)}</p></div><button className="ins-icon-btn" onClick={() => setDetail(null)} aria-label="Close report"><X size={16} /></button></header>
        {detail.error ? <p className="ins-error">{detail.error}</p> : !detail.data ? <><Skeleton height={60} /><Skeleton height={120} /></> : <>
          <div className="ins-forecast">
            <div><span>Income</span><strong>{ksh(detail.data.kpis.income)}</strong></div>
            <div><span>Expenses</span><strong>{ksh(detail.data.kpis.expenses)}</strong></div>
            <div className="total"><span>Net cash flow</span><strong className={Number(detail.data.kpis.net_cash_flow) < 0 ? 'neg' : 'pos'}>{ksh(detail.data.kpis.net_cash_flow)}</strong></div>
          </div>
          <h3>Spending by category</h3>
          {detail.data.categories.length ? <table className="ins-table compact"><tbody>{detail.data.categories.map((c) => <tr key={c.category}><td><span className="ins-swatch" style={{ background: CATEGORY_COLORS[c.category] }} />{categoryLabel(c.category)}</td><td className="n">{ksh(c.amount)}</td><td className="n">{Number(c.share_percent).toFixed(1)}%</td></tr>)}</tbody></table> : <p className="ins-muted">No spending this month.</p>}
          {detail.data.kpis.largest_outgoing && <p className="ins-rule">Largest payment: {ksh(detail.data.kpis.largest_outgoing.amount)} · {detail.data.kpis.largest_outgoing.description} · {day(detail.data.kpis.largest_outgoing.date)}. {detail.data.kpis.transactions} completed transactions.</p>}
        </>}
      </div>
    </div>}
  </Panel>;
}
