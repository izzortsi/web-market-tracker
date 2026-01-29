from __future__ import annotations

import json
import logging
import threading
import time
from typing import Dict, Optional, Any, List

from kafka import KafkaConsumer

from ..config import (
    BINANCE_REST_BASE,
    GLOBAL_TICK_SEC,
    KAFKA_BROKER,
    RAW_TOPIC,
    EMA_ALPHA,
    EMA_BETA,
    EMA_GAMMA,
    MAX_ACTIVE_SYMBOLS,
    RANGE_LOW,
    RANGE_HIGH,
    MIN_QUOTE_VOLUME_24H,
    VOL_STD_WINDOW_COUNT,
    VOL_REFRESH_SEC,
    FEE_ROUND_TRIP,
    SLIP_BUFFER,
    VOL_FEE_MULTIPLIER,
    PROMOTION_CONFIRM_SEC,
    PROMOTION_MIN_HOLD_SEC,
    KLINE_INTERVAL,
    KLINE_BOOTSTRAP_COUNT,
    KELTNER_EMA_LENGTH,
    KELTNER_ATR_LENGTH,
    KELTNER_MULTIPLES,
    MAX_SERIES_POINTS,
    AGG_TRADE_CHUNK_SIZE,
    AGG_TRADE_MIN_CHUNK_SIZE,
    AGG_TRADE_MAX_FAIL_BEFORE_REDUCE,
    AGG_TRADE_RECONNECT_SEC,
    LOG_SCREENING_EVERY_SEC,
    LOG_CANDIDATE_LIMIT,
)
from .agg_trade_streams import AggTradeStreamManager, AggTradeEvent
from .global_metrics import GlobalMetricEngine, GlobalMetricSample
from .volatility import VolatilityService
from .screener import Screener, ScreeningResult
from .kline_tracker import KlineTrackerManager
from .universe import UniverseManager

logger = logging.getLogger(__name__)


