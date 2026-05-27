'use client';
import dynamic from 'next/dynamic';
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false });

export function PlotlyChart({ figure, height = 280 }: { figure: any; height?: number }) {
  if (!figure) return null;
  return (
    <Plot
      data={figure.data}
      layout={{
        ...figure.layout,
        autosize: true,
        margin: { l: 44, r: 14, t: 8, b: 36, ...(figure.layout?.margin ?? {}) },
        paper_bgcolor: 'white',
        plot_bgcolor: 'white',
        font: { family: 'Inter, sans-serif', size: 11, color: '#1C1917' },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%', height }}
      useResizeHandler
    />
  );
}
