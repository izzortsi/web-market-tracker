from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
from collections import deque


@dataclass
class SymbolMetricState:
    symbol: str
    last_trade_price: Optional[float] = None
    tick_bucket_sec: Optional[int] = None
    tick_volume: float = 0.0
    tick_last_trade_price: Optional[float] = None

    prev_price: Optional[float] = None
    prev_mass: Optional[float] = None
    prev_P: Optional[float] = None

    vol_ema: Optional[float] = None
    slow_price_ema: Optional[float] = None
    vel_ema: Optional[float] = None


@dataclass(frozen=True)
class GlobalMetricSample:
    tick_sec: int
    Pbar: float
    Fbar: float
    active_symbol_count: int
    fresh_trade_count: int
    top_contributors: List[Tuple[str, float]]


class GlobalMetricEngine:
    def __init__(
        self,
        alpha: float,
        beta: float,
        gamma: float,
        max_samples: int = 300,
    ) -> None:
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.states: Dict[str, SymbolMetricState] = {}
        self.samples = deque(maxlen=max_samples)

    def ingest_trade(self, symbol: str, price: float, qty: float, event_time_ms: int) -> None:
        state = self.states.get(symbol)
        if state is None:
            state = SymbolMetricState(symbol=symbol)
            self.states[symbol] = state

        bucket_sec = int(event_time_ms // 1000)
        if state.tick_bucket_sec is None or bucket_sec != state.tick_bucket_sec:
            state.tick_bucket_sec = bucket_sec
            state.tick_volume = 0.0
            state.tick_last_trade_price = None

        state.tick_volume += qty
        state.tick_last_trade_price = price
        state.last_trade_price = price

    def finalize_tick(self, tick_sec: int) -> GlobalMetricSample:
        total_weight = 0.0
        weighted_P = 0.0
        weighted_F = 0.0
        active = 0
        fresh = 0
        contribs: List[Tuple[str, float]] = []

        for sym, state in self.states.items():
            price = state.tick_last_trade_price or state.last_trade_price or state.prev_price
            if price is None:
                continue

            active += 1

            if state.tick_bucket_sec == tick_sec:
                delta_v = state.tick_volume
                if delta_v > 0:
                    fresh += 1
            else:
                delta_v = 0.0

            prev_price = state.prev_price if state.prev_price is not None else price
            delta_p = price - prev_price

            vol_ema = _ema_update(state.vol_ema, delta_v, self.alpha)
            slow_price_ema = _ema_update(state.slow_price_ema, price, self.gamma)
            vel_ema = _ema_update(state.vel_ema, delta_p, self.beta)

            mass = (vol_ema or 0.0) * (slow_price_ema or price)
            P = mass * (vel_ema or 0.0)
            prev_P = state.prev_P or 0.0
            F = P - prev_P

            weight_mass = state.prev_mass
            if weight_mass is not None and weight_mass > 0:
                total_weight += weight_mass
                weighted_P += weight_mass * P
                weighted_F += weight_mass * F
                contribs.append((sym, weight_mass * F))

            state.prev_price = price
            state.prev_mass = mass
            state.prev_P = P
            state.vol_ema = vol_ema
            state.slow_price_ema = slow_price_ema
            state.vel_ema = vel_ema

            if state.tick_bucket_sec != tick_sec:
                state.tick_bucket_sec = tick_sec
                state.tick_volume = 0.0
                state.tick_last_trade_price = None

        if total_weight <= 0:
            Pbar = 0.0
            Fbar = 0.0
        else:
            Pbar = weighted_P / total_weight
            Fbar = weighted_F / total_weight

        contribs.sort(key=lambda x: abs(x[1]), reverse=True)
        top = contribs[:10]

        sample = GlobalMetricSample(
            tick_sec=tick_sec,
            Pbar=Pbar,
            Fbar=Fbar,
            active_symbol_count=active,
            fresh_trade_count=fresh,
            top_contributors=top,
        )
        self.samples.append(sample)
        return sample

    def get_series(self) -> List[GlobalMetricSample]:
        return list(self.samples)


def _ema_update(prev: Optional[float], value: float, alpha: float) -> float:
    if prev is None:
        return value
    return (alpha * value) + ((1 - alpha) * prev)
