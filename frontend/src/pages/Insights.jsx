import { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { AlertCircle, BarChart3, Download, LineChart, RefreshCw } from 'lucide-react';
import { insightsApi } from '../api/services.js';
import { PageTitle } from '../components/Feedback.jsx';
import { IncomeExpenseChart, NetFlowChart } from './insights/Charts.jsx';
import { CalendarSection } from './insights/CalendarSection.jsx';
import { downloadCsv, printReport } from './insights/exportReport.js';
import { day, PERIOD_OPTIONS } from '../components/dashboard/format.js';
import { DashboardSkeleton, EmptyState, KpiCards, Panel } from '../components/dashboard/ui.jsx';
import { CategoryAnalytics, ForecastSection, MonthlyReports, RecurringSection, RuleAnalytics } from './insights/Sections.jsx';
import '../components/dashboard/dashboard.css';

const LOCAL_TZ = 'Africa/Nairobi';
const localToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: LOCAL_TZ }).format(new Date());
const STALE_MS = 5 * 60 * 1000;

function LiveIndicator({ live, updatedAt, refreshing }) {
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick((n) => n + 1), 30000); return () => clearInterval(id); }, []);
  if (!updatedAt) return null;
  const age = Date.now() - updatedAt.getTime();
  const time = updatedAt.toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit' });
  const isLive = live === 'connected';
  const label = refreshing ? 'Updating…' : isLive ? `Live · updated ${time}` : age > STALE_MS ? `Not live · figures from ${time}` : `Updated ${time}`;
  return <span className={`ins-live ${isLive && !refreshing ? 'on' : ''}`} title={isLive ? 'Connected: new wallet activity refreshes these figures automatically.' : 'Live updates are not connected. Use Refresh for the latest figures.'}><span className="dot" />{label}</span>;
}

export function Insights() {
  const outlet = useOutletContext() || {};
  const [period, setPeriod] = useState('last_30_days');
  const [custom, setCustom] = useState({ from: '', to: '' });
  const [applied, setApplied] = useState({ period: 'last_30_days' });
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [calendarKey, setCalendarKey] = useState(0);
  const requestId = useRef(0);

  const load = useCallback(async (params = applied, { quiet = false } = {}) => {
    const id = ++requestId.current; // later requests win; earlier responses are ignored
    if (quiet) setRefreshing(true); else setLoading(true);
    setError('');
    try {
      const { data: result } = await insightsApi.dashboard(params);
      if (id !== requestId.current) return;
      setData(result); setUpdatedAt(new Date());
    } catch (e) {
      if (id === requestId.current) setError(e.message);
    } finally {
      if (id === requestId.current) { setLoading(false); setRefreshing(false); }
    }
  }, [applied]);
  useEffect(() => { load(applied); }, [applied]); // eslint-disable-line react-hooks/exhaustive-deps

  // New wallet activity arrives over the existing live connection: refresh quietly, once per burst.
  const firstEvent = useRef(outlet.eventCount);
  useEffect(() => {
    if (outlet.eventCount === undefined || outlet.eventCount === firstEvent.current) return undefined;
    const timer = setTimeout(() => { load(applied, { quiet: true }); setCalendarKey((n) => n + 1); }, 1500);
    return () => clearTimeout(timer);
  }, [outlet.eventCount]); // eslint-disable-line react-hooks/exhaustive-deps

  function choosePeriod(value) {
    setPeriod(value);
    if (value !== 'custom') setApplied({ period: value });
  }
  function applyCustom(event) {
    event.preventDefault();
    if (custom.from && custom.to) setApplied({ period: 'custom', from: custom.from, to: custom.to });
  }
  const refresh = () => { load(applied, { quiet: Boolean(data) }); setCalendarKey((n) => n + 1); };
  const refreshQuiet = useCallback(() => load(applied, { quiet: true }), [load, applied]);
  const exportAs = (kind) => { setExportOpen(false); if (data) { if (kind === 'csv') downloadCsv(data); else if (!printReport(data)) setError('Allow pop-ups for this site to export a PDF.'); } };
  const today = localToday();
  const hasActivity = data && data.kpis.transactions > 0;

  return <div className="ins">
    <PageTitle eyebrow="REPORTING" title="Financial Insights" detail="Understand your financial activity through clear, data-driven reporting."
       />

    <div className="ins-toolbar">
      <div className="ins-toolbar-left">
        <label className="ins-select"><span>Reporting period</span>
          <select value={period} onChange={(e) => choosePeriod(e.target.value)}>{PERIOD_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {period === 'custom' && <form className="ins-range" onSubmit={applyCustom}>
          <label><span>From</span><input type="date" required max={custom.to || today} value={custom.from} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} /></label>
          <label><span>To</span><input type="date" required min={custom.from || undefined} max={today} value={custom.to} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} /></label>
          <button className="ins-btn primary" type="submit" disabled={!custom.from || !custom.to}>Apply</button>
        </form>}
        {data && <span className="ins-period-note">{day(data.period.from)} – {day(data.period.to)} · compared with {day(data.period.previous_from)} – {day(data.period.previous_to)}</span>}
      </div>
      <div className="ins-toolbar-right">
        <button className="ins-btn" onClick={refresh} disabled={loading || refreshing}><RefreshCw size={14} className={refreshing ? 'ins-spin' : ''} /> Refresh</button>
        <div className="ins-menu">
          <button className="ins-btn" onClick={() => setExportOpen((o) => !o)} disabled={!data} aria-haspopup="menu" aria-expanded={exportOpen}><Download size={14} /> Export report</button>
          {exportOpen && <div className="ins-menu-list" role="menu"><button role="menuitem" onClick={() => exportAs('csv')}>CSV spreadsheet</button><button role="menuitem" onClick={() => exportAs('pdf')}>PDF (print)</button></div>}
        </div>
      </div>
    </div>

    {error && <div className="ins-banner" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="ins-btn" onClick={refresh}>Try again</button></div>}
    {loading && !data ? <DashboardSkeleton /> : data && <div className={refreshing || loading ? 'ins-dim' : ''}>
      <KpiCards data={data} />

      <div className="ins-grid-2 wide-first">
        <Panel title="Income vs expenses" subtitle={`Completed transactions per ${data.period.granularity}`}>
          {hasActivity ? <IncomeExpenseChart series={data.series} granularity={data.period.granularity} />
            : <EmptyState icon={BarChart3} title="No completed transactions in this period" detail="Deposits and payments will appear here once they complete. Try a longer reporting period." />}
          {hasActivity && !data.kpis.incoming_count && <p className="ins-rule">No incoming transactions in this period.</p>}
          {hasActivity && !data.kpis.outgoing_count && <p className="ins-rule">No outgoing transactions in this period.</p>}
        </Panel>
        <Panel title="Net cash flow trend" subtitle="Income minus expenses per period">
          {hasActivity ? <NetFlowChart series={data.series} granularity={data.period.granularity} />
            : <EmptyState icon={LineChart} title="No cash flow to chart" detail="Net cash flow is calculated from completed incoming and outgoing transactions." />}
        </Panel>
      </div>

      <CategoryAnalytics data={data} onChanged={refreshQuiet} />
      <RuleAnalytics data={data} />
      <RecurringSection data={data} onChanged={refreshQuiet} />
      <ForecastSection data={data} />
      <MonthlyReports data={data} onExportCsv={() => exportAs('csv')} onExportPdf={() => exportAs('pdf')} />
      <CalendarSection refreshKey={calendarKey} />
      <ul className="ins-data-rules">{data.data_rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>
    </div>}
  </div>;
}
