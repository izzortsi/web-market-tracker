from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from .ring_buffer import RingBuffer
from ..config import RING_SIZE, MAX_SERIES_POINTS, CANDLE_WINDOW_MS, CANDLE_COUNT, BAR_INTERVAL_SEC


@dataclass
class SymbolState:
    buffer: RingBuffer[dict]
    cap_rank: int = 999


class MarketStore:
    def __init__(self, cap_weights: Dict[str, int]) -> None:
        self.symbols: Dict[str, SymbolState] = {}
        self.momentum_series: List[dict] = []
        self.accel_series: List[dict] = []
        self.cap_weights = cap_weights

    def update_candle(self, symbol: str, candle: dict, is_new: bool) -> None:
        state = self.symbols.get(symbol)
        if state is None:
            state = SymbolState(buffer=RingBuffer(RING_SIZE), cap_rank=self.cap_weights.get(symbol, 999))
        if is_new:
            state.buffer.push(candle)
        else:
            state.buffer.update_last(candle)
        self.symbols[symbol] = state

    def get_last_candle_ts(self, symbol: str) -> Optional[int]:
        state = self.symbols.get(symbol)
        if state is None:
            return None
        values = state.buffer.values()
        if not values:
            return None
        return values[-1].get("t")

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
            highs = [v["h"] for v in vals if "h" in v]
            lows = [v["l"] for v in vals if "l" in v]
            if not highs or not lows:
                continue
            hl_diff = (max(highs) - min(lows)) / max(min(lows), 1e-9)
            min_hl = min(min_hl, hl_diff)
            max_hl = max(max_hl, hl_diff)

        if min_hl == float("inf"):
            min_hl = 0.0
            max_hl = 0.0

        hl_range = max_hl - min_hl or 1.0

        for sym, state in self.symbols.items():
            vals = state.buffer.values()
            if len(vals) < CANDLE_COUNT:
                continue

            last_close = _parse_float(vals[-1].get("c"))
            first_open = _parse_float(vals[0].get("o"))
            highs = [v.get("h") for v in vals]
            lows = [v.get("l") for v in vals]
            if last_close is None or first_open is None:
                continue

            change_window_pct = ((last_close - first_open) / first_open) * 100.0 if first_open else 0.0
            max_high = max(h for h in highs if h is not None)
            min_low = min(l for l in lows if l is not None)
            hl_diff_abs = (max_high - min_low) / max(min_low, 1e-9)
            normalized_hl = (hl_diff_abs - min_hl) / hl_range

            cap_rank = state.cap_rank
            weight = 1.0 / max(1, cap_rank)
            score = weight + normalized_hl

            speed = _compute_speed(vals)
            accel = _compute_accel(vals)

            symbol_snapshots.append(
                {
                    "sym": sym,
                    "last": last_close,
                    "change24hPct": change_window_pct,
                    "hlDiffAbs": hl_diff_abs,
                    "score": score,
                    "capRank": cap_rank,
                    "speed": speed,
                    "accel": accel,
                    "ohlc": vals[-CANDLE_COUNT:],
                }
            )

        symbol_snapshots.sort(key=lambda s: s["score"], reverse=True)
        top5 = symbol_snapshots[:5]

        agg_momentum = self._compute_aggregate_momentum(symbol_snapshots)
        agg_accel = self._compute_aggregate_acceleration(symbol_snapshots)

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

    def _compute_aggregate_momentum(self, snapshots: List[dict]) -> float:
        total = 0.0
        for snap in snapshots:
            speed = snap.get("speed")
            if speed is None:
                continue
            cap_rank = snap.get("capRank", 999)
            mass = 1.0 / max(1, cap_rank)
            total += mass * speed
        return total

    def _compute_aggregate_acceleration(self, snapshots: List[dict]) -> float:
        total = 0.0
        count = 0
        for snap in snapshots:
            accel = snap.get("accel")
            if accel is not None:
                total += accel
                count += 1
        if count == 0:
            return 0.0
        return total / count


def _parse_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_speed(vals: List[dict]) -> Optional[float]:
    if len(vals) < 2:
        return None
    c1 = _parse_float(vals[-1].get("c"))
    c0 = _parse_float(vals[-2].get("c"))
    if c1 is None or c0 is None:
        return None
    return (c1 - c0) / BAR_INTERVAL_SEC


def _compute_accel(vals: List[dict]) -> Optional[float]:
    if len(vals) < 3:
        return None
    c2 = _parse_float(vals[-3].get("c"))
    c1 = _parse_float(vals[-2].get("c"))
    c0 = _parse_float(vals[-1].get("c"))
    if c0 is None or c1 is None or c2 is None:
        return None
    speed_prev = (c1 - c2) / BAR_INTERVAL_SEC
    speed_now = (c0 - c1) / BAR_INTERVAL_SEC
    return (speed_now - speed_prev) / BAR_INTERVAL_SEC
