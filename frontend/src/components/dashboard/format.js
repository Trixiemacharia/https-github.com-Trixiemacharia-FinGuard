const NUMBER = new Intl.NumberFormat('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function ksh(value) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  return `${n < 0 ? '−' : ''}KSh ${NUMBER.format(Math.abs(n))}`;
}
export function kshShort(value) {
  const n = Number(value); const abs = Math.abs(n);
  const text = abs >= 1e6 ? `${(abs / 1e6).toFixed(1)}M` : abs >= 1e3 ? `${(abs / 1e3).toFixed(abs >= 1e4 ? 0 : 1)}K` : abs.toFixed(0);
  return `${n < 0 ? '−' : ''}KSh ${text}`;
}
export function pct(value, digits = 1) {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}%`;
}
export function day(value, opts = { day: 'numeric', month: 'short', year: 'numeric' }) {
  if (!value) return '—';
  const [y, m, d] = String(value).slice(0, 10).split('-').map(Number);
  return new Intl.DateTimeFormat('en-KE', opts).format(new Date(y, m - 1, d));
}
export function monthLabel(value) {
  const [y, m] = String(value).split('-').map(Number);
  return new Intl.DateTimeFormat('en-KE', { month: 'long', year: 'numeric' }).format(new Date(y, m - 1, 1));
}
export const CATEGORY_LABELS = {
  groceries: 'Groceries', transport: 'Transport', utilities: 'Utilities', housing: 'Housing', health: 'Health',
  education: 'Education', shopping: 'Shopping', dining: 'Dining', transfers: 'Transfers', other: 'Other',
};
export const categoryLabel = (key) => CATEGORY_LABELS[key] || key;
export const CATEGORY_KEYS = Object.keys(CATEGORY_LABELS);
export const CATEGORY_COLORS = {
  housing: '#102D40', groceries: '#239B78', transport: '#3A7CA5', utilities: '#E39A53', dining: '#B5654A',
  shopping: '#7A6FB0', health: '#4FA3A5', education: '#5B8E5B', transfers: '#A7B4BC', other: '#C9D2D8',
};
export const PERIOD_OPTIONS = [
  ['last_7_days', 'Last 7 days'], ['last_30_days', 'Last 30 days'], ['last_3_months', 'Last 3 months'],
  ['last_6_months', 'Last 6 months'], ['this_year', 'This year'], ['custom', 'Custom range'],
];
