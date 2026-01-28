from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd
import pandas_ta as ta
from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic

from ..config import (
    BAR_INTERVAL_SEC,
    FLUSH_INTERVAL_SEC,
    KAFKA_BROKER,
    MAX_SERIES_POINTS,
    PROCESSED_FLUSH_SIZE,
    PROCESSED_STORE_DIR,
    PROCESSED_TOPIC,
    PROCESSED_TOPIC_PARTITIONS,
    RAW_FLUSH_SIZE,
    RAW_STORE_DIR,
    RAW_TOPIC,
    RAW_TOPIC_PARTITIONS,
    SNAPSHOT_INTERVAL_SEC,
)
from .market_store import MarketStore

logger = logging.getLogger(__name__)

BAR_INTERVAL_MS = BAR_INTERVAL_SEC * 1000


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
        self._market_store.ingest([clean])
        closed_bar = self._update_bar(clean)
        if closed_bar:
            self._process_bar(closed_bar)

    def _update_bar(self, ev: dict) -> Optional[dict]:
        sym = ev.get("s")
        ts = ev.get("E")
        price = _parse_float(ev.get("c"))
        qty = _parse_float(ev.get("Q")) or 0.0
        if sym is None or ts is None or price is None:
            return None
        bucket = int(ts // BAR_INTERVAL_MS)
        state = self._bars.get(sym)
        if state is None:
            self._bars[sym] = BarState(bucket=bucket, o=price, h=price, l=price, c=price, v=qty, ts=ts)
            return None
        if bucket == state.bucket:
            state.h = max(state.h, price)
            state.l = min(state.l, price)
            state.c = price
            state.v += qty
            state.ts = ts
            return None

        closed = {
            "sym": sym,
            "t": state.bucket * BAR_INTERVAL_MS,
            "o": state.o,
            "h": state.h,
            "l": state.l,
            "c": state.c,
            "v": state.v,
        }
        self._bars[sym] = BarState(bucket=bucket, o=price, h=price, l=price, c=price, v=qty, ts=ts)
        return closed

    def _process_bar(self, bar: dict) -> None:
        sym = bar["sym"]
        history = self._bar_history.setdefault(sym, [])
        history.append(bar)
        if len(history) > 300:
            history.pop(0)

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
