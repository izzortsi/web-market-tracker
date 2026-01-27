import { RingBuffer } from './ringBuffer.js';
import { OHLC, SymbolSnapshot, MarketSummaryPayload, TickerEvent, MarketSeriesPoint } from '../types/ticker.js';

type SymbolState = {
  buffer: RingBuffer<TickerEvent>;
  lastPrice?: number;
  prevSpeed?: number;
  lastSpeed?: number;
  lastAccel?: number;
  lastTimestamp?: number;
  capRank: number;
};

type CapWeights = Record<string, number>;

const RING_SIZE = 500;
const MAX_SERIES_POINTS = 300; // keep ~5 minutes at 1s cadence

export class MarketStore {
  private symbols: Map<string, SymbolState> = new Map();
  private momentumSeries: MarketSeriesPoint[] = [];
  private accelSeries: MarketSeriesPoint[] = [];
  private capWeights: CapWeights;

  constructor(capWeights: CapWeights) {
    this.capWeights = capWeights;
  }

  ingest(events: TickerEvent[]): void {
    for (const ev of events) {
      const sym = ev.s;
      const state = this.symbols.get(sym) ?? {
        buffer: new RingBuffer<TickerEvent>(RING_SIZE),
        capRank: this.capWeights[sym] ?? 999
      };
      state.buffer.push(ev);

      const price = parseFloat(ev.c);
      const ts = ev.E;
      if (!Number.isFinite(price)) {
        this.symbols.set(sym, state);
        continue;
      }

      if (state.lastPrice !== undefined && state.lastTimestamp !== undefined) {
        const dtSec = Math.max((ts - state.lastTimestamp) / 1000, 1e-3);
        const speed = (price - state.lastPrice) / dtSec;
        let accel: number | undefined;
        if (state.lastSpeed !== undefined) {
          accel = (speed - state.lastSpeed) / dtSec;
        }
        state.prevSpeed = state.lastSpeed;
        state.lastSpeed = speed;
        if (accel !== undefined) {
          state.lastAccel = accel;
        }
      } else {
        state.lastSpeed = undefined;
        state.prevSpeed = undefined;
        state.lastAccel = undefined;
      }

      state.lastPrice = price;
      state.lastTimestamp = ts;

      this.symbols.set(sym, state);
    }
  }

  computeSnapshot(now: number): MarketSummaryPayload {
    const symbolSnapshots: SymbolSnapshot[] = [];

    let minHl = Number.POSITIVE_INFINITY;
    let maxHl = Number.NEGATIVE_INFINITY;

    // First pass compute hl diff bounds
    for (const [, state] of this.symbols.entries()) {
      const vals = state.buffer.values();
      if (vals.length === 0) continue;
      const latest = vals[vals.length - 1];
      const high = parseFloat(latest.h);
      const low = parseFloat(latest.l);
      if (low > 0 && Number.isFinite(high) && Number.isFinite(low)) {
        const hlDiff = Math.abs((high - low) / low);
        if (hlDiff < minHl) minHl = hlDiff;
        if (hlDiff > maxHl) maxHl = hlDiff;
      }
    }

    const range = maxHl - minHl || 1;

    for (const [sym, state] of this.symbols.entries()) {
      const vals = state.buffer.values();
      if (vals.length === 0) continue;
      const latest = vals[vals.length - 1];
      const lastPrice = parseFloat(latest.c);
      const open = parseFloat(latest.o);
      const high = parseFloat(latest.h);
      const low = parseFloat(latest.l);

      if (!Number.isFinite(lastPrice) || !Number.isFinite(open) || !Number.isFinite(high) || !Number.isFinite(low) || low <= 0) {
        continue;
      }

      const change24hPct = ((lastPrice - open) / open) * 100;
      const hlDiffAbs = Math.abs((high - low) / low);
      const normalizedHl = (hlDiffAbs - minHl) / range;

      const capRank = state.capRank;
      const weight = 1 / Math.max(1, capRank); // higher rank => lower weight number
      const score = weight + normalizedHl;

      const ohlc = buildOhlc(vals, 60_000, now);

      symbolSnapshots.push({
        sym,
        last: lastPrice,
        change24hPct,
        hlDiffAbs,
        score,
        capRank,
        ohlc
      });
    }

    symbolSnapshots.sort((a, b) => b.score - a.score);
    const top5 = symbolSnapshots.slice(0, 5);

    const aggMomentum = this.computeAggregateMomentum();
    const aggAccel = this.computeAggregateAcceleration();

    this.momentumSeries.push({ t: now, v: aggMomentum });
    this.accelSeries.push({ t: now, v: aggAccel });
    this.trimSeries();

    return {
      ts: now,
      top: top5,
      market: {
        momentum: [...this.momentumSeries],
        acceleration: [...this.accelSeries]
      }
    };
  }

  private trimSeries(): void {
    if (this.momentumSeries.length > MAX_SERIES_POINTS) {
      this.momentumSeries = this.momentumSeries.slice(-MAX_SERIES_POINTS);
    }
    if (this.accelSeries.length > MAX_SERIES_POINTS) {
      this.accelSeries = this.accelSeries.slice(-MAX_SERIES_POINTS);
    }
  }

  private computeAggregateMomentum(): number {
    let total = 0;
    for (const [, state] of this.symbols.entries()) {
      if (state.lastSpeed !== undefined) {
        const mass = 1 / Math.max(1, state.capRank);
        total += mass * state.lastSpeed;
      }
    }
    return total;
  }

  private computeAggregateAcceleration(): number {
    let total = 0;
    let count = 0;
    for (const [, state] of this.symbols.entries()) {
      if (state.lastAccel !== undefined) {
        total += state.lastAccel;
        count += 1;
      }
    }
    if (count === 0) return 0;
    return total / count;
  }
}

function buildOhlc(events: TickerEvent[], windowMs: number, now: number): OHLC[] {
  const cutoff = now - windowMs * 5; // 5 bars window
  const buckets: Record<number, TickerEvent[]> = {};
  for (const ev of events) {
    if (ev.E < cutoff) continue;
    const bucket = Math.floor(ev.E / windowMs);
    (buckets[bucket] ||= []).push(ev);
  }
  const result: OHLC[] = [];
  const sortedBuckets = Object.keys(buckets).map(Number).sort((a, b) => a - b);
  for (const b of sortedBuckets) {
    const list = buckets[b];
    list.sort((a, b2) => a.E - b2.E);
    const o = parseFloat(list[0].c);
    const c = parseFloat(list[list.length - 1].c);
    let h = Number.NEGATIVE_INFINITY;
    let l = Number.POSITIVE_INFINITY;
    for (const ev of list) {
      const p = parseFloat(ev.c);
      if (p > h) h = p;
      if (p < l) l = p;
    }
    if (Number.isFinite(o) && Number.isFinite(c) && Number.isFinite(h) && Number.isFinite(l)) {
      result.push({ t: b * windowMs, o, h, l, c });
    }
  }
  return result.slice(-5);
}
