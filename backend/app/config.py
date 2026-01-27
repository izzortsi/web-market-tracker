from pathlib import Path

STREAM_URL = "wss://fstream.binance.com/stream?streams=!ticker@arr"

RECONNECT_DELAY_SEC = 3
PING_INTERVAL_SEC = 20
PING_TIMEOUT_SEC = 10

SNAPSHOT_INTERVAL_SEC = 1.0
RING_SIZE = 500
MAX_SERIES_POINTS = 300

DATA_DIR = Path(__file__).resolve().parent / "data"
MARKET_CAPS_PATH = DATA_DIR / "market_caps.json"
