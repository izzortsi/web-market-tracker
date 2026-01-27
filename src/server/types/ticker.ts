export interface TickerEvent {
  e: string; // Event type
  E: number; // Event time
  s: string; // Symbol
  p: string; // Price change
  P: string; // Price change percent
  w: string; // Weighted avg price
  c: string; // Last price
  Q: string; // Last quantity
  o: string; // Open price
  h: string; // High price
  l: string; // Low price
  v: string; // Total traded base asset volume
  q: string; // Total traded quote asset volume
}

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
