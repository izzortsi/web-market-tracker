from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import itertools
import time


@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    side: str  # BUY or SELL
    qty: float
    price: float
    ts_ms: int
    status: str  # FILLED or REJECTED


@dataclass
class PaperTrade:
    trade_id: str
    order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    ts_ms: int


@dataclass
class PaperPosition:
    symbol: str
    qty: float
    avg_price: float
    realized_pnl: float


class PaperLedger:
    def __init__(self, starting_equity: float) -> None:
        self.starting_equity = starting_equity
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: List[PaperOrder] = []
        self.trades: List[PaperTrade] = []

    def apply_trade(self, trade: PaperTrade) -> None:
        pos = self.positions.get(trade.symbol)
        if pos is None:
            pos = PaperPosition(symbol=trade.symbol, qty=0.0, avg_price=0.0, realized_pnl=0.0)

        signed_qty = trade.qty if trade.side == "BUY" else -trade.qty

        if pos.qty == 0:
            pos.qty = signed_qty
            pos.avg_price = trade.price
        elif (pos.qty > 0 and signed_qty > 0) or (pos.qty < 0 and signed_qty < 0):
            new_qty = pos.qty + signed_qty
            pos.avg_price = (pos.avg_price * abs(pos.qty) + trade.price * abs(signed_qty)) / max(abs(new_qty), 1e-9)
            pos.qty = new_qty
        else:
            # Reducing or flipping
            closing_qty = min(abs(pos.qty), abs(signed_qty))
            pnl = closing_qty * (trade.price - pos.avg_price) * (1 if pos.qty > 0 else -1)
            pos.realized_pnl += pnl
            pos.qty += signed_qty
            if pos.qty == 0:
                pos.avg_price = 0.0
            else:
                pos.avg_price = trade.price

        self.positions[trade.symbol] = pos

    def total_equity(self) -> float:
        return self.starting_equity + sum(p.realized_pnl for p in self.positions.values())

    def total_exposure(self, price_map: Dict[str, float]) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            price = price_map.get(sym)
            if price is None:
                continue
            total += abs(pos.qty * price)
        return total

    def symbol_exposure(self, symbol: str, price: float) -> float:
        pos = self.positions.get(symbol)
        if pos is None:
            return 0.0
        return abs(pos.qty * price)


class PaperTradingEngine:
    def __init__(
        self,
        starting_equity: float,
        max_total_pct: float,
        max_symbol_pct: float,
        band_multiples: List[float],
        min_active_bands: int = 1,
    ) -> None:
        self.ledger = PaperLedger(starting_equity)
        self.max_total_pct = max_total_pct
        self.max_symbol_pct = max_symbol_pct
        self.band_multiples = band_multiples
        self.min_active_bands = min_active_bands

        self._order_seq = itertools.count(1)
        self._trade_seq = itertools.count(1)

        self._last_price: Dict[str, float] = {}
        self._last_market_dir: Optional[float] = None
        self._active_band_count = len(band_multiples)

    def update(
        self,
        promoted_symbols: List[str],
        symbol_states: Dict[str, dict],
        market_dir: float,
    ) -> None:
        if self._last_market_dir is None:
            self._last_market_dir = market_dir
        elif market_dir != 0.0 and self._last_market_dir != 0.0 and market_dir != self._last_market_dir:
            self._active_band_count = max(self.min_active_bands, self._active_band_count - 1)
            self._last_market_dir = market_dir
        else:
            if self._active_band_count < len(self.band_multiples):
                self._active_band_count += 1
            self._last_market_dir = market_dir

        for sym in promoted_symbols:
            state = symbol_states.get(sym)
            if state is None:
                continue
            klines = state.get("klines", [])
            if not klines:
                continue
            last_close = klines[-1].get("c")
            if last_close is None:
                continue
            price = float(last_close)
            prev_price = self._last_price.get(sym, price)
            self._last_price[sym] = price

            keltner = state.get("keltner") or {}
            multiples = keltner.get("multiples") or {}
            if not multiples:
                continue

            active_bands = _select_active_bands(multiples, self.band_multiples, self._active_band_count)

            # Determine crossings
            if market_dir < 0:  # market down, we short on upward band cross
                crossed = _crossed_up(prev_price, price, active_bands)
                if crossed is not None:
                    self._execute_trade(sym, "SELL", price, crossed)
            elif market_dir > 0:  # market up, we long on downward band cross
                crossed = _crossed_down(prev_price, price, active_bands)
                if crossed is not None:
                    self._execute_trade(sym, "BUY", price, crossed)

    def _execute_trade(self, symbol: str, side: str, price: float, band_key: float) -> None:
        equity = self.ledger.total_equity()
        max_total = equity * self.max_total_pct
        max_symbol = equity * self.max_symbol_pct

        total_exposure = self.ledger.total_exposure({symbol: price})
        if total_exposure >= max_total:
            return
        if self.ledger.symbol_exposure(symbol, price) >= max_symbol:
            return

        # size: allocate equal notional per active band
        notional = min(max_symbol - self.ledger.symbol_exposure(symbol, price), max_total - total_exposure)
        if notional <= 0:
            return
        qty = notional / price

        now_ms = int(time.time() * 1000)
        order_id = f"paper-{next(self._order_seq)}"
        trade_id = f"trade-{next(self._trade_seq)}"

        order = PaperOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            ts_ms=now_ms,
            status="FILLED",
        )
        trade = PaperTrade(
            trade_id=trade_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            ts_ms=now_ms,
        )

        self.ledger.orders.append(order)
        self.ledger.trades.append(trade)
        self.ledger.apply_trade(trade)


def _select_active_bands(
    multiples: Dict[str, dict],
    band_multiples: List[float],
    active_count: int,
) -> List[Tuple[float, float, float]]:
    ordered = sorted([m for m in band_multiples if str(m) in multiples])[:active_count]
    bands: List[Tuple[float, float, float]] = []
    for k in ordered:
        band = multiples.get(str(k))
        if band:
            bands.append((k, band["lower"], band["upper"]))
    return bands


def _crossed_up(prev_price: float, price: float, bands: List[Tuple[float, float, float]]) -> Optional[float]:
    for k, lower, upper in bands:
        if prev_price <= upper < price:
            return k
    return None


def _crossed_down(prev_price: float, price: float, bands: List[Tuple[float, float, float]]) -> Optional[float]:
    for k, lower, upper in bands:
        if prev_price >= lower > price:
            return k
    return None
