from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .volatility import VolatilityService


@dataclass(frozen=True)
class CandidateScore:
    symbol: str
    score: float
    range_pos: float
    sigma_1m: float
    quote_volume_24h: Optional[float]
    fee_threshold: float


@dataclass(frozen=True)
class ScreeningResult:
    candidates: List[CandidateScore]
    promoted: List[str]


class Screener:
    def __init__(
        self,
        volatility: VolatilityService,
        max_active_symbols: int,
        range_low: float,
        range_high: float,
        min_quote_volume_24h: Optional[float],
        fee_round_trip: float,
        slip_buffer: float,
        vol_fee_multiplier: float,
        confirm_sec: float,
        min_hold_sec: float,
    ) -> None:
        self.volatility = volatility
        self.max_active_symbols = max_active_symbols
        self.range_low = range_low
        self.range_high = range_high
        self.min_quote_volume_24h = min_quote_volume_24h
        self.fee_round_trip = fee_round_trip
        self.slip_buffer = slip_buffer
        self.vol_fee_multiplier = vol_fee_multiplier

        self.confirm_sec = confirm_sec
        self.min_hold_sec = min_hold_sec

        self._candidate_since: Dict[str, float] = {}
        self._promoted_since: Dict[str, float] = {}

    def evaluate(
        self,
        ticker_stats: Dict[str, dict],
        market_direction: float,
        now_sec: float,
    ) -> ScreeningResult:
        candidates: List[CandidateScore] = []
        fee_threshold = self.fee_round_trip + self.slip_buffer
        vol_gate = self.vol_fee_multiplier * fee_threshold

        for sym, stats in ticker_stats.items():
            high = _parse_float(stats.get("h"))
            low = _parse_float(stats.get("l"))
            last = _parse_float(stats.get("c"))
            quote_volume = _parse_float(stats.get("q"))

            if high is None or low is None or last is None:
                continue
            if high <= low:
                continue
            if self.min_quote_volume_24h is not None and (quote_volume is None or quote_volume < self.min_quote_volume_24h):
                continue

            range_pos = (high - last) / (high - low)

            if market_direction > 0:
                if range_pos < self.range_high:
                    continue
            elif market_direction < 0:
                if range_pos > self.range_low:
                    continue
            else:
                if not (range_pos <= self.range_low or range_pos >= self.range_high):
                    continue

            sigma_snapshot = self.volatility.get_sigma(sym)
            if sigma_snapshot is None:
                continue

            sigma = sigma_snapshot.sigma_1m
            if sigma < vol_gate:
                continue

            extremeness = abs(range_pos - 0.5)
            score = extremeness * (sigma / max(vol_gate, 1e-9))
            candidates.append(
                CandidateScore(
                    symbol=sym,
                    score=score,
                    range_pos=range_pos,
                    sigma_1m=sigma,
                    quote_volume_24h=quote_volume,
                    fee_threshold=fee_threshold,
                )
            )

        candidates.sort(key=lambda x: x.score, reverse=True)

        candidate_symbols = {c.symbol for c in candidates}
        for sym in candidate_symbols:
            if sym not in self._candidate_since:
                self._candidate_since[sym] = now_sec
        for sym in list(self._candidate_since.keys()):
            if sym not in candidate_symbols:
                self._candidate_since.pop(sym, None)

        eligible = [c for c in candidates if (now_sec - self._candidate_since.get(c.symbol, now_sec)) >= self.confirm_sec]

        desired = [c.symbol for c in eligible[: self.max_active_symbols]]
        desired_set = set(desired)

        final_promoted: List[str] = []
        for sym in list(self._promoted_since.keys()):
            if sym in desired_set:
                continue
            if (now_sec - self._promoted_since[sym]) < self.min_hold_sec:
                desired_set.add(sym)

        for c in candidates:
            if len(final_promoted) >= self.max_active_symbols:
                break
            if c.symbol in desired_set:
                final_promoted.append(c.symbol)

        for sym in final_promoted:
            if sym not in self._promoted_since:
                self._promoted_since[sym] = now_sec
        for sym in list(self._promoted_since.keys()):
            if sym not in final_promoted:
                self._promoted_since.pop(sym, None)

        return ScreeningResult(candidates=candidates, promoted=final_promoted)


def _parse_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
