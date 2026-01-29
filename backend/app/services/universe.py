from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import requests


@dataclass(frozen=True)
class SymbolMeta:
    symbol: str
    status: Optional[str] = None
    base_asset: Optional[str] = None
    quote_asset: Optional[str] = None
    contract_type: Optional[str] = None


class UniverseManager:
    def __init__(self, rest_base: str) -> None:
        self.rest_base = rest_base.rstrip("/")
        self.symbols: Dict[str, SymbolMeta] = {}
        self.eligible_symbols: List[str] = []
        self.ticker_24h: Dict[str, dict] = {}

    def bootstrap(self) -> None:
        self._load_exchange_info()
        self._load_ticker_24h()

    def _load_exchange_info(self) -> None:
        url = f"{self.rest_base}/fapi/v1/exchangeInfo"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        symbols = data.get("symbols", [])

        eligible: Dict[str, SymbolMeta] = {}
        for entry in symbols:
            sym = entry.get("symbol")
            if not sym:
                continue
            if entry.get("status") != "TRADING":
                continue
            if entry.get("contractType") != "PERPETUAL":
                continue
            if entry.get("quoteAsset") != "USDT":
                continue

            eligible[sym] = SymbolMeta(
                symbol=sym,
                status=entry.get("status"),
                base_asset=entry.get("baseAsset"),
                quote_asset=entry.get("quoteAsset"),
                contract_type=entry.get("contractType"),
            )

        self.symbols = eligible
        self.eligible_symbols = sorted(eligible.keys())

    def _load_ticker_24h(self) -> None:
        url = f"{self.rest_base}/fapi/v1/ticker/24hr"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            for entry in data:
                sym = entry.get("symbol")
                if sym and sym in self.symbols:
                    self.ticker_24h[sym] = entry
