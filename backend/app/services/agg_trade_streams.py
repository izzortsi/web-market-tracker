from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

import websockets

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AggTradeEvent:
    symbol: str
    price: float
    qty: float
    event_time_ms: int


class ChunkReduceRequested(Exception):
    pass


class AggTradeStreamManager:
    def __init__(
        self,
        symbols: List[str],
        chunk_size: int,
        reconnect_delay_sec: float,
        on_trade: Callable[[AggTradeEvent], None],
        min_chunk_size: int = 5,
        max_failures_before_reduce: int = 3,
        reduce_on_error: bool = True,
    ) -> None:
        self.symbols = symbols
        self.chunk_size = max(1, chunk_size)
        self.reconnect_delay_sec = reconnect_delay_sec
        self.on_trade = on_trade

        self.min_chunk_size = max(1, min_chunk_size)
        self.max_failures_before_reduce = max(1, max_failures_before_reduce)
        self.reduce_on_error = reduce_on_error

        self._stop_event = threading.Event()
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

    def _run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        current_chunk_size = self.chunk_size
        while not self._stop_event.is_set():
            chunks = _chunk_symbols(self.symbols, current_chunk_size)
            try:
                await asyncio.gather(*[self._run_chunk(chunk) for chunk in chunks])
            except ChunkReduceRequested:
                if self.reduce_on_error and current_chunk_size > self.min_chunk_size:
                    new_size = max(self.min_chunk_size, current_chunk_size // 2)
                    if new_size != current_chunk_size:
                        logger.warning(
                            "Reducing aggTrade chunk size from %s to %s due to repeated failures.",
                            current_chunk_size,
                            new_size,
                        )
                        current_chunk_size = new_size
                await asyncio.sleep(self.reconnect_delay_sec)
            except Exception as exc:
                logger.warning("aggTrade stream manager error: %s", exc)
                await asyncio.sleep(self.reconnect_delay_sec)

    async def _run_chunk(self, symbols: List[str]) -> None:
        stream_url = _build_stream_url(symbols)
        failures = 0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(stream_url, ping_interval=20, ping_timeout=20) as ws:
                    failures = 0
                    async for message in ws:
                        self._handle_message(message)
            except Exception:
                failures += 1
                if self.reduce_on_error and failures >= self.max_failures_before_reduce:
                    raise ChunkReduceRequested()
                await asyncio.sleep(self.reconnect_delay_sec)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return
        if data.get("e") != "aggTrade":
            return

        symbol = data.get("s")
        price = _parse_float(data.get("p"))
        qty = _parse_float(data.get("q"))
        event_time = data.get("T") or data.get("E")
        if symbol is None or price is None or qty is None or event_time is None:
            return

        self.on_trade(AggTradeEvent(symbol=symbol, price=price, qty=qty, event_time_ms=int(event_time)))


def _build_stream_url(symbols: List[str]) -> str:
    streams = "/".join([f"{sym.lower()}@aggTrade" for sym in symbols])
    return f"wss://fstream.binance.com/stream?streams={streams}"


def _chunk_symbols(symbols: List[str], chunk_size: int) -> List[List[str]]:
    return [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]


def _parse_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
