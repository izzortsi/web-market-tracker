#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import requests

BASE = "http://localhost:8000"


def fetch(path: str):
    url = f"{BASE}{path}"
    resp = requests.get(url, timeout=10)
    return resp.status_code, resp.json()


def main() -> int:
    print("Smoke test against", BASE)

    status, data = fetch("/api/global/metrics")
    print("/api/global/metrics", status, "series_len=", len(data.get("series", [])))

    status, data = fetch("/api/screener/promoted")
    promoted = data.get("promoted", [])
    print("/api/screener/promoted", status, "promoted=", promoted)

    if promoted:
        sym = promoted[0]
        status, data = fetch(f"/api/symbols/{sym}")
        print(f"/api/symbols/{sym}", status, "keys=", list(data.keys())[:6])
    else:
        print("No promoted symbols to query /api/symbols/{symbol}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
