import { useCallback, useEffect, useState } from 'react';
import { ArrowDownLeft, ArrowLeftRight, ArrowRight, ArrowUpRight, Clock3, ShieldCheck, WalletCards } from 'lucide-react';
import { Link } from 'react-router-dom';
import { walletApi } from '../api/services.js';
import { formatMoney, formatWhen } from '../utils/format.js';
import { Empty, ErrorState, Loading, PageTitle, StatusPill } from '../components/Feedback.jsx';
import { useAuth } from '../context/AuthContext.jsx';

export function Overview() {
  const { user } = useAuth();
  const [wallet, setWallet] = useState(null); const [transactions, setTransactions] = useState([]); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = useCallback(async () => { setLoading(true); setError(''); try { const [w, t] = await Promise.all([walletApi.get(), walletApi.transactions('?page_size=5')]); setWallet(w.data); setTransactions(t.data.results || []); } catch (e) { setError(e.message); } finally { setLoading(false); } }, []);
  useEffect(() => { load(); }, [load]);
  return <><PageTitle eyebrow="YOUR FINANCIAL PICTURE" title={`Good to see you ${user?.username || ''}`.trim()} detail="Here’s a clear view of what’s happening with your money." action={<span className="today-label"><Clock3 size={14} /> Account overview</span>} />
    {loading ? <Loading label="Loading your account" /> : error ? <ErrorState error={error} onRetry={load} /> : <>
      <section className="overview-grid">
        <article className="balance-card"><div className="balance-card-head"><div className="balance-icon"><WalletCards size={18} /></div><span>AVAILABLE BALANCE</span><span className="balance-verified"><ShieldCheck size={14} /> Verified</span></div><div className="balance-amount">{formatMoney(wallet.balance, wallet.currency)}</div><div className="balance-foot"><span>Account ending in <strong>{wallet.account_number?.slice(-4) || '—'}</strong></span><span className={`wallet-state ${wallet.is_frozen ? 'frozen' : ''}`}><i /> {wallet.is_frozen ? 'Wallet frozen' : 'Wallet active'}</span></div><div className="balance-decoration" /></article>
        <article className="welcome-card"><div className="welcome-mark"><ShieldCheck size={18} /></div><div className="eyebrow">SECURITY CHECK</div><h3>Your account is<br />being monitored.</h3><p>FinGuard watches for unusual activity and keeps your financial updates together.</p><Link to="/wallet">Security centre <ArrowRight size={14} /></Link><div className="welcome-watermark"><ShieldCheck size={118} /></div></article>
      </section>
      <div className="section-heading"><div><h2>Recent activity</h2><p>Your latest account transactions</p></div><Link className="subtle-link" to="/transactions">View all transactions <ArrowRight size={14} /></Link></div>
      <TransactionTable transactions={transactions} />
      <section className="quick-actions"><div className="quick-intro"><span className="eyebrow">GET THINGS DONE</span><h2>What would you like to do?</h2><p>Manage your wallet and make secure payments.</p></div><Link to="/transactions" className="quick-card"><div className="quick-icon teal"><ArrowLeftRight size={18} /></div><strong>Send money</strong><span>Transfer to a saved beneficiary</span><ArrowRight className="quick-arrow" size={15} /></Link><Link to="/payments" className="quick-card"><div className="quick-icon orange"><ArrowDownLeft size={18} /></div><strong>Add money</strong><span>Deposit with M-Pesa</span><ArrowRight className="quick-arrow" size={15} /></Link><Link to="/wallet" className="quick-card"><div className="quick-icon blue"><WalletCards size={18} /></div><strong>Wallet details</strong><span>Account and beneficiaries</span><ArrowRight className="quick-arrow" size={15} /></Link></section>
    </>}
  </>;
}

export function TransactionTable({ transactions, compact = false }) {
  if (!transactions?.length) return <Empty title="No transactions yet" detail="When money moves in your account, it will show up here." />;
  return <div className="table-wrap"><table><thead><tr><th>TRANSACTION</th><th>REFERENCE</th><th>DATE</th><th>STATUS</th><th className="align-right">AMOUNT</th></tr></thead><tbody>{transactions.map((txn) => <tr key={txn.id}><td><div className="table-entity"><span className={`transaction-direction ${txn.direction === 'credit' ? 'credit' : ''}`}>{txn.direction === 'credit' ? <ArrowDownLeft size={15} /> : <ArrowUpRight size={15} />}</span><span><strong>{txn.counterparty?.name || (txn.type === 'deposit' ? 'M-Pesa deposit' : 'Transfer')}</strong><small>{txn.type} · {txn.direction}</small></span></div></td><td className="mono-cell">{txn.reference}</td><td>{formatWhen(txn.created_at)}</td><td><StatusPill value={txn.status} /></td><td className={`money-cell ${txn.direction === 'credit' ? 'positive' : ''}`}>{txn.direction === 'credit' ? '+' : '−'}{formatMoney(txn.amount, txn.currency)}</td></tr>)}</tbody></table></div>;
}
