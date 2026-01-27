from pydantic import BaseModel
from typing import List, Optional


class OHLC(BaseModel):
    t: int
    o: float
    h: float
    l: float
    c: float


class MarketSeriesPoint(BaseModel):
    t: int
    v: float


class SymbolSnapshot(BaseModel):
    sym: str
    last: float
    change24hPct: float
    hlDiffAbs: float
    score: float
    capRank: int
    accel: Optional[float] = None
    ohlc: List[OHLC]


class MarketSeries(BaseModel):
    momentum: List[MarketSeriesPoint]
    acceleration: List[MarketSeriesPoint]


class MarketSummaryPayload(BaseModel):
    ts: int
    top: List[SymbolSnapshot]
    market: MarketSeries
