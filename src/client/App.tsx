import { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import type { MarketSummaryPayload, SymbolSnapshot, OHLC } from '../server/types/ticker.js';
import './styles.css';

const API_URL = '/api/market/summary';

export default function App() {
  const [data, setData] = useState<MarketSummaryPayload | null>(null);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(API_URL);
        if (!res.ok) return;
        const json = await res.json();
        setData(json);
      } catch (err) {
        console.error(err);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="page">
      <header className="header">
        <h1>Market Tracker</h1>
      </header>
      <section className="metrics">
        <MetricChart
          title="Aggregate Momentum"
          series={data?.market.momentum ?? []}
          color="#00c896"
        />
        <MetricChart
          title="Aggregate Acceleration"
          series={data?.market.acceleration ?? []}
          color="#ff6b6b"
        />
      </section>
      <section className="cards">
        {(data?.top ?? []).map((sym: SymbolSnapshot) => (
          <SymbolCard key={sym.sym} sym={sym} />
        ))}
      </section>
    </div>
  );
}

function MetricChart({
  title,
  series,
  color
}: {
  title: string;
  series: { t: number; v: number }[];
  color: string;
}) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <Plot
        data={[
          {
            x: series.map((p) => new Date(p.t)),
            y: series.map((p) => p.v),
            type: 'scatter',
            mode: 'lines',
            line: { color }
          }
        ]}
        layout={{
          margin: { l: 40, r: 10, t: 20, b: 30 },
          autosize: true,
          height: 200
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}

function SymbolCard({ sym }: { sym: SymbolSnapshot }) {
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="sym">{sym.sym}</div>
          <div className="meta">Cap rank: {sym.capRank}</div>
        </div>
        <div className="price">${sym.last.toFixed(4)}</div>
      </div>
      <div className="stats">
        <span className={sym.change24hPct >= 0 ? 'pos' : 'neg'}>
          24h: {sym.change24hPct.toFixed(2)}%
        </span>
        <span>|HL|: {(sym.hlDiffAbs * 100).toFixed(2)}%</span>
        <span>Score: {sym.score.toFixed(3)}</span>
      </div>
      <Plot
        data={[
          {
            x: sym.ohlc.map((o: OHLC) => new Date(o.t)),
            close: sym.ohlc.map((o: OHLC) => o.c),
            open: sym.ohlc.map((o: OHLC) => o.o),
            high: sym.ohlc.map((o: OHLC) => o.h),
            low: sym.ohlc.map((o: OHLC) => o.l),
            type: 'candlestick',
            increasing: { line: { color: '#00c896' } },
            decreasing: { line: { color: '#ff6b6b' } }
          }
        ]}
        layout={{
          margin: { l: 30, r: 10, t: 10, b: 20 },
          autosize: true,
          height: 200,
          xaxis: { showgrid: false, zeroline: false, showticklabels: false },
          yaxis: { showgrid: true, zeroline: false }
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}
