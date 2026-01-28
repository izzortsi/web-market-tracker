from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from .ring_buffer import RingBuffer
from ..config import RING_SIZE, MAX_SERIES_POINTS, CANDLE_WINDOW_MS, CANDLE_COUNT


@dataclass
class SymbolState:
    buffer: RingBuffer[dict]
    last_price: Optional[float] = None
    prev_speed: Optional[float] = None
    last_speed: Optional[float] = None
    last_accel: Optional[float] = None
    last_timestamp: Optional[int] = None
    cap_rank: int = 999


class MarketStore:
    def __init__(self, cap_weights: Dict[str, int]) -> None:
        self.symbols: Dict[str, SymbolState] = {}
        self.momentum_series: List[dict] = []
        self.accel_series: List[dict] = []
        self.cap_weights = cap_weights

    def ingest(self, events: List[dict]) -> None:
        for ev in events:
            sym = ev.get("s")
            if not sym:
                continue
            state = self.symbols.get(sym)
            if state is None:
                state = SymbolState(buffer=RingBuffer(RING_SIZE), cap_rank=self.cap_weights.get(sym, 999))
            state.buffer.push(ev)

            price = _parse_float(ev.get("c"))
            ts = ev.get("E")
            if price is None or ts is None:
                self.symbols[sym] = state
                continue

            if state.last_price is not None and state.last_timestamp is not None:
                dt_sec = max((ts - state.last_timestamp) / 1000.0, 1e-3)
                speed = (price - state.last_price) / dt_sec
                accel = None
                if state.last_speed is not None:
                    accel = (speed - state.last_speed) / dt_sec
                state.prev_speed = state.last_speed
                state.last_speed = speed
                if accel is not None:
                    state.last_accel = accel
            else:
                state.last_speed = None
                state.prev_speed = None
                state.last_accel = None

            state.last_price = price
            state.last_timestamp = ts
            self.symbols[sym] = state

    def has_data(self) -> bool:
        return any(state.buffer.length() > 0 for state in self.symbols.values())

    def compute_snapshot(self, now: int) -> dict:
        symbol_snapshots: List[dict] = []
        min_hl = float("inf")
        max_hl = float("-inf")

        for state in self.symbols.values():
            vals = state.buffer.values()
            if not vals:
                continue
            latest = vals[-1]
            high = _parse_float(latest.get("h"))
            low = _parse_float(latest.get("l"))
            if low and low > 0 and high is not None:
                hl_diff = abs((high - low) / low)
                min_hl = min(min_hl, hl_diff)
                max_hl = max(max_hl, hl_diff)

        if min_hl == float("inf"):
            min_hl = 0.0
            max_hl = 0.0

        hl_range = max_hl - min_hl or 1.0

        for sym, state in self.symbols.items():
            vals = state.buffer.values()
            if not vals:
                continue
            latest = vals[-1]

            last_price = _parse_float(latest.get("c"))
            open_price = _parse_float(latest.get("o"))
            high = _parse_float(latest.get("h"))
            low = _parse_float(latest.get("l"))

            if last_price is None or open_price is None or high is None or low is None or low <= 0:
                continue

            change_24h_pct = ((last_price - open_price) / open_price) * 100.0
            hl_diff_abs = abs((high - low) / low)
            normalized_hl = (hl_diff_abs - min_hl) / hl_range

            cap_rank = state.cap_rank
            weight = 1.0 / max(1, cap_rank)
            score = weight + normalized_hl

            ohlc = build_ohlc(vals, CANDLE_WINDOW_MS, now)

            symbol_snapshots.append(
                {
                    "sym": sym,
                    "last": last_price,
                    "change24hPct": change_24h_pct,
                    "hlDiffAbs": hl_diff_abs,
                    "score": score,
                    "capRank": cap_rank,
                    "accel": state.last_accel,
                    "ohlc": ohlc,
                }
            )

        symbol_snapshots.sort(key=lambda s: s["score"], reverse=True)
        top5 = symbol_snapshots[:5]

        agg_momentum = self._compute_aggregate_momentum()
        agg_accel = self._compute_aggregate_acceleration()

        self.momentum_series.append({"t": now, "v": agg_momentum})
        self.accel_series.append({"t": now, "v": agg_accel})
        self._trim_series()

        return {
            "ts": now,
            "top": top5,
            "market": {
                "momentum": list(self.momentum_series),
                "acceleration": list(self.accel_series),
            },
        }

    def _trim_series(self) -> None:
        if len(self.momentum_series) > MAX_SERIES_POINTS:
            self.momentum_series = self.momentum_series[-MAX_SERIES_POINTS:]
        if len(self.accel_series) > MAX_SERIES_POINTS:
            self.accel_series = self.accel_series[-MAX_SERIES_POINTS:]

    def _compute_aggregate_momentum(self) -> float:
        total = 0.0
        for state in self.symbols.values():
            if state.last_speed is not None:
                mass = 1.0 / max(1, state.cap_rank)
                total += mass * state.last_speed
        return total

    def _compute_aggregate_acceleration(self) -> float:
        total = 0.0
        count = 0
        for state in self.symbols.values():
            if state.last_accel is not None:
                total += state.last_accel
                count += 1
        if count == 0:
            return 0.0
        return total / count


def build_ohlc(events: List[dict], window_ms: int, now: int) -> List[dict]:
    cutoff = now - window_ms * 5
    buckets: Dict[int, List[dict]] = {}
    for ev in events:
        ts = ev.get("E")
        if ts is None or ts < cutoff:
            continue
        bucket = int(ts // window_ms)
        buckets.setdefault(bucket, []).append(ev)

    result: List[dict] = []
    for bucket in sorted(buckets.keys()):
        bucket_events = buckets[bucket]
        bucket_events.sort(key=lambda e: e.get("E", 0))
        o = _parse_float(bucket_events[0].get("c"))
        c = _parse_float(bucket_events[-1].get("c"))
        h = float("-inf")
        l = float("inf")
        for ev in bucket_events:
            p = _parse_float(ev.get("c"))
            if p is None:
                continue
            h = max(h, p)
            l = min(l, p)
        if o is not None and c is not None and h != float("-inf") and l != float("inf"):
            result.append({"t": bucket * window_ms, "o": o, "h": h, "l": l, "c": c})

    return result[-CANDLE_COUNT:]


def _parse_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
