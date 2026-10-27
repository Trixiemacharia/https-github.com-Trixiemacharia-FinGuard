export function formatMoney(amount, currency = 'KES') {
  if (amount === undefined || amount === null) return '—';
  try { return new Intl.NumberFormat('en-KE', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(amount)); }
  catch { return `${currency} ${amount}`; }
}
export function formatWhen(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-KE', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
