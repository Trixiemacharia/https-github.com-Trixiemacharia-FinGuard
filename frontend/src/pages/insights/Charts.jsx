import { useMemo } from 'react';
import { useChart } from '../../hooks/useChart.js';
import { CATEGORY_COLORS, categoryLabel, day, ksh, kshShort } from '../../components/dashboard/format.js';

const TEAL = '#239B78'; const WARM = '#E39A53'; const NAVY = '#102D40'; const RED = '#D95D5D';
const GRID = '#E5EBEF'; const MUTED = '#82929D';
const FONT = { family: "'DM Sans', sans-serif", size: 11 };

function bucketLabel(bucket, granularity) {
  if (granularity === 'day') return day(bucket.start, { day: 'numeric', month: 'short' });
  if (granularity === 'month') return day(bucket.start, { month: 'short', year: 'numeric' });
  return bucket.start === bucket.end ? day(bucket.start, { day: 'numeric', month: 'short' })
    : `${day(bucket.start, { day: 'numeric', month: 'short' })} – ${day(bucket.end, { day: 'numeric', month: 'short' })}`;
}

const AXIS_TITLES = { day: 'Day', week: 'Week', month: 'Month' };

function baseOptions(granularity) {
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'bottom', align: 'start', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, color: MUTED, font: FONT } },
      tooltip: { backgroundColor: NAVY, padding: 10, titleFont: { ...FONT, weight: '600' }, bodyFont: FONT,
        callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ksh(ctx.parsed.y)}` } },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: MUTED, font: FONT, maxRotation: 0, autoSkipPadding: 12 },
        title: { display: true, text: AXIS_TITLES[granularity], color: MUTED, font: FONT } },
      y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED, font: FONT, callback: (v) => kshShort(v) },
        title: { display: true, text: 'Amount (KSh)', color: MUTED, font: FONT } },
    },
  };
}

export function IncomeExpenseChart({ series, granularity }) {
  const data = useMemo(() => ({
    labels: series.map((b) => bucketLabel(b, granularity)),
    datasets: [
      { label: 'Income', data: series.map((b) => Number(b.income)), backgroundColor: TEAL, borderRadius: 4, maxBarThickness: 28 },
      { label: 'Expenses', data: series.map((b) => Number(b.expenses)), backgroundColor: WARM, borderRadius: 4, maxBarThickness: 28 },
    ],
  }), [series, granularity]);
  const options = useMemo(() => baseOptions(granularity), [granularity]);
  const ref = useChart('bar', data, options);
  return <div className="ins-chart"><canvas ref={ref} role="img" aria-label="Income and expenses by period" /></div>;
}

export function NetFlowChart({ series, granularity }) {
  const data = useMemo(() => ({
    labels: series.map((b) => bucketLabel(b, granularity)),
    datasets: [{
      label: 'Net cash flow', data: series.map((b) => Number(b.net)), borderColor: NAVY, borderWidth: 2, tension: 0.25,
      pointRadius: series.length > 40 ? 0 : 3, pointHoverRadius: 5,
      pointBackgroundColor: series.map((b) => (Number(b.net) < 0 ? RED : TEAL)),
      segment: { borderColor: (ctx) => (ctx.p0.parsed.y < 0 || ctx.p1.parsed.y < 0 ? RED : NAVY) },
      fill: { target: 'origin', above: 'rgba(35,155,120,.08)', below: 'rgba(217,93,93,.08)' },
    }],
  }), [series, granularity]);
  const options = useMemo(() => {
    const opts = baseOptions(granularity);
    opts.plugins.legend.display = false;
    opts.scales.y.grid.color = (ctx) => (ctx.tick.value === 0 ? '#B8C4CB' : GRID);
    return opts;
  }, [granularity]);
  const ref = useChart('line', data, options);
  return <div className="ins-chart"><canvas ref={ref} role="img" aria-label="Net cash flow trend" /></div>;
}

export function CategoryDoughnut({ categories, selected, onSelect }) {
  const data = useMemo(() => ({
    labels: categories.map((c) => categoryLabel(c.category)),
    datasets: [{
      data: categories.map((c) => Number(c.amount)),
      backgroundColor: categories.map((c) => CATEGORY_COLORS[c.category] || '#C9D2D8'),
      borderColor: '#fff', borderWidth: 2,
      offset: categories.map((c) => (c.category === selected ? 10 : 0)),
    }],
  }), [categories, selected]);
  const options = useMemo(() => ({
    responsive: true, maintainAspectRatio: false, cutout: '68%', animation: { duration: 250 },
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: NAVY, padding: 10, bodyFont: FONT,
        callbacks: { label: (ctx) => ` ${ctx.label}: ${ksh(ctx.parsed)} (${Number(categories[ctx.dataIndex].share_percent).toFixed(1)}%)` } },
    },
    onClick: (_event, elements) => { if (elements.length) onSelect(categories[elements[0].index].category); },
  }), [categories, onSelect]);
  const ref = useChart('doughnut', data, options);
  return <div className="ins-chart ins-chart-doughnut"><canvas ref={ref} role="img" aria-label="Spending distribution by category" /></div>;
}
