import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Download, History, Search } from 'lucide-react';
import { savingsApi } from '../../api/services.js';
import { EmptyState, Panel, Skeleton } from '../../components/dashboard/ui.jsx';
import { day, ksh } from '../../components/dashboard/format.js';

const BLANK = { q: '', type: '', source: '', from: '', to: '' };

const csvCell = (v) => { const t = v === null || v === undefined ? '' : String(v); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };

export function buildStatementCsv(rows, filters, totals) {
  const lines = [['FinGuard savings statement'], ['Filters', Object.entries(filters).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join('; ') || 'none'],
    ['Contributed', totals.contributed], ['Withdrawn', totals.withdrawn], ['Net into savings', totals.net], [],
    ['Date', 'Description', 'Goal', 'Type', 'Source', 'Amount (KES)', 'Status', 'Ledger entry'],
    ...rows.map((r) => [r.created_at, r.description, r.goal_name, r.direction, r.source, r.signed_amount, r.status, r.ledger_entry_id])];
  return lines.map((cells) => cells.map(csvCell).join(',')).join('\n');
}

export function ActivitySection({ refreshKey }) {
  const [filters, setFilters] = useState(BLANK);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState(false);
  const request = useRef(0);

  useEffect(() => { const t = setTimeout(() => { setFilters((f) => ({ ...f, q: query })); setPage(1); }, 300); return () => clearTimeout(t); }, [query]);
  useEffect(() => {
    const id = ++request.current;
    setError('');
    savingsApi.activity({ ...filters, page }).then(({ data: result }) => { if (id === request.current) setData(result); })
      .catch((e) => { if (id === request.current) { setError(e.message); setData((d) => d || { count: 0, results: [], pages: 1, page: 1 }); } });
  }, [filters, page, refreshKey]);

  const setFilter = (key) => (e) => { setFilters((f) => ({ ...f, [key]: e.target.value })); setPage(1); };
  const filtered = Object.values(filters).some(Boolean);
  async function download() {
    setExporting(true); setError('');
    try {
      const { data: all } = await savingsApi.activity({ ...filters, export: '1' });
      const blob = new Blob([buildStatementCsv(all.results, filters, all.totals)], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = Object.assign(document.createElement('a'), { href: url, download: `finguard-savings-statement-${new Date().toISOString().slice(0, 10)}.csv` });
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e.message); } finally { setExporting(false); }
  }
  return <Panel title="Savings activity" subtitle="Every completed contribution and withdrawal. Failed movements never change balances and are not recorded here."
    action={<button className="ins-btn" onClick={download} disabled={exporting || !data?.count}><Download size={14} /> {exporting ? 'Preparing…' : 'Download statement'}</button>}>
    <div className="sv-filters">
      <label className="sv-search"><Search size={14} /><input type="search" aria-label="Search activity" placeholder="Search goal or type" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <select aria-label="Transaction type" value={filters.type} onChange={setFilter('type')}><option value="">All types</option><option value="contribution">Contributions</option><option value="withdrawal">Withdrawals</option></select>
      <select aria-label="Source" value={filters.source} onChange={setFilter('source')}><option value="">Manual and automatic</option><option value="manual">Manual</option><option value="automatic">Automatic</option></select>
      <input type="date" aria-label="From date" value={filters.from} max={filters.to || undefined} onChange={setFilter('from')} />
      <input type="date" aria-label="To date" value={filters.to} min={filters.from || undefined} onChange={setFilter('to')} />
      {filtered && <button className="ins-btn ghost" onClick={() => { setFilters(BLANK); setQuery(''); setPage(1); }}>Clear</button>}
    </div>
    {error && <p className="ins-error">{error}</p>}
    {data === null ? <><Skeleton height={38} /><Skeleton height={38} /><Skeleton height={38} /></> : !data.results.length ?
      <EmptyState icon={History} title={filtered ? 'No activity matches these filters' : 'No savings activity yet'} detail={filtered ? 'Try a wider date range or clear the filters.' : 'Contributions and withdrawals appear here as soon as they complete.'} /> : <>
        <div className="ins-table-wrap"><table className="ins-table stack">
          <thead><tr><th>Date</th><th>Description</th><th>Goal</th><th>Type</th><th className="n">Amount</th><th>Status</th></tr></thead>
          <tbody>{data.results.map((r) => <tr key={r.id}>
            <td>{day(r.created_at)}<small className="ins-muted"> {new Date(r.created_at).toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit' })}</small></td>
            <td data-label="Description">{r.description}</td><td data-label="Goal">{r.goal_name}</td>
            <td data-label="Type"><span className={`ins-chip ${r.direction === 'contribution' ? 'info' : 'warn'}`}>{r.direction === 'contribution' ? 'Contribution' : 'Withdrawal'}</span></td>
            <td data-label="Amount" className={`n ${Number(r.signed_amount) < 0 ? 'neg' : 'pos'}`}>{Number(r.signed_amount) < 0 ? '' : '+'}{ksh(r.signed_amount)}</td>
            <td data-label="Status"><span className="ins-chip good">Completed</span></td>
          </tr>)}</tbody></table></div>
        <div className="sv-pager">
          <span>{data.count} movement{data.count === 1 ? '' : 's'} · in {ksh(data.totals.contributed)} · out {ksh(data.totals.withdrawn)}</span>
          <span className="ins-actions"><button className="ins-icon-btn" disabled={data.page <= 1} onClick={() => setPage(data.page - 1)} aria-label="Previous page"><ChevronLeft size={15} /></button>
            <span>Page {data.page} of {data.pages}</span>
            <button className="ins-icon-btn" disabled={data.page >= data.pages} onClick={() => setPage(data.page + 1)} aria-label="Next page"><ChevronRight size={15} /></button></span>
        </div>
      </>}
  </Panel>;
}
