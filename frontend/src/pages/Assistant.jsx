import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Circle, CircleX, LoaderCircle, Send, ShieldCheck } from 'lucide-react';
import { assistantApi } from '../api/services.js';
import { ErrorState, Loading, PageTitle } from '../components/Feedback.jsx';
import { formatMoney } from '../utils/format.js';
import './assistant.css';

const POLL_MS = 600;
const MAX_POLLS = 100;
const VERDICT_TEXT = { affordable: 'Affordable', tight: 'Tight', not_affordable: 'Not affordable', insufficient_history: 'Not enough history', wallet_frozen: 'Wallet frozen', can_save: 'Can save', no_room: 'No room to save', missing_income: 'Income missing' };
const ACTION_SCREENS = { add_calendar_entry: '/insights#financial-calendar', create_savings_goal: '/savings', create_savings_schedule: '/savings', review_recurring_payment: '/insights', open_screen: '/payments' };

function StepIcon({ status }) {
  if (status === 'completed') return <CheckCircle2 size={16} />;
  if (status === 'running') return <LoaderCircle size={16} className="assistant-spin" />;
  if (status === 'failed') return <CircleX size={16} />;
  return <Circle size={16} />;
}

function Steps({ steps }) {
  return <>{steps.map((step) => <div className="assistant-plan-step" key={step.key}><StepIcon status={step.status} /><span>{step.label}{step.detail ? ` · ${step.detail}` : ''}</span><small>{step.status}</small></div>)}</>;
}

export function Assistant() {
  const [capabilities, setCapabilities] = useState(null); const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null); const [steps, setSteps] = useState([]);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const conversationRef = useRef(null); const cancelled = useRef(false);
  useEffect(() => {
    assistantApi.capabilities().then(({ data }) => setCapabilities(data)).catch(() => setCapabilities({ mode: 'read_only', language_provider_available: false }));
    return () => { cancelled.current = true; };
  }, []);

  async function ask(text) {
    const q = (text ?? question).trim(); if (!q) return;
    setQuestion(q); setLoading(true); setError(''); setResult(null);
    setSteps([{ key: 'understand', label: 'Understand the question', status: 'running' }, { key: 'analyse', label: 'Check your wallet balance and records', status: 'pending' }, { key: 'compose', label: 'Write the answer', status: 'pending' }]);
    try {
      const { data: created } = await assistantApi.startRun(q, conversationRef.current);
      conversationRef.current = created.conversation_id; setSteps(created.steps || []);
      let run = created;
      for (let i = 0; !cancelled.current && i < MAX_POLLS && !['completed', 'failed'].includes(run.status); i += 1) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        run = (await assistantApi.run(created.run_id)).data; setSteps(run.steps || []);
      }
      if (run.result) setResult(run.result); else setError('The assistant is still working. Please try again shortly.');
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }
  const submit = (event) => { event.preventDefault(); ask(); };

  return <><PageTitle eyebrow="DECISION ASSISTANT" title="AI assistant" detail="Figures and verdicts are calculated from your wallet records. The assistant is read-only and never moves money." action={<span className="secure-chip"><ShieldCheck size={14} /> Read-only</span>} />
    {capabilities === null ? <Loading label="Checking assistant tools" /> : <>
      <form className="assistant-prompt" onSubmit={submit}><label htmlFor="assistant-question">Ask a money question</label><div><input id="assistant-question" maxLength="500" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about your balance, spending, savings or a purchase" /><button className="primary-button" type="submit" disabled={loading || !question.trim()}>{loading ? <LoaderCircle size={16} className="assistant-spin" /> : <Send size={15} />}{loading ? 'Working…' : 'Ask'}</button></div>
        <small>Covers this wallet only, not cash or other accounts.</small></form>
      {(loading || (steps.length > 0 && !result)) && <section className="assistant-result" aria-live="polite"><h2>Plan</h2><Steps steps={steps} /></section>}
      {error && <ErrorState error={error} />}
      {result && <section className="assistant-result" aria-live="polite">
        <h2>Plan</h2><Steps steps={result.steps || []} />
        <div className="assistant-answer">
          {result.verdict && <span className={`assistant-verdict ${result.verdict}`}>{VERDICT_TEXT[result.verdict] || result.verdict}</span>}
          <p>{result.answer}</p>
          <small>{result.confidence ? `Confidence: ${result.confidence} · ` : ''}Wording: {result.provider?.phrasing === 'deterministic_template' ? 'built-in template' : 'language provider (numbers checked)'}</small>
        </div>
        {result.reasoning?.steps?.length > 0 && <><h3>How I worked it out</h3><ol className="assistant-reasoning">{result.reasoning.steps.map((step, i) => <li key={i}><span>{step.text}</span>{step.calc && <code>{step.calc}</code>}</li>)}</ol></>}
        {result.key_figures?.length > 0 && <div className="assistant-facts">{result.key_figures.map((f) => <div className="assistant-fact" key={f.key}><span>{f.label}</span><strong>{formatMoney(f.amount, f.currency)}</strong></div>)}</div>}
        {result.missing_inputs?.length > 0 && <><h3>Missing information</h3><ul className="assistant-list">{result.missing_inputs.map((m) => <li key={m}>{m === 'housing_cost' ? 'Rent or housing cost is not recorded.' : m === 'expected_income' ? 'Expected income is not recorded.' : m}</li>)}</ul></>}
        {result.assumptions?.length > 0 && <><h3>Assumptions</h3><ul className="assistant-list">{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></>}
        {result.proposed_actions?.length > 0 && <><h3>Suggested next steps (you confirm them)</h3><div className="assistant-actions">{result.proposed_actions.map((a, i) => <Link className="text-button" key={`${a.type}-${i}`} to={ACTION_SCREENS[a.type] || '/overview'}>{a.label} <ArrowRight size={14} /></Link>)}</div></>}
        {result.requires_approval && <div className="error-state"><ShieldCheck size={17} /><span>Nothing was executed. Review and submit it yourself in the relevant screen.</span></div>}
        {result.citation_count > 0 && <p className="assistant-citation-note">Based on {result.citation_count} wallet record{result.citation_count === 1 ? '' : 's'}{result.citation_count > result.citations.length ? ` (first ${result.citations.length} cited)` : ''}.</p>}
        {result.suggested_followups?.length > 0 && <div className="assistant-chips" aria-label="Follow-up questions based on these figures">{result.suggested_followups.map((f) => <button type="button" key={f} disabled={loading} onClick={() => ask(f)}>{f}</button>)}</div>}
      </section>}
    </>}
  </>;
}
