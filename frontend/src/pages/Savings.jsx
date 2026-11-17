import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeftRight, Plus, RefreshCw } from 'lucide-react';
import { savingsApi, walletApi } from '../api/services.js';
import { PageTitle } from '../components/Feedback.jsx';
import { ConfirmDialog, DashboardSkeleton, Feedback, Panel } from '../components/dashboard/ui.jsx';
import { day, ksh } from '../components/dashboard/format.js';
import { ActivitySection } from './savings/Activity.jsx';
import { GoalDetail, GoalFormModal, GoalGrid, SavingsOverview } from './savings/Goals.jsx';
import { MoveMoneyModal } from './savings/MoveMoneyModal.jsx';
import { FinancialPlanning, SavingsCalculator } from './savings/Planning.jsx';
import { RuleFormModal, RulesSection } from './savings/Rules.jsx';
import '../components/dashboard/dashboard.css';
import './savings/savings.css';

const rowsOf = (data) => data?.results || data || [];

export function Savings() {
  const [goals, setGoals] = useState([]); const [rules, setRules] = useState([]); const [wallet, setWallet] = useState(null);
  const [loading, setLoading] = useState(true); const [refreshing, setRefreshing] = useState(false); const [loadError, setLoadError] = useState('');
  const [feedback, setFeedback] = useState(null);
  const [modal, setModal] = useState(null); // { type: 'move'|'goal'|'detail'|'rule'|'archive', ... }
  const [showArchived, setShowArchived] = useState(false);
  const [activityKey, setActivityKey] = useState(0);
  const [archiving, setArchiving] = useState(false);
  const request = useRef(0);

  const load = useCallback(async ({ quiet = false } = {}) => {
    const id = ++request.current;
    if (quiet) setRefreshing(true); else setLoading(true);
    try {
      const [g, r, w] = await Promise.all([savingsApi.goals(), savingsApi.schedules(), walletApi.get()]);
      if (id !== request.current) return;
      setGoals(rowsOf(g.data)); setRules(rowsOf(r.data)); setWallet(w.data); setLoadError('');
    } catch (e) { if (id === request.current) setLoadError(e.message); }
    finally { if (id === request.current) { setLoading(false); setRefreshing(false); } }
  }, []);
  useEffect(() => { load(); }, [load]);

  const notify = useCallback((type, text) => setFeedback({ type, text, at: Date.now() }), []);
  const dismiss = useCallback(() => setFeedback(null), []);
  const reload = useCallback(async () => { await load({ quiet: true }); setActivityKey((k) => k + 1); }, [load]);
  const close = () => setModal(null);
  // Keep an open detail view in sync with refreshed data.
  const liveGoal = (goal) => goals.find((g) => g.id === goal?.id) || goal;

  const handlers = {
    onView: (goal) => setModal({ type: 'detail', goal }),
    onEdit: (goal) => setModal({ type: 'goal', goal }),
    onArchive: (goal) => setModal({ type: 'archive', goal }),
    onMove: (goal, direction) => setModal({ type: 'move', initial: { goalId: goal.id, direction } }),
  };
  async function archive(goal) {
    setArchiving(true);
    try { await savingsApi.archiveGoal(goal.id); notify('success', `${goal.name} archived. Its ${ksh(goal.saved_amount)} stays saved and can still be withdrawn.`); close(); await reload(); }
    catch (e) { notify('error', e.message); close(); } finally { setArchiving(false); }
  }
  const activeRulesFor = (goal) => rules.filter((r) => String(r.goal) === String(goal.id) && r.status === 'authorized').length;

  return <div className="ins sv">
    <PageTitle eyebrow="SAVINGS" title="Your Savings" detail="Build towards your financial goals with clarity and control."
      action={<span className="ins-actions sv-header-actions">
        <button className="ins-btn" onClick={reload} disabled={loading || refreshing}><RefreshCw size={14} className={refreshing ? 'ins-spin' : ''} /> Refresh</button>
        <button className="ins-btn" onClick={() => setModal({ type: 'goal' })} disabled={loading}><Plus size={14} /> New goal</button>
        <button className="ins-btn primary" onClick={() => setModal({ type: 'move', initial: {} })} disabled={loading || !wallet}><ArrowLeftRight size={14} /> Move money</button>
      </span>} />
    <Feedback feedback={feedback} onDismiss={dismiss} />
    {loadError && <div className="ins-banner" role="alert"><span>{loadError}</span><button className="ins-btn" onClick={() => load()}>Try again</button></div>}
    {loading && !wallet ? <DashboardSkeleton /> : wallet && <div className={refreshing ? 'ins-dim' : ''}>
      <SavingsOverview goals={goals} wallet={wallet} />
      <Panel title="Savings goals" subtitle="Ordered by your priority. Select a goal to see its history, milestones and automatic savings."
        action={goals.length > 0 && <button className="ins-btn" onClick={() => setModal({ type: 'goal' })}><Plus size={14} /> New goal</button>}>
        <GoalGrid goals={goals} rules={rules} showArchived={showArchived} onToggleArchived={() => setShowArchived((s) => !s)} onCreate={() => setModal({ type: 'goal' })} {...handlers} />
      </Panel>
      <RulesSection rules={rules} goals={goals} notify={notify} onChanged={reload}
        onCreate={() => setModal({ type: 'rule' })} onEdit={(rule) => setModal({ type: 'rule', rule })} />
      <ActivitySection refreshKey={activityKey} />
      <FinancialPlanning goals={goals} rules={rules} notify={notify} onChanged={reload} onCreateGoal={(prefill) => setModal({ type: 'goal', prefill })} />
      <SavingsCalculator goals={goals} />
    </div>}

    {modal?.type === 'move' && <MoveMoneyModal goals={goals} wallet={wallet} initial={modal.initial} onClose={close} onDone={reload} />}
    {modal?.type === 'goal' && <GoalFormModal goal={modal.goal} prefill={modal.prefill} onClose={close}
      onSaved={(goal, edited) => { notify('success', edited ? `${goal.name} updated.` : `${goal.name} created.`); close(); reload(); }} />}
    {modal?.type === 'detail' && <GoalDetail goal={liveGoal(modal.goal)} rules={rules} onClose={close} {...handlers}
      onManageRules={(goal) => setModal({ type: 'rule', presetGoal: goal })} />}
    {modal?.type === 'rule' && <RuleFormModal rule={modal.rule} presetGoal={modal.presetGoal} goals={goals} onClose={close}
      onSaved={(rule, edited) => { notify('success', rule.status === 'authorized' ? `Rule ${edited ? 'updated and ' : ''}authorized. Next run ${day(rule.next_run_date)}.` : `Draft rule ${edited ? 'updated' : 'saved'}. It will not move money until you authorize it.`); close(); reload(); }} />}
    {modal?.type === 'archive' && <ConfirmDialog title={`Archive ${modal.goal.name}?`} confirmLabel="Archive goal" tone="danger" busy={archiving}
      message={<>The goal stops accepting contributions{activeRulesFor(modal.goal) ? ` and its ${activeRulesFor(modal.goal)} active automatic rule${activeRulesFor(modal.goal) === 1 ? ' is' : 's are'} paused` : ''}. The {ksh(modal.goal.saved_amount)} already saved stays recorded and can still be withdrawn to your wallet.</>}
      onConfirm={() => archive(modal.goal)} onCancel={close} />}
  </div>;
}
