export interface OHLC {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
}

export interface SymbolSnapshot {
  sym: string;
  last: number;
  change24hPct: number;
  hlDiffAbs: number;
  score: number;
  capRank: number;
  accel?: number;
  ohlc: OHLC[];
}

export interface MarketSeriesPoint {
  t: number;
  v: number;
}

export interface MarketSummaryPayload {
  ts: number;
  top: SymbolSnapshot[];
  market: {
    momentum: MarketSeriesPoint[];
    acceleration: MarketSeriesPoint[];
  };
}
