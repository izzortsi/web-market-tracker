from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class KeltnerResult:
    symbol: str
    basis: float
    atr: float
    multiples: Dict[float, Tuple[float, float]]


def _ema_series(values: List[float], length: int) -> List[float]:
    if not values:
        return []
    alpha = 2 / (length + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(alpha * v + (1 - alpha) * ema[-1])
    return ema


def _atr_series(highs: List[float], lows: List[float], closes: List[float], length: int) -> List[float]:
    trs: List[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return []
    alpha = 2 / (length + 1)
    atr = [sum(trs[:length]) / max(1, length)]
    for tr in trs[length:]:
        atr.append(alpha * tr + (1 - alpha) * atr[-1])
    return atr


def _compute_keltner(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    ema_len: int,
    atr_len: int,
    multiples: List[float],
) -> Optional[KeltnerResult]:
    if len(closes) < max(ema_len, atr_len) + 1:
        return None
    ema = _ema_series(closes, ema_len)
    atr = _atr_series(highs, lows, closes, atr_len)
    if not ema or not atr:
        return None
    basis = ema[-1]
    atr_val = atr[-1]
    bands: Dict[float, Tuple[float, float]] = {}
    for k in multiples:
        bands[float(k)] = (basis - k * atr_val, basis + k * atr_val)
    return KeltnerResult(symbol="", basis=basis, atr=atr_val, multiples=bands)


def _worker_loop(task_queue: mp.Queue, result_queue: mp.Queue) -> None:
    while True:
        task = task_queue.get()
        if task is None:
            break
        if not isinstance(task, dict):
            continue
        if task.get("type") != "keltner":
            continue
        symbol = task.get("symbol")
        closes = task.get("closes", [])
        highs = task.get("highs", [])
        lows = task.get("lows", [])
        ema_len = task.get("ema_len")
        atr_len = task.get("atr_len")
        multiples = task.get("multiples", [])
        result = _compute_keltner(closes, highs, lows, int(ema_len), int(atr_len), list(multiples))
        if result is None:
            continue
        result_queue.put(
            {
                "symbol": symbol,
                "basis": result.basis,
                "atr": result.atr,
                "multiples": result.multiples,
            }
        )


class ComputeWorker:
    def __init__(self, max_queue: int = 1000) -> None:
        ctx = mp.get_context("spawn")
        self._task_queue: mp.Queue = ctx.Queue(maxsize=max_queue)
        self._result_queue: mp.Queue = ctx.Queue()
        self._proc = ctx.Process(target=_worker_loop, args=(self._task_queue, self._result_queue), daemon=True)

    def start(self) -> None:
        if not self._proc.is_alive():
            self._proc.start()

    def stop(self) -> None:
        try:
            self._task_queue.put_nowait(None)
        except Exception:
            pass
        if self._proc.is_alive():
            self._proc.join(timeout=5)

    def submit_keltner(
        self,
        symbol: str,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        ema_len: int,
        atr_len: int,
        multiples: List[float],
    ) -> None:
        payload = {
            "type": "keltner",
            "symbol": symbol,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "ema_len": ema_len,
            "atr_len": atr_len,
            "multiples": multiples,
        }
        try:
            self._task_queue.put_nowait(payload)
        except Exception:
            return

    def drain_results(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        while True:
            try:
                res = self._result_queue.get_nowait()
            except Exception:
                break
            if isinstance(res, dict):
                results.append(res)
        return results
