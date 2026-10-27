import { useCallback, useEffect, useState } from 'react';
import { Activity, ArrowRight, Bell, RefreshCw, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { fraudApi } from '../api/services.js';
import { formatMoney, formatWhen } from '../utils/format.js';
import { Empty, ErrorState, Loading, PageTitle, StatusPill } from '../components/Feedback.jsx';

const labels = {
  'transaction.completed': 'Transfer completed',
  'transaction.received': 'Money received',
  'transaction.under_review': 'Transfer under review',
  'transaction.blocked': 'Transfer blocked',
  'transaction.rejected': 'Transfer rejected',
};

function EventCard({ event }) {
  const payload = event.payload || {};
  const incoming = event.type === 'transaction.received';
  const title = labels[event.type] || event.type?.replaceAll('.', ' ').replaceAll('_', ' ') || 'Account update';
  return <article className="event-card"><span className={`event-icon ${incoming ? 'incoming' : ''}`}><Bell size={16} /></span><div className="event-copy"><div className="event-title-row"><strong>{title}</strong>{payload.status && <StatusPill value={payload.status} />}</div><p>{incoming && payload.amount ? `You received ${formatMoney(payload.amount, payload.currency)}.` : payload.reference ? `Transaction ${payload.reference}.` : 'There is an update to your account activity.'}</p><small>{formatWhen(event.at)} · Event {event.id}</small></div>{payload.reference && <Link aria-label={`View transaction history for ${payload.reference}`} to="/transactions"><ArrowRight size={15} /></Link>}</article>;
}

export function Notifications() {
  const [events, setEvents] = useState([]); const [cursor, setCursor] = useState(0); const [hasMore, setHasMore] = useState(true); const [loading, setLoading] = useState(true); const [loadingMore, setLoadingMore] = useState(false); const [error, setError] = useState('');
  const load = useCallback(async (after = 0, append = false) => {
    if (append) setLoadingMore(true); else { setLoading(true); setError(''); }
    try {
      const { data } = await fraudApi.notifications(after);
      const batch = data.events || [];
      setEvents((current) => append ? [...current, ...batch.filter((event) => !current.some((item) => item.id === event.id))] : batch);
      setCursor(batch.reduce((last, event) => Math.max(last, event.id), after));
      setHasMore(batch.length === 100);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); setLoadingMore(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  return <><PageTitle eyebrow="ACCOUNT UPDATES" title="Notifications" detail="A history of transaction and account events returned for your account." action={<span className="secure-chip"><ShieldCheck size={14} /> Private to your account</span>} />
    <div className="notification-note"><Activity size={15} /><span>These are backend event records. The API does not provide read/unread controls.</span><button className="icon-text-button" onClick={() => load()}><RefreshCw size={13} /> Refresh</button></div>
    {loading ? <Loading label="Loading notifications" /> : error ? <ErrorState error={error} onRetry={() => load()} /> : !events.length ? <Empty title="No notifications" detail="Transaction updates and security events will appear here." /> : <>
      <div className="event-list">{[...events].reverse().map((event) => <EventCard key={event.id} event={event} />)}</div>
      {hasMore && <div className="load-more"><button className="secondary-button" disabled={loadingMore} onClick={() => load(cursor, true)}>{loadingMore ? 'Loading…' : 'Load older updates'} <ArrowRight size={14} /></button></div>}
    </>}
  </>;
}
