import { AlertCircle, RefreshCw } from 'lucide-react';

export function ErrorState({ error, onRetry }) {
  return <div className="error-state" role="alert"><AlertCircle size={18} /><span>{error?.message || String(error || 'Something went wrong.')}</span>{onRetry && <button className="text-button" onClick={onRetry}><RefreshCw size={14} /> Retry</button>}</div>;
}
export function Loading({ label = 'Loading' }) { return <div className="loading"><span className="spinner" />{label}…</div>; }
export function Empty({ title = 'Nothing here yet', detail = 'New activity will appear here.' }) { return <div className="empty"><span className="empty-mark">—</span><strong>{title}</strong><p>{detail}</p></div>; }
export function StatusPill({ value }) {
  const tone = /complete|success|approved|low/i.test(value) ? 'success' : /pending|review|processing|medium/i.test(value) ? 'warning' : /reject|fail|block|high|frozen|cancel/i.test(value) ? 'danger' : 'neutral';
  return <span className={`status-pill ${tone}`}>{String(value || 'unknown').replaceAll('_', ' ')}</span>;
}
export function PageTitle({ eyebrow, title, detail, action }) { return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{detail && <p>{detail}</p>}</div>{action && <div className="title-action">{action}</div>}</div>; }
