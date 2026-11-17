// Deterministic savings calculations shared by the Savings page. Money is handled in integer cents.
import { Briefcase, Car, GraduationCap, Heart, Home, PiggyBank, Plane, ShieldCheck, Smartphone } from 'lucide-react';

export const LOCAL_TZ = 'Africa/Nairobi';
export const localToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: LOCAL_TZ }).format(new Date());

export const toCents = (value) => Math.round(Number(value || 0) * 100);
export const fromCents = (cents) => (cents / 100).toFixed(2);
export const AMOUNT_PATTERN = /^\d{1,12}(\.\d{1,2})?$/;

/** Returns an error message, or null when the amount is a valid positive KSh amount with at most 2 decimals. */
export function amountError(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return 'Enter an amount.';
  if (!AMOUNT_PATTERN.test(value)) return 'Use a number with at most 2 decimal places.';
  if (toCents(value) <= 0) return 'The amount must be greater than zero.';
  return null;
}

export function daysUntil(dateString, today = localToday()) {
  if (!dateString) return null;
  const [a, b] = [dateString, today].map((d) => Date.UTC(...d.slice(0, 10).split('-').map((n, i) => Number(n) - (i === 1 ? 1 : 0))));
  return Math.round((a - b) / 86400000);
}

/** Contributions needed to close `remainingCents` by `targetDate`. Null when there is no future date. */
export function requiredContribution(remainingCents, targetDate, today = localToday()) {
  const days = daysUntil(targetDate, today);
  if (days === null || days <= 0 || remainingCents <= 0) return days === null ? null : { days, daily: 0, weekly: 0, monthly: 0, done: remainingCents <= 0 };
  const per = (periods) => Math.ceil(remainingCents / Math.max(1, periods));
  return { days, daily: per(days), weekly: per(days / 7), monthly: per(days / (365.25 / 12)), done: false };
}

/** Monthly-equivalent cents of a goal's authorized automatic rules (weekly x 52 / 12). Drafts and paused rules count as 0. */
export function scheduledMonthlyCents(rules, goalId) {
  return rules.filter((r) => String(r.goal) === String(goalId) && r.status === 'authorized')
    .reduce((sum, r) => sum + (r.cadence === 'weekly' ? Math.round(toCents(r.amount) * 52 / 12) : toCents(r.amount)), 0);
}

export const MILESTONES = [25, 50, 75, 100];

export function milestones(saved, target) {
  const savedCents = toCents(saved); const targetCents = toCents(target);
  return MILESTONES.map((pct) => {
    const amount = Math.ceil(targetCents * pct / 100);
    return { pct, amount, reached: targetCents > 0 && savedCents >= amount };
  });
}

/** Date each milestone was first reached, replaying completed movements oldest first. */
export function milestoneDates(history, target) {
  const targetCents = toCents(target);
  const sorted = [...history].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  const reached = {}; let balance = 0;
  for (const item of sorted) {
    balance += (item.direction === 'withdrawal' ? -1 : 1) * toCents(item.amount);
    for (const pct of MILESTONES) if (!reached[pct] && balance >= Math.ceil(targetCents * pct / 100)) reached[pct] = item.created_at;
  }
  return reached;
}

export const GOAL_STATUS = {
  completed: ['Completed', 'good'], on_track: ['On track', 'good'], behind: ['Needs attention', 'warn'],
  overdue: ['Target date passed', 'bad'], in_progress: ['In progress', 'info'], archived: ['Archived', 'neutral'],
};

/**
 * completed: saved >= target. overdue: target date passed. on_track / behind: authorized rules' monthly amount
 * compared with the monthly contribution needed to hit the target date. in_progress: no target date.
 */
export function goalStatus(goal, rules, today = localToday()) {
  if (goal.archived_at) return 'archived';
  if (toCents(goal.saved_amount) >= toCents(goal.target_amount)) return 'completed';
  if (!goal.target_date) return 'in_progress';
  const need = requiredContribution(toCents(goal.remaining_amount), goal.target_date, today);
  if (!need || need.days <= 0) return 'overdue';
  return scheduledMonthlyCents(rules, goal.id) >= need.monthly ? 'on_track' : 'behind';
}

const ICONS = [
  [/emergenc|rainy|safety|buffer/i, ShieldCheck], [/trip|travel|holiday|vacation|safari|flight/i, Plane],
  [/car|vehicle|motorbike|boda/i, Car], [/house|home|rent|deposit|land|plot/i, Home],
  [/school|fees|tuition|education|college|university/i, GraduationCap], [/wedding|gift|family|baby/i, Heart],
  [/phone|laptop|computer|tv|gadget/i, Smartphone], [/business|stock|shop|capital/i, Briefcase],
];
export const goalIcon = (name) => (ICONS.find(([pattern]) => pattern.test(name || '')) || [null, PiggyBank])[1];

export const newIdempotencyKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
