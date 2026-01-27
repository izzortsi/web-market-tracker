import asyncio
import json
import logging
from typing import Optional

import websockets

from ..config import STREAM_URL, RECONNECT_DELAY_SEC, PING_INTERVAL_SEC, PING_TIMEOUT_SEC
from .market_store import MarketStore

logger = logging.getLogger(__name__)


class BinanceTickerClient:
    def __init__(self, store: MarketStore) -> None:
        self.store = store
        self._stopped = False

    async def run(self) -> None:
        while not self._stopped:
            try:
                async with websockets.connect(
                    STREAM_URL,
                    ping_interval=PING_INTERVAL_SEC,
                    ping_timeout=PING_TIMEOUT_SEC,
                    max_queue=None,
                ) as ws:
                    async for message in ws:
                        try:
                            parsed = json.loads(message)
                        except json.JSONDecodeError:
                            continue
                        data = parsed.get("data")
                        if isinstance(data, list):
                            self.store.ingest(data)
            except Exception as exc:
                logger.warning("WebSocket error: %s", exc)
                await asyncio.sleep(RECONNECT_DELAY_SEC)

    def stop(self) -> None:
        self._stopped = True
