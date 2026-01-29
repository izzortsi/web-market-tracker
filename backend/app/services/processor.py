from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import pandas_ta as ta
import requests
from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic

from ..config import (
    BAR_INTERVAL_SEC,
    FLUSH_INTERVAL_SEC,
    KAFKA_BROKER,
    PROCESSED_FLUSH_SIZE,
    PROCESSED_STORE_DIR,
    PROCESSED_TOPIC,
    PROCESSED_TOPIC_PARTITIONS,
    RAW_FLUSH_SIZE,
    RAW_STORE_DIR,
    RAW_TOPIC,
    RAW_TOPIC_PARTITIONS,
    SNAPSHOT_INTERVAL_SEC,
    CANDLE_COUNT,
)
from .market_store import MarketStore

logger = logging.getLogger(__name__)

BAR_INTERVAL_MS = BAR_INTERVAL_SEC * 1000
REST_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


@dataclass
class BarState:
    bucket: int
    o: float
    h: float
    l: float
    c: float
    v: float
    ts: int


class ProcessorService:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.latest_snapshot: Optional[dict] = None

        self._market_store = MarketStore({})
        self._bars: Dict[str, BarState] = {}
        self._bar_history: Dict[str, List[dict]] = {}
        self._seeded: set[str] = set()
        self._live_initialized: set[str] = set()
        self._watchlist: set[str] = set()
        self._ticker_stats: Dict[str, dict] = {}
        self._last_watchlist_refresh = time.monotonic()

        self._raw_buffer: List[dict] = []
        self._processed_buffer: List[dict] = []
        self._last_flush = time.monotonic()
        self._last_message_time = time.monotonic()

        self._producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            key_serializer=lambda k: k.encode("utf-8"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self._consumer = KafkaConsumer(
            RAW_TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            group_id="raw-processor",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )

        self._ensure_topics()
        RAW_STORE_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_STORE_DIR.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._consumer.close()
        self._producer.close()

    def get_snapshot(self) -> dict:
        if self.latest_snapshot is not None:
            return self.latest_snapshot
        now_ms = int(time.time() * 1000)
        return self._market_store.compute_snapshot(now_ms)

    def _ensure_topics(self) -> None:
        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BROKER)
        existing = {topic for topic in admin.list_topics()}
        topics = []
        if RAW_TOPIC not in existing:
            topics.append(NewTopic(name=RAW_TOPIC, num_partitions=RAW_TOPIC_PARTITIONS, replication_factor=1))
        if PROCESSED_TOPIC not in existing:
            topics.append(NewTopic(name=PROCESSED_TOPIC, num_partitions=PROCESSED_TOPIC_PARTITIONS, replication_factor=1))
        if topics:
            admin.create_topics(topics)
        admin.close()

    def _run(self) -> None:
        next_snapshot = time.monotonic()
        while not self._stop_event.is_set():
            try:
                records = self._consumer.poll(timeout_ms=1000)
                received = False
                for _, messages in records.items():
                    for msg in messages:
                        ev = msg.value
                        if not isinstance(ev, dict):
                            continue
                        received = True
                        self._last_message_time = time.monotonic()
                        self._handle_raw_event(ev)

                now = time.monotonic()
                if not received and (now - self._last_message_time) > 10:
                    logger.warning("No raw messages received for >10s (raw topic: %s)", RAW_TOPIC)
                    self._last_message_time = now

                if now - self._last_watchlist_refresh > 5:
                    self._refresh_watchlist()
                    self._last_watchlist_refresh = now

                if now >= next_snapshot:
                    self._update_snapshot()
                    next_snapshot = now + SNAPSHOT_INTERVAL_SEC

                self._flush_buffers_if_needed()
            except Exception as exc:
                logger.exception("Processor loop error: %s", exc)
                time.sleep(1)

    def _handle_raw_event(self, ev: dict) -> None:
        clean = _strip_additional_properties(ev)
        self._raw_buffer.append(clean)

        sym = clean.get("s")
        ts = clean.get("E")
        price = _parse_float(clean.get("c"))
        if sym is None or ts is None or price is None:
            return

        self._ticker_stats[sym] = {
            "h": _parse_float(clean.get("h")),
            "l": _parse_float(clean.get("l")),
            "o": _parse_float(clean.get("o")),
            "c": price,
        }

        if sym not in self._seeded:
            return

        closed, current = self._update_bar(sym, ts, price, _parse_float(clean.get("Q")) or 0.0)

        if closed:
            self._market_store.update_candle(sym, closed, is_new=True)
            self._bar_history.setdefault(sym, []).append(closed)
            self._process_bar(sym)
            self._market_store.update_candle(sym, current, is_new=True)
            self._live_initialized.add(sym)
        else:
            if sym not in self._live_initialized:
                self._market_store.update_candle(sym, current, is_new=True)
                self._live_initialized.add(sym)
            else:
                self._market_store.update_candle(sym, current, is_new=False)

    def _refresh_watchlist(self) -> None:
        if not self._ticker_stats:
            return
        scored: List[tuple[str, float]] = []
        for sym, stats in self._ticker_stats.items():
            high = stats.get("h")
            low = stats.get("l")
            if high is None or low is None or low <= 0:
                continue
            hl_diff = (high - low) / low
            scored.append((sym, hl_diff))
        scored.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [sym for sym, _ in scored[:5]]
        self._watchlist = set(top_symbols)

        for sym in top_symbols:
            if sym in self._seeded:
                continue
            self._seed_symbol(sym)

    def _seed_symbol(self, sym: str) -> None:
        stats = self._ticker_stats.get(sym)
        if stats is None:
            return
        end_time = int(time.time() * 1000) - 1
        candles = self._fetch_seed_candles(sym, end_time)
        if not candles:
            return
        history = self._bar_history.setdefault(sym, [])
        for candle in candles:
            history.append(candle)
            self._market_store.update_candle(sym, candle, is_new=True)
        if len(history) > CANDLE_COUNT:
            del history[:-CANDLE_COUNT]

        last_close = candles[-1].get("c")
        live_price = stats.get("c") if stats else None
        price = live_price if live_price is not None else last_close
        if price is None:
            return
        now_ms = int(time.time() * 1000)
        bucket = int(now_ms // BAR_INTERVAL_MS)
        live_state = BarState(bucket=bucket, o=price, h=price, l=price, c=price, v=0.0, ts=now_ms)
        self._bars[sym] = live_state
        live_candle = _state_to_candle(live_state)
        self._market_store.update_candle(sym, live_candle, is_new=True)
        self._live_initialized.add(sym)

        self._seeded.add(sym)

    def _fetch_seed_candles(self, sym: str, end_time_ms: int) -> List[dict]:
        try:
            params = {
                "symbol": sym,
                "interval": "1m",
                "limit": CANDLE_COUNT - 1,
                "endTime": end_time_ms,
            }
            resp = requests.get(REST_KLINES_URL, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            candles: List[dict] = []
            for entry in data:
                candles.append(
                    {
                        "t": int(entry[0]),
                        "o": float(entry[1]),
                        "h": float(entry[2]),
                        "l": float(entry[3]),
                        "c": float(entry[4]),
                        "v": float(entry[5]),
                    }
                )
            return candles
        except Exception as exc:
            logger.warning("Failed to seed candles for %s: %s", sym, exc)
            return []

    def _update_bar(self, sym: str, ts: int, price: float, qty: float) -> Tuple[Optional[dict], dict]:
        bucket = int(ts // BAR_INTERVAL_MS)
        state = self._bars.get(sym)
        if state is None:
            state = BarState(bucket=bucket, o=price, h=price, l=price, c=price, v=qty, ts=ts)
            self._bars[sym] = state
            return None, _state_to_candle(state)

        if bucket == state.bucket:
            state.h = max(state.h, price)
            state.l = min(state.l, price)
            state.c = price
            state.v += qty
            state.ts = ts
            return None, _state_to_candle(state)

        closed = _state_to_candle(state)
        new_state = BarState(bucket=bucket, o=price, h=price, l=price, c=price, v=qty, ts=ts)
        self._bars[sym] = new_state
        return closed, _state_to_candle(new_state)

    def _process_bar(self, sym: str) -> None:
        history = self._bar_history.get(sym, [])
        if not history:
            return

        df = pd.DataFrame(history)
        df.sort_values("t", inplace=True)
        df.reset_index(drop=True, inplace=True)

        df["rsi"] = ta.rsi(df["c"], length=14)
        macd = ta.macd(df["c"], fast=12, slow=26, signal=9)
        if macd is not None:
            df = pd.concat([df, macd], axis=1)
        df["atr"] = ta.atr(df["h"], df["l"], df["c"], length=14)

        latest = df.iloc[-1]
        processed = {
            "sym": sym,
            "t": int(latest["t"]),
            "o": _safe_float(latest.get("o")),
            "h": _safe_float(latest.get("h")),
            "l": _safe_float(latest.get("l")),
            "c": _safe_float(latest.get("c")),
            "v": _safe_float(latest.get("v")),
            "rsi": _safe_float(latest.get("RSI_14")),
            "macd": _safe_float(latest.get("MACD_12_26_9")),
            "macd_signal": _safe_float(latest.get("MACDs_12_26_9")),
            "macd_hist": _safe_float(latest.get("MACDh_12_26_9")),
            "atr": _safe_float(latest.get("ATRr_14")) or _safe_float(latest.get("ATR_14")),
        }

        self._processed_buffer.append(processed)
        self._producer.send(PROCESSED_TOPIC, key=sym, value=processed)

        if len(history) > CANDLE_COUNT:
            del history[:-CANDLE_COUNT]

    def _update_snapshot(self) -> None:
        now_ms = int(time.time() * 1000)
        snapshot = self._market_store.compute_snapshot(now_ms)
        with self._lock:
            self.latest_snapshot = snapshot

    def _flush_buffers_if_needed(self) -> None:
        now = time.monotonic()
        if (len(self._raw_buffer) >= RAW_FLUSH_SIZE) or (now - self._last_flush >= FLUSH_INTERVAL_SEC):
            if self._raw_buffer:
                _write_parquet(RAW_STORE_DIR, "raw", self._raw_buffer)
                self._raw_buffer = []
            if self._processed_buffer:
                _write_parquet(PROCESSED_STORE_DIR, "processed", self._processed_buffer)
                self._processed_buffer = []
            self._last_flush = now


def _state_to_candle(state: BarState) -> dict:
    return {
        "t": state.bucket * BAR_INTERVAL_MS,
        "o": state.o,
        "h": state.h,
        "l": state.l,
        "c": state.c,
        "v": state.v,
    }


def _write_parquet(base_dir: Path, prefix: str, records: List[dict]) -> None:
    if not records:
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    date_dir = base_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    path = date_dir / f"{prefix}_{timestamp}.parquet"
    df = pd.DataFrame(records)
    df.to_parquet(path, index=False)


def _parse_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        val = float(value)
        if pd.isna(val):
            return None
        return val
    except (TypeError, ValueError):
        return None


def _strip_additional_properties(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, val in value.items():
            if key == "additional_properties":
                continue
            cleaned[key] = _strip_additional_properties(val)
        return cleaned
    if isinstance(value, list):
        return [_strip_additional_properties(item) for item in value]
    return value
