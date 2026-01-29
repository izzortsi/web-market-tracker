from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional, List, Set, Tuple

import requests
import websockets


@dataclass
class Kline:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


@dataclass
class KeltnerBands:
    basis: float
    atr: float
    multiples: Dict[float, Tuple[float, float]]


@dataclass
class SymbolKlineState:
    symbol: str
    interval: str
    klines: deque
    keltner: Optional[KeltnerBands]
    updated_at_ms: int


class KlineTrackerManager:
    def __init__(
        self,
        rest_base: str,
        interval: str,
        bootstrap_count: int,
        ema_length: int,
        atr_length: int,
        band_multiples: List[float],
    ) -> None:
        self.rest_base = rest_base.rstrip("/")
        self.interval = interval
        self.bootstrap_count = bootstrap_count
        self.ema_length = ema_length
        self.atr_length = atr_length
        self.band_multiples = band_multiples

        self._states: Dict[str, SymbolKlineState] = {}
        self._symbols: Set[str] = set()
        self._lock = threading.Lock()

        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def set_symbols(self, symbols: List[str]) -> None:
        new_symbols = set(symbols)
        with self._lock:
            if new_symbols == self._symbols:
                return
            added = new_symbols - self._symbols
            removed = self._symbols - new_symbols
            self._symbols = new_symbols

        for sym in added:
            self._bootstrap_symbol(sym)

        for sym in removed:
            self._states.pop(sym, None)

        self._restart_event.set()

    def get_state(self, symbol: str) -> Optional[SymbolKlineState]:
        return self._states.get(symbol)

    def get_all_states(self) -> Dict[str, SymbolKlineState]:
        return dict(self._states)

    def _run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        while not self._stop_event.is_set():
            symbols = self._get_symbols()
            if not symbols:
                await asyncio.sleep(0.5)
                continue
            stream_url = _build_stream_url(symbols, self.interval)
            try:
                async with websockets.connect(stream_url, ping_interval=20, ping_timeout=20) as ws:
                    self._restart_event.clear()
                    while not self._stop_event.is_set():
                        if self._restart_event.is_set():
                            break
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        self._handle_message(message)
            except Exception:
                await asyncio.sleep(1)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return
        if data.get("e") != "kline":
            return

        symbol = data.get("s")
        k = data.get("k", {})
        if symbol is None or not isinstance(k, dict):
            return

        kline = Kline(
            open_time=int(k.get("t")),
            close_time=int(k.get("T")),
            open=float(k.get("o")),
            high=float(k.get("h")),
            low=float(k.get("l")),
            close=float(k.get("c")),
            volume=float(k.get("v")),
            is_closed=bool(k.get("x")),
        )
        self._update_symbol_kline(symbol, kline)

    def _update_symbol_kline(self, symbol: str, kline: Kline) -> None:
        state = self._states.get(symbol)
        if state is None:
            state = SymbolKlineState(
                symbol=symbol,
                interval=self.interval,
                klines=deque(maxlen=self.bootstrap_count),
                keltner=None,
                updated_at_ms=int(time.time() * 1000),
            )
            self._states[symbol] = state

        if state.klines and state.klines[-1].open_time == kline.open_time:
            state.klines[-1] = kline
        else:
            state.klines.append(kline)

        state.keltner = _compute_keltner(list(state.klines), self.ema_length, self.atr_length, self.band_multiples)
        state.updated_at_ms = int(time.time() * 1000)

    def _bootstrap_symbol(self, symbol: str) -> None:
        try:
            params = {
                "symbol": symbol,
                "interval": self.interval,
                "limit": self.bootstrap_count,
            }
            url = f"{self.rest_base}/fapi/v1/klines"
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            klines = deque(maxlen=self.bootstrap_count)
            for entry in data:
                klines.append(
                    Kline(
                        open_time=int(entry[0]),
                        close_time=int(entry[6]) if len(entry) > 6 else int(entry[0]),
                        open=float(entry[1]),
                        high=float(entry[2]),
                        low=float(entry[3]),
                        close=float(entry[4]),
                        volume=float(entry[5]),
                        is_closed=True,
                    )
                )
            state = SymbolKlineState(
                symbol=symbol,
                interval=self.interval,
                klines=klines,
                keltner=_compute_keltner(list(klines), self.ema_length, self.atr_length, self.band_multiples),
                updated_at_ms=int(time.time() * 1000),
            )
            self._states[symbol] = state
        except Exception:
            return

    def _get_symbols(self) -> List[str]:
        with self._lock:
            return sorted(self._symbols)


def _build_stream_url(symbols: List[str], interval: str) -> str:
    streams = "/".join([f"{sym.lower()}@kline_{interval}" for sym in symbols])
    return f"wss://fstream.binance.com/stream?streams={streams}"


def _compute_keltner(
    klines: List[Kline],
    ema_len: int,
    atr_len: int,
    multiples: List[float],
) -> Optional[KeltnerBands]:
    if len(klines) < max(ema_len, atr_len) + 1:
        return None

    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]

    ema = _ema_series(closes, ema_len)
    atr = _atr_series(highs, lows, closes, atr_len)

    basis = ema[-1]
    atr_val = atr[-1]
    bands: Dict[float, Tuple[float, float]] = {}
    for k in multiples:
        bands[k] = (basis - k * atr_val, basis + k * atr_val)

    return KeltnerBands(basis=basis, atr=atr_val, multiples=bands)


def _ema_series(values: List[float], length: int) -> List[float]:
    if not values:
        return []
    alpha = 2 / (length + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(alpha * v + (1 - alpha) * ema[-1])
    return ema


def _atr_series(highs: List[float], lows: List[float], closes: List[float], length: int) -> List[float]:
    trs: List[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return []
    alpha = 2 / (length + 1)
    atr = [sum(trs[:length]) / max(1, length)]
    for tr in trs[length:]:
        atr.append(alpha * tr + (1 - alpha) * atr[-1])
    return atr
