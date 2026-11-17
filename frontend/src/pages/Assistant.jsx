import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Bot, CheckCircle2, Circle, LoaderCircle, Send, ShieldCheck } from 'lucide-react';
import { assistantApi } from '../api/services.js';
import { Empty, ErrorState, Loading, PageTitle, StatusPill } from '../components/Feedback.jsx';
import { formatMoney, formatWhen } from '../utils/format.js';
import './assistant.css';

function toolLabel(tool) {
  return ({ wallet_balance: 'Read wallet balance', recent_transactions: 'Read recent transactions', monthly_spending: 'Calculate monthly spending', savings_goals: 'Read savings goals' })[tool] || tool;
}

export function Assistant() {
  const [capabilities, setCapabilities] = useState(null); const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const [plan, setPlan] = useState([]);
  useEffect(() => { assistantApi.capabilities().then(({ data }) => setCapabilities(data)).catch(() => setCapabilities({ mode: 'read_only', language_provider_available: false })); }, []);
  async function ask(event) {
    event.preventDefault(); if (!question.trim()) return;
    setLoading(true); setError(''); setResult(null);
    setPlan([{ tool: 'account_grounded_lookup', status: 'pending', detail: 'Waiting to read your account records.' }]);
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    setPlan([{ tool: 'account_grounded_lookup', status: 'running', detail: 'Selecting a deterministic account tool.' }]);
    try {
      const { data } = await assistantApi.ask(question.trim());
      setResult(data); setPlan(data.plan || []);
    } catch (e) {
      setError(e.message); setPlan([{ tool: 'account_grounded_lookup', status: 'failed', detail: e.message }]);
    } finally { setLoading(false); }
  }
  const toolData = result?.tool_results?.[0]?.data;
  return <><PageTitle eyebrow="ACCOUNT-GROUNDED HELP" title="AI assistant" detail="The assistant reads your wallet records through deterministic tools. It cannot move money." action={<span className="secure-chip"><ShieldCheck size={14} /> Read-only</span>} />
    {capabilities === null ? <Loading label="Checking assistant tools" /> : <>
      <form className="assistant-prompt" onSubmit={ask}><label htmlFor="assistant-question">Ask about your account</label><div><input id="assistant-question" maxLength="500" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="For example: What is my current balance?" /><button className="primary-button" type="submit" disabled={loading || !question.trim()}>{loading ? <LoaderCircle size={16} className="assistant-spin" /> : <Send size={15} />}{loading ? 'Checking…' : 'Ask'}</button></div><small>Try balance, recent transactions, monthly spending, or savings goals.</small></form>
      {loading && <section className="assistant-result"><h2>Plan</h2>{plan.map((step) => <div className="assistant-plan-step" key={step.tool}><LoaderCircle size={16} className="assistant-spin" /><span>{toolLabel(step.tool)}</span><StatusPill value={step.status} /></div>)}</section>}
      {error && <ErrorState error={error} />}
      {result && <section className="assistant-result" aria-live="polite"><h2>Plan</h2>{result.plan?.length ? result.plan.map((step, index) => <div className="assistant-plan-step" key={`${step.tool}-${index}`}>{step.status === 'completed' ? <CheckCircle2 size={16} /> : step.status === 'running' ? <LoaderCircle size={16} className="assistant-spin" /> : <Circle size={16} />}<span>{toolLabel(step.tool)}{step.detail ? ` · ${step.detail}` : ''}</span><StatusPill value={step.status} /></div>) : <div className="assistant-plan-step"><Circle size={16} /><span>No account tool was run.</span><StatusPill value="completed" /></div>}
        <div className="assistant-answer"><span className="eyebrow">{result.support_status === 'answered' ? 'ACCOUNT ANSWER' : 'REQUEST STATUS'}</span><p>{result.answer}</p>{result.language_provider && <small>Response wording: {result.language_provider === 'openai' ? 'language provider' : 'deterministic fallback'}</small>}</div>
        {result.requires_approval && <div className="error-state"><ShieldCheck size={17} /><span>Nothing was executed. This request could affect money or account settings; review and submit it yourself in the relevant screen.</span><Link className="text-button" to={question.toLowerCase().includes('freez') ? '/wallet' : question.toLowerCase().includes('send') || question.toLowerCase().includes('transfer') || question.toLowerCase().includes('pay') ? '/payments' : '/savings'}>Review request <ArrowRight size={14} /></Link></div>}
        {toolData?.balance !== undefined && <div className="assistant-fact"><span>Wallet balance</span><strong>{formatMoney(toolData.balance, toolData.currency)}</strong><small>{toolData.is_frozen ? 'Wallet frozen' : 'Wallet active'}</small></div>}
        {toolData?.report && <div className="assistant-facts"><div className="assistant-fact"><span>Completed outgoing this month</span><strong>{formatMoney(toolData.report.outgoing, toolData.report.currency)}</strong></div><div className="assistant-fact"><span>Completed incoming this month</span><strong>{formatMoney(toolData.report.incoming, toolData.report.currency)}</strong></div></div>}
        {toolData?.transactions && (toolData.transactions.length ? <><h3>Cited transactions</h3><div className="transaction-list">{toolData.transactions.map((txn) => <article className="transaction-row" key={txn.id}><div className="transaction-main"><strong>{txn.description || txn.reference}</strong><small>{txn.reference} · {formatWhen(txn.created_at)} · {txn.direction}</small></div><span>{formatMoney(txn.amount, txn.currency)}</span></article>)}</div></> : <Empty title="No completed transactions found" detail="There are no completed transactions to cite for this request." />)}
        {toolData?.goals && (toolData.goals.length ? <div className="transaction-list">{toolData.goals.map((goal) => <article className="transaction-row" key={goal.id}><div className="transaction-main"><strong>{goal.name}</strong><small>Saved {formatMoney(goal.saved_amount, goal.currency)} of {formatMoney(goal.target_amount, goal.currency)}</small></div><StatusPill value="completed" /></article>)}</div> : <Empty title="No active savings goals" detail="Create a goal in Savings to track progress." />)}
        {result.citations?.length > 0 && <p className="assistant-citation-note">Citations are transaction records from your account. References and timestamps above identify each record.</p>}
      </section>}
    </>}
  </>;
}