class ProcessorService:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._consumer = KafkaConsumer(
            RAW_TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            group_id="raw-processor",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )

        self.universe = UniverseManager(BINANCE_REST_BASE)
        self.metrics = GlobalMetricEngine(
            alpha=EMA_ALPHA,
            beta=EMA_BETA,
            gamma=EMA_GAMMA,
            max_samples=MAX_SERIES_POINTS,
        )
        self.volatility = VolatilityService(
            rest_base=BINANCE_REST_BASE,
            interval=KLINE_INTERVAL,
            window_count=VOL_STD_WINDOW_COUNT,
            refresh_sec=VOL_REFRESH_SEC,
        )
        self.screener = Screener(
            volatility=self.volatility,
            max_active_symbols=MAX_ACTIVE_SYMBOLS,
            range_low=RANGE_LOW,
            range_high=RANGE_HIGH,
            min_quote_volume_24h=MIN_QUOTE_VOLUME_24H,
            fee_round_trip=FEE_ROUND_TRIP,
            slip_buffer=SLIP_BUFFER,
            vol_fee_multiplier=VOL_FEE_MULTIPLIER,
            confirm_sec=PROMOTION_CONFIRM_SEC,
            min_hold_sec=PROMOTION_MIN_HOLD_SEC,
        )
        self.kline_tracker = KlineTrackerManager(
            rest_base=BINANCE_REST_BASE,
            interval=KLINE_INTERVAL,
            bootstrap_count=KLINE_BOOTSTRAP_COUNT,
            ema_length=KELTNER_EMA_LENGTH,
            atr_length=KELTNER_ATR_LENGTH,
            band_multiples=KELTNER_MULTIPLES,
        )

        self._agg_trade_manager: Optional[AggTradeStreamManager] = None
        self._ticker_stats: Dict[str, dict] = {}
        self._eligible_symbols: set[str] = set()
        self.latest_global_sample: Optional[GlobalMetricSample] = None
        self.latest_screening: Optional[ScreeningResult] = None
        self._last_screen_log = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        try:
            self.universe.bootstrap()
            self._ticker_stats.update(self.universe.ticker_24h)
            self._eligible_symbols = set(self.universe.eligible_symbols)
        except Exception as exc:
            logger.warning("Universe bootstrap failed: %s", exc)

        self.kline_tracker.start()

        symbols = list(self.universe.eligible_symbols)
        self._agg_trade_manager = AggTradeStreamManager(
            symbols=symbols,
            chunk_size=AGG_TRADE_CHUNK_SIZE,
            reconnect_delay_sec=AGG_TRADE_RECONNECT_SEC,
            on_trade=self._handle_trade,
            min_chunk_size=AGG_TRADE_MIN_CHUNK_SIZE,
            max_failures_before_reduce=AGG_TRADE_MAX_FAIL_BEFORE_REDUCE,
        )
        self._agg_trade_manager.start()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._consumer.close()
        self.kline_tracker.stop()
        if self._agg_trade_manager:
            self._agg_trade_manager.stop()

    def get_global_series(self) -> List[dict]:
        return [sample.__dict__ for sample in self.metrics.get_series()]

    def get_candidates(self) -> List[dict]:
        if self.latest_screening is None:
            return []
        return [
            {
                "symbol": c.symbol,
                "score": c.score,
                "range_pos": c.range_pos,
                "sigma_1m": c.sigma_1m,
                "quote_volume_24h": c.quote_volume_24h,
                "fee_threshold": c.fee_threshold,
            }
            for c in self.latest_screening.candidates
        ]

    def get_promoted(self) -> List[str]:
        if self.latest_screening is None:
            return []
        return list(self.latest_screening.promoted)

    def is_promoted(self, symbol: str) -> bool:
        if self.latest_screening is None:
            return False
        return symbol in self.latest_screening.promoted

    def get_symbol_state(self, symbol: str) -> Optional[dict]:
        state = self.kline_tracker.get_state(symbol)
        if state is None:
            return None
        keltner = None
        if state.keltner:
            keltner = {
                "basis": state.keltner.basis,
                "atr": state.keltner.atr,
                "multiples": {
                    str(k): {"lower": v[0], "upper": v[1]}
                    for k, v in state.keltner.multiples.items()
                },
            }
        return {
            "symbol": state.symbol,
            "interval": state.interval,
            "updated_at_ms": state.updated_at_ms,
            "klines": [
                {
                    "t": k.open_time,
                    "T": k.close_time,
                    "o": k.open,
                    "h": k.high,
                    "l": k.low,
                    "c": k.close,
                    "v": k.volume,
                    "x": k.is_closed,
                }
                for k in state.klines
            ],
            "keltner": keltner,
        }

    def _run(self) -> None:
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            try:
                records = self._consumer.poll(timeout_ms=500)
                for _, messages in records.items():
                    for msg in messages:
                        ev = msg.value
                        if not isinstance(ev, dict):
                            continue
                        self._handle_raw_event(ev)

                now = time.monotonic()
                if now >= next_tick:
                    self._update_tick()
                    next_tick = now + GLOBAL_TICK_SEC
            except Exception as exc:
                logger.exception("Processor loop error: %s", exc)
                time.sleep(1)

    def _handle_raw_event(self, ev: dict) -> None:
        sym = ev.get("s")
        ts = ev.get("E")
        price = _parse_float(ev.get("c"))
        if sym is None or ts is None or price is None:
            return
        if self._eligible_symbols and sym not in self._eligible_symbols:
            return

        self._ticker_stats[sym] = ev

    def _handle_trade(self, trade: AggTradeEvent) -> None:
        self.metrics.ingest_trade(
            trade.symbol,
            trade.price,
            trade.qty,
            trade.event_time_ms,
        )

    def _update_tick(self) -> None:
        tick_sec = int(time.time())
        self.latest_global_sample = self.metrics.finalize_tick(tick_sec)

        market_dir = 0.0
        if self.latest_global_sample.Fbar > 0:
            market_dir = 1.0
        elif self.latest_global_sample.Fbar < 0:
            market_dir = -1.0

        now_sec = time.time()
        self.latest_screening = self.screener.evaluate(self._ticker_stats, market_dir, now_sec)
        self.kline_tracker.set_symbols(self.latest_screening.promoted)

        if now_sec - self._last_screen_log >= LOG_SCREENING_EVERY_SEC:
            self._last_screen_log = now_sec
            promoted = list(self.latest_screening.promoted)
            top_candidates = [
                f"{c.symbol}:{c.score:.3f}" for c in self.latest_screening.candidates[:LOG_CANDIDATE_LIMIT]
            ]
            logger.info("Promoted: %s", promoted)
            logger.info("Candidates (top %s): %s", LOG_CANDIDATE_LIMIT, top_candidates)


def _parse_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
