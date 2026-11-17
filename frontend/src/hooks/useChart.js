import { useEffect, useRef } from 'react';
import {
  ArcElement, BarController, BarElement, CategoryScale, Chart, DoughnutController, Filler, Legend,
  LinearScale, LineController, LineElement, PointElement, Tooltip,
} from 'chart.js';

Chart.register(ArcElement, BarController, BarElement, CategoryScale, DoughnutController, Filler, Legend,
  LinearScale, LineController, LineElement, PointElement, Tooltip);

/** One Chart.js instance per canvas: created once, updated in place, destroyed on unmount. */
export function useChart(type, data, options) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);
  useEffect(() => {
    if (!canvasRef.current) return undefined;
    chartRef.current = new Chart(canvasRef.current, { type, data, options });
    return () => { chartRef.current?.destroy(); chartRef.current = null; };
    // Recreate only when the chart type changes; data/options updates are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.data = data;
    chart.options = options;
    chart.update();
  }, [data, options]);
  return canvasRef;
}
