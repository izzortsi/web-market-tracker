import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI

from .api.routes import router
from .config import MARKET_CAPS_PATH, SNAPSHOT_INTERVAL_SEC
from .services.binance_client import BinanceTickerClient
from .services.market_store import MarketStore

app = FastAPI()
app.include_router(router)


def _load_cap_ranks(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


async def _snapshot_loop(app_instance: FastAPI) -> None:
    while True:
        store: MarketStore = app_instance.state.store
        if store.has_data():
            now = int(time.time() * 1000)
            app_instance.state.latest_snapshot = store.compute_snapshot(now)
        else:
            app_instance.state.latest_snapshot = None
        await asyncio.sleep(SNAPSHOT_INTERVAL_SEC)


@app.on_event("startup")
async def on_startup() -> None:
    cap_ranks = _load_cap_ranks(MARKET_CAPS_PATH)
    store = MarketStore(cap_ranks)
    client = BinanceTickerClient(store)

    app.state.store = store
    app.state.client = client
    app.state.latest_snapshot = None

    asyncio.create_task(client.run())
    asyncio.create_task(_snapshot_loop(app))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    client = getattr(app.state, "client", None)
    if client:
        client.stop()
