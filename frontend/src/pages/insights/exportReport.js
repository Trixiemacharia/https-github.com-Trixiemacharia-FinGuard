import { categoryLabel, day, ksh, monthLabel, pct } from '../../components/dashboard/format.js';

const csvCell = (value) => {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};
const csvRow = (cells) => cells.map(csvCell).join(',');

/** CSV rows use the exact backend figures (2 decimal places) that the dashboard displays. */
export function buildCsv(data) {
  const p = data.period; const k = data.kpis; const c = data.comparison;
  const rows = [
    ['FinGuard financial report'], ['Period', p.from, p.to], ['Compared with', p.previous_from, p.previous_to],
    ['Currency', 'KES'], ['Generated', data.generated_at], [],
    ['Metric', 'This period', 'Previous period', 'Change %'],
    ['Total income', k.income, c.income.previous, c.income.change_percent ?? ''],
    ['Total expenses', k.expenses, c.expenses.previous, c.expenses.change_percent ?? ''],
    ['Net cash flow', k.net_cash_flow, c.net_cash_flow.previous, c.net_cash_flow.change_percent ?? ''],
    ['Completed transactions', k.transactions, c.transactions.previous, c.transactions.change_percent ?? ''], [],
    ['Month', 'From', 'To', 'Total income', 'Total expenses', 'Net cash flow', 'Transactions', 'Partial month'],
    ...data.monthly_reports.map((m) => [m.month, m.from, m.to, m.income, m.expenses, m.net_cash_flow, m.transactions, m.partial ? 'yes' : 'no']), [],
    ['Category', 'Amount', 'Share %', 'Previous period', 'Change %'],
    ...data.categories.map((cat) => [categoryLabel(cat.category), cat.amount, cat.share_percent, cat.previous_amount, cat.change_percent ?? '']),
  ];
  return rows.map(csvRow).join('\n');
}

export function downloadCsv(data) {
  const blob = new Blob([buildCsv(data)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement('a'), { href: url, download: `finguard-report-${data.period.from}-to-${data.period.to}.csv` });
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

/** Opens a print-ready report; the browser's "Save as PDF" produces the PDF. */
export function printReport(data) {
  const win = window.open('', '_blank', 'width=900,height=1000');
  if (!win) return false;
  const k = data.kpis; const c = data.comparison;
  const kpi = (label, key, value) => `<tr><td>${label}</td><td class="n">${esc(value)}</td><td class="n">${esc(key === 'transactions' ? c[key].previous : ksh(c[key].previous))}</td><td class="n">${esc(pct(c[key].change_percent))}</td></tr>`;
  win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>FinGuard report ${esc(data.period.from)} to ${esc(data.period.to)}</title>
<style>body{font-family:Arial,sans-serif;color:#1D2B36;margin:32px;font-size:12px}h1{color:#102D40;font-size:20px;margin:0 0 4px}h2{font-size:14px;color:#102D40;margin:24px 0 8px}
p{color:#82929D;margin:0 0 4px}table{width:100%;border-collapse:collapse}th,td{padding:7px 8px;border-bottom:1px solid #E5EBEF;text-align:left}th{background:#F4F7F9;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.n{text-align:right;font-variant-numeric:tabular-nums}.neg{color:#D95D5D}.pos{color:#239B78}@media print{body{margin:12mm}}</style></head><body>
<h1>FinGuard financial report</h1><p>${esc(day(data.period.from))} – ${esc(day(data.period.to))} · compared with ${esc(day(data.period.previous_from))} – ${esc(day(data.period.previous_to))}</p>
<p>Completed wallet transactions only, grouped in ${esc(data.period.timezone)} time. Generated ${esc(new Date(data.generated_at).toLocaleString('en-KE'))}.</p>
<h2>Summary</h2><table><thead><tr><th>Metric</th><th class="n">This period</th><th class="n">Previous period</th><th class="n">Change</th></tr></thead><tbody>
${kpi('Total income', 'income', ksh(k.income))}${kpi('Total expenses', 'expenses', ksh(k.expenses))}${kpi('Net cash flow', 'net_cash_flow', ksh(k.net_cash_flow))}${kpi('Completed transactions', 'transactions', k.transactions)}</tbody></table>
<h2>Monthly reports</h2><table><thead><tr><th>Month</th><th class="n">Total income</th><th class="n">Total expenses</th><th class="n">Net cash flow</th><th class="n">Transactions</th></tr></thead><tbody>
${data.monthly_reports.map((m) => `<tr><td>${esc(monthLabel(m.month))}${m.partial ? ` (${esc(day(m.from, { day: 'numeric', month: 'short' }))}–${esc(day(m.to, { day: 'numeric', month: 'short' }))})` : ''}</td><td class="n">${esc(ksh(m.income))}</td><td class="n">${esc(ksh(m.expenses))}</td><td class="n ${Number(m.net_cash_flow) < 0 ? 'neg' : 'pos'}">${esc(ksh(m.net_cash_flow))}</td><td class="n">${esc(m.transactions)}</td></tr>`).join('')}</tbody></table>
<h2>Spending by category</h2>${data.categories.length ? `<table><thead><tr><th>Category</th><th class="n">Amount</th><th class="n">Share</th><th class="n">Previous period</th></tr></thead><tbody>
${data.categories.map((cat) => `<tr><td>${esc(categoryLabel(cat.category))}</td><td class="n">${esc(ksh(cat.amount))}</td><td class="n">${esc(Number(cat.share_percent).toFixed(1))}%</td><td class="n">${esc(ksh(cat.previous_amount))}</td></tr>`).join('')}</tbody></table>` : '<p>No completed spending in this period.</p>'}
<script>window.onload=function(){window.focus();window.print();}</script></body></html>`);
  win.document.close();
  return true;
}
