from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Dict, Optional, List

import requests


@dataclass(frozen=True)
class VolatilitySnapshot:
    symbol: str
    sigma_1m: float
    window_count: int
    interval: str
    updated_at_ms: int


class VolatilityService:
    def __init__(
        self,
        rest_base: str,
        interval: str,
        window_count: int,
        refresh_sec: float,
    ) -> None:
        self.rest_base = rest_base.rstrip("/")
        self.interval = interval
        self.window_count = window_count
        self.refresh_sec = refresh_sec
        self._cache: Dict[str, VolatilitySnapshot] = {}

    def get_sigma(self, symbol: str) -> Optional[VolatilitySnapshot]:
        snap = self._cache.get(symbol)
        now = time.monotonic()
        if snap and (now - (snap.updated_at_ms / 1000.0)) < self.refresh_sec:
            return snap

        klines = self._fetch_klines(symbol)
        if not klines:
            return None
        closes = [k[4] for k in klines]
        if len(closes) < 2:
            return None

        returns = _compute_returns(closes)
        if not returns:
            return None
        sigma = statistics.pstdev(returns)
        snapshot = VolatilitySnapshot(
            symbol=symbol,
            sigma_1m=sigma,
            window_count=self.window_count,
            interval=self.interval,
            updated_at_ms=int(time.time() * 1000),
        )
        self._cache[symbol] = snapshot
        return snapshot

    def _fetch_klines(self, symbol: str) -> List[List[float]]:
        params = {
            "symbol": symbol,
            "interval": self.interval,
            "limit": self.window_count + 1,
        }
        url = f"{self.rest_base}/fapi/v1/klines"
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        out: List[List[float]] = []
        for entry in data:
            out.append(
                [
                    float(entry[0]),
                    float(entry[1]),
                    float(entry[2]),
                    float(entry[3]),
                    float(entry[4]),
                    float(entry[5]),
                ]
            )
        return out


def _compute_returns(closes: List[float]) -> List[float]:
    returns: List[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev == 0:
            continue
        returns.append((curr / prev) - 1.0)
    return returns
