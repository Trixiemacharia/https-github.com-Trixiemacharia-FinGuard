import { useEffect, useRef } from 'react';
import { ArrowDownRight, ArrowUpRight, Minus, X } from 'lucide-react';
import { ksh, pct } from './format.js';

export function Panel({ title, subtitle, action, children, className = '', id }) {
  return <section className={`ins-panel ${className}`} id={id}>
    {(title || action) && <header className="ins-panel-head"><div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>{action && <div className="ins-panel-action">{action}</div>}</header>}
    {children}
  </section>;
}

export function EmptyState({ icon: Icon, title, detail, action }) {
  return <div className="ins-empty" role="status">
    {Icon && <span className="ins-empty-icon"><Icon size={18} /></span>}
    <strong>{title}</strong>{detail && <p>{detail}</p>}{action}
  </div>;
}

export function Skeleton({ height = 16, width = '100%' }) {
  return <span className="ins-skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function DashboardSkeleton() {
  return <div aria-busy="true" aria-label="Loading financial insights">
    <div className="ins-kpis">{[0, 1, 2, 3].map((i) => <div className="ins-kpi" key={i}><Skeleton width="45%" height={12} /><Skeleton width="70%" height={26} /><Skeleton width="55%" height={12} /></div>)}</div>
    <div className="ins-grid-2">{[0, 1].map((i) => <div className="ins-panel" key={i}><Skeleton width="35%" height={14} /><Skeleton height={240} /></div>)}</div>
  </div>;
}

/** Change badge. `goodWhen` says which direction is favourable for this metric. */
export function Trend({ value, goodWhen = 'up', suffix = 'vs previous period' }) {
  if (value === null || value === undefined) return <span className="ins-trend neutral"><Minus size={13} /> No previous data</span>;
  const n = Number(value);
  const tone = n === 0 || goodWhen === 'none' ? 'neutral' : (n > 0) === (goodWhen === 'up') ? 'good' : 'bad';
  const Icon = n > 0 ? ArrowUpRight : n < 0 ? ArrowDownRight : Minus;
  return <span className={`ins-trend ${tone}`}><Icon size={13} /> {pct(n)} <span className="ins-trend-note">{suffix}</span></span>;
}

export function KpiCards({ data }) {
  const k = data.kpis; const c = data.comparison;
  const net = Number(k.net_cash_flow);
  const cards = [
    { key: 'income', label: 'Total income', value: ksh(k.income), trend: <Trend value={c.income.change_percent} />, foot: `${k.incoming_count} incoming · previous ${ksh(c.income.previous)}` },
    { key: 'expenses', label: 'Total expenses', value: ksh(k.expenses), trend: <Trend value={c.expenses.change_percent} goodWhen="down" />, foot: `${k.outgoing_count} outgoing · previous ${ksh(c.expenses.previous)}` },
    { key: 'net', label: 'Net cash flow', value: ksh(k.net_cash_flow), tone: net < 0 ? 'neg' : net > 0 ? 'pos' : '', trend: <span className={`ins-status ${net < 0 ? 'bad' : net > 0 ? 'good' : 'neutral'}`}>{net < 0 ? 'Spending exceeded income' : net > 0 ? 'Income exceeded spending' : 'Break-even'}</span>, foot: `Previous ${ksh(c.net_cash_flow.previous)}${k.savings_rate !== null ? ` · ${Number(k.savings_rate).toFixed(1)}% of income kept` : ''}` },
    { key: 'count', label: 'Total transactions', value: k.transactions.toLocaleString('en-KE'), trend: <Trend value={c.transactions.change_percent} goodWhen="none" />, foot: k.average_transaction_value ? `Average value ${ksh(k.average_transaction_value)}` : 'No completed transactions' },
  ];
  return <div className="ins-kpis">{cards.map((card) => <article className="ins-kpi" key={card.key}>
    <span className="ins-kpi-label">{card.label}</span>
    <strong className={`ins-kpi-value ${card.tone || ''}`}>{card.value}</strong>
    {card.trend}
    <small>{card.foot}</small>
  </article>)}</div>;
}

/** Accessible modal: Escape and backdrop close it, focus moves inside on open and returns on close. */
export function Modal({ title, subtitle, onClose, children, footer, width = 520, busy = false }) {
  const cardRef = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    // Focus the first form field; dialogs without one take focus themselves (no stray focus ring on a button).
    const first = cardRef.current?.querySelector('input,select,textarea') || cardRef.current;
    first?.focus();
    const onKey = (event) => { if (event.key === 'Escape' && !busy) onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus?.(); };
  }, [onClose, busy]);
  return <div className="ins-modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <div className="ins-modal-card" ref={cardRef} tabIndex={-1} style={{ width: `min(${width}px, 100%)` }}>
      <header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="ins-icon-btn" onClick={onClose} disabled={busy} aria-label="Close"><X size={16} /></button></header>
      {children}
      {footer && <footer className="ins-modal-footer">{footer}</footer>}
    </div>
  </div>;
}

export function ConfirmDialog({ title, message, confirmLabel = 'Confirm', tone = 'primary', busy, onConfirm, onCancel }) {
  return <Modal title={title} onClose={onCancel} busy={busy} width={440}
    footer={<><button className="ins-btn ghost" onClick={onCancel} disabled={busy}>Cancel</button><button className={`ins-btn ${tone}`} onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : confirmLabel}</button></>}>
    <div className="ins-confirm-body">{message}</div>
  </Modal>;
}

/** Success/error banner. Success messages clear themselves; errors stay until dismissed. */
export function Feedback({ feedback, onDismiss }) {
  useEffect(() => {
    if (feedback?.type !== 'success') return undefined;
    const timer = setTimeout(onDismiss, 6000);
    return () => clearTimeout(timer);
  }, [feedback, onDismiss]);
  if (!feedback) return null;
  return <div className={`ins-feedback ${feedback.type}`} role={feedback.type === 'error' ? 'alert' : 'status'}>
    <span>{feedback.text}</span><button className="ins-icon-btn" onClick={onDismiss} aria-label="Dismiss"><X size={14} /></button>
  </div>;
}
