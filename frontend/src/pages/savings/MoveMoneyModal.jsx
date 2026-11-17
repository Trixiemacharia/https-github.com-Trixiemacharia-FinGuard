import { useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, CheckCircle2, ShieldCheck } from 'lucide-react';
import { savingsApi } from '../../api/services.js';
import { Modal } from '../../components/dashboard/ui.jsx';
import { ksh } from '../../components/dashboard/format.js';
import { amountError, fromCents, newIdempotencyKey, toCents } from './logic.js';

/**
 * Contribute to / withdraw from a goal in three steps: details -> review -> result.
 * The server re-checks every rule (balances, frozen wallet, archived goal) inside one database transaction; the
 * checks here only give early feedback. One idempotency key per reviewed movement makes retries safe.
 */
export function MoveMoneyModal({ goals, wallet, initial = {}, onClose, onDone }) {
  const [direction, setDirection] = useState(initial.direction || 'contribution');
  const [goalId, setGoalId] = useState(initial.goalId || '');
  const [amount, setAmount] = useState('');
  const [step, setStep] = useState('form');
  const [touched, setTouched] = useState(false);
  const [key, setKey] = useState(null);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState('');
  const [result, setResult] = useState(null);

  const eligible = useMemo(() => goals.filter((g) => (direction === 'contribution' ? !g.archived_at : toCents(g.saved_amount) > 0)), [goals, direction]);
  const goal = eligible.find((g) => String(g.id) === String(goalId)) || null;
  const walletCents = toCents(wallet?.balance); const goalCents = toCents(goal?.saved_amount);
  const cents = amountError(amount) ? 0 : toCents(amount);

  // Validation always runs; `touched` only decides when to show the message.
  let validation = amountError(amount);
  if (!validation && goal) {
    if (direction === 'contribution' && cents > walletCents) validation = `That is more than your available wallet balance of ${ksh(wallet.balance)}.`;
    if (direction === 'withdrawal' && cents > goalCents) validation = `You can withdraw at most ${ksh(goal.saved_amount)} from this goal.`;
  }
  const error = touched ? validation : null;
  const blocked = wallet?.is_frozen ? 'Your wallet is frozen, so money cannot move in or out of savings.' : null;
  const canReview = Boolean(goal) && !validation && !blocked;

  function switchDirection(next) { setDirection(next); setGoalId(''); setAmount(''); setTouched(false); }
  function review(event) {
    event.preventDefault(); setTouched(true);
    if (!canReview) return;
    setKey(newIdempotencyKey()); setServerError(''); setStep('review');
  }
  async function confirm() {
    setBusy(true); setServerError('');
    try {
      const { data } = await savingsApi.move(goal.id, { amount: fromCents(cents), direction }, key);
      setResult(data); setStep('done'); onDone?.();
    } catch (e) {
      setServerError(e.message || 'The movement could not be completed.');
    } finally { setBusy(false); }
  }
  const contributing = direction === 'contribution';
  const after = { wallet: walletCents + (contributing ? -cents : cents), goal: goalCents + (contributing ? cents : -cents) };

  if (step === 'done') {
    return <Modal title="Movement complete" onClose={onClose} footer={<button className="ins-btn primary" onClick={onClose}>Done</button>}>
      <div className="sv-result"><CheckCircle2 size={28} />
        <strong>{ksh(result.amount)} {contributing ? `added to ${goal.name}` : `returned to your wallet from ${goal.name}`}</strong>
        <p>New wallet balance {ksh(fromCents(after.wallet))} · goal balance {ksh(fromCents(after.goal))}</p></div>
    </Modal>;
  }
  if (step === 'review') {
    return <Modal title="Review movement" subtitle="Nothing moves until you confirm." onClose={onClose} busy={busy}
      footer={<><button className="ins-btn ghost" disabled={busy} onClick={() => { setStep('form'); setServerError(''); }}>Back</button>
        <button className="ins-btn primary" disabled={busy} onClick={confirm}>{busy ? 'Processing…' : `Confirm ${contributing ? 'contribution' : 'withdrawal'}`}</button></>}>
      <dl className="sv-review">
        <div><dt>Type</dt><dd>{contributing ? 'Contribution: wallet → savings' : 'Withdrawal: savings → wallet'}</dd></div>
        <div><dt>Goal</dt><dd>{goal.name}</dd></div>
        <div className="amount"><dt>Amount</dt><dd>{ksh(fromCents(cents))}</dd></div>
      </dl>
      <table className="ins-table compact sv-balances"><thead><tr><th /><th className="n">Now</th><th className="n">After</th></tr></thead><tbody>
        <tr><td>Wallet balance</td><td className="n">{ksh(wallet.balance)}</td><td className={`n ${contributing ? 'neg' : 'pos'}`}>{ksh(fromCents(after.wallet))}</td></tr>
        <tr><td>{goal.name}</td><td className="n">{ksh(goal.saved_amount)}</td><td className={`n ${contributing ? 'pos' : 'neg'}`}>{ksh(fromCents(after.goal))}</td></tr>
      </tbody></table>
      {serverError && <p className="ins-error" role="alert">{serverError} No money was moved. You can retry safely.</p>}
      <p className="ins-rule"><ShieldCheck size={12} /> Balances are checked again on the server at the moment you confirm.</p>
    </Modal>;
  }
  return <Modal title="Move money" subtitle="Between your wallet and your savings goals" onClose={onClose}
    footer={<><button className="ins-btn ghost" onClick={onClose}>Cancel</button><button className="ins-btn primary" type="submit" form="sv-move-form" disabled={!!blocked || !eligible.length}>Review</button></>}>
    <form id="sv-move-form" className="sv-form" onSubmit={review} noValidate>
      <div className="sv-segment" role="radiogroup" aria-label="Movement type">
        <button type="button" role="radio" aria-checked={contributing} className={contributing ? 'on' : ''} onClick={() => switchDirection('contribution')}><ArrowUpRight size={14} /> Contribute</button>
        <button type="button" role="radio" aria-checked={!contributing} className={!contributing ? 'on' : ''} onClick={() => switchDirection('withdrawal')}><ArrowDownLeft size={14} /> Withdraw</button>
      </div>
      {blocked && <p className="ins-error">{blocked}</p>}
      {!eligible.length ? <p className="ins-muted">{contributing ? 'Create an active savings goal first.' : 'None of your goals has a balance to withdraw.'}</p> : <>
        <label>Savings goal<select required value={goalId} onChange={(e) => setGoalId(e.target.value)}>
          <option value="">Select a goal</option>
          {eligible.map((g) => <option key={g.id} value={g.id}>{g.name} · {ksh(g.saved_amount)} saved{g.archived_at ? ' (archived)' : ''}</option>)}
        </select></label>
        <label>Amount (KSh)<input inputMode="decimal" value={amount} placeholder="0.00" aria-invalid={!!error}
          onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} onBlur={() => setTouched(true)} /></label>
        {goal && <div className="sv-quick">
          {contributing ? <><span>Available in wallet {ksh(wallet.balance)}</span>{toCents(goal.remaining_amount) > 0 && toCents(goal.remaining_amount) <= walletCents && <button type="button" className="ins-btn ghost" onClick={() => { setAmount(goal.remaining_amount); setTouched(true); }}>Fill remaining {ksh(goal.remaining_amount)}</button>}</>
            : <><span>Saved in goal {ksh(goal.saved_amount)}</span><button type="button" className="ins-btn ghost" onClick={() => { setAmount(goal.saved_amount); setTouched(true); }}>Withdraw all</button></>}
        </div>}
        {error && <p className="ins-error" role="alert">{error}</p>}
        {touched && !goal && <p className="ins-error">Select a savings goal.</p>}
      </>}
    </form>
  </Modal>;
}
