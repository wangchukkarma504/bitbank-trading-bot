"""Daily auto-tuner: re-learns frequent mode's entry and stop settings from recent market data.

A single live trade says almost nothing, but two months of 5-minute candles on five coins contain hundreds
of would-be trades. Once a day the tuner replays that history for a small grid of settings, with the same
rules the live bot uses (near-market maker entry, stop beyond the recent swing, profit-lock trail, real
fees, one position at a time), and adopts a new setting only if it

  1. trades at least `min_trades_per_day` in the training window,
  2. has the best total result there, and
  3. also beats the setting currently in use on the most recent days, which it was NOT chosen on.

Otherwise it keeps what it has. Settings only ever come from the grid below, so the tuner cannot wander
into untested territory. Candles come from Bitbank's public API and are cached on disk.
"""

from datetime import datetime, timedelta, timezone
import itertools
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("AutoTuner")

PUBLIC = "https://public.bitbank.cc"
PAIRS = ("btc_jpy", "eth_jpy", "xrp_jpy", "sol_jpy", "doge_jpy")

DEFAULT_PARAMS: Dict[str, Any] = {
    "short_rsi_min": 60.0, "long_rsi_max": 40.0, "require_1h": False,
    "trail_arm_pct": 0.0060, "trail_dist_pct": 0.0050,
}
GRID: Dict[str, List[Any]] = {
    "short_rsi_min": [55.0, 60.0, 65.0],
    "require_1h": [False, True],
    "trail_arm_pct": [0.0035, 0.0060, 0.0090],
    "trail_dist_pct": [0.0040, 0.0050, 0.0070],
}
# Fixed parts of the live rule set (kept in step with DirectionalStrategist / TradingOrchestrator)
ENTRY_OFFSET = 0.0008
SWING_BARS_5M = 24
SWING_BUFFER = 0.0015
MIN_STOP, MAX_STOP = 0.004, 0.012
TRAIL_LOCK = 0.0020
STOP_COST = 0.0012 + 0.0003 - 0.0002   # taker stop fee + slippage - maker entry rebate
Bar = Tuple[int, float, float, float, float]  # ts_ms, open, high, low, close


def _ema(prev: Optional[float], value: float, period: int) -> float:
    k = 2.0 / (period + 1)
    return value if prev is None else value * k + prev * (1 - k)


def fetch_rows(pair: str, tf: str, day: str, cache_dir: str, session: requests.Session) -> List[list]:
    """One day (or year, for 4hour) of candles, cached on disk once that period is over."""
    path = os.path.join(cache_dir, f"{pair}_{tf}_{day}.json")
    now = datetime.now(timezone.utc)
    current = day in (now.strftime("%Y%m%d"), now.strftime("%Y"))
    if os.path.exists(path) and not current:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    for attempt in range(3):
        try:
            d = session.get(f"{PUBLIC}/{pair}/candlestick/{tf}/{day}", timeout=20).json()
            if d.get("success") == 1:
                rows = d["data"]["candlestick"][0]["ohlcv"]
                if not current:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(rows, f)
                time.sleep(0.25)  # stay far below the public rate limit; the live bot shares it
                return rows
        except Exception:
            pass
        time.sleep(1.0 + attempt)
    return []


def load_history(pair: str, days: int, cache_dir: str) -> Tuple[List[Bar], List[Tuple[int, float]]]:
    os.makedirs(cache_dir, exist_ok=True)
    session = requests.Session()
    now = datetime.now(timezone.utc)
    rows: List[list] = []
    for d in range(days, -1, -1):
        rows += fetch_rows(pair, "5min", (now - timedelta(days=d)).strftime("%Y%m%d"), cache_dir, session)
    m5 = sorted({int(r[5]): (int(r[5]), float(r[0]), float(r[1]), float(r[2]), float(r[3])) for r in rows}.values())
    h4: List[list] = []
    for year in (now.year - 1, now.year):
        h4 += fetch_rows(pair, "4hour", str(year), cache_dir, session)
    h4c = sorted({int(r[5]): (int(r[5]), float(r[3])) for r in h4}.values())
    return m5, h4c


def _aggregate(m5: List[Bar], seconds: int) -> List[Tuple[int, float]]:
    """(bucket start ms, close) for a higher timeframe built from 5m bars."""
    out: Dict[int, float] = {}
    for ts, _, _, _, c in m5:
        out[ts // (seconds * 1000) * seconds * 1000] = c
    return sorted(out.items())


def build_features(m5: List[Bar], h4: List[Tuple[int, float]]) -> List[Tuple[int, float, float, bool, bool, int]]:
    """Per closed 15m bar: (close_ts, close, rsi14, h4_bear, h1_down, index of the next 5m bar)."""
    idx5 = {b[0]: i for i, b in enumerate(m5)}
    h1: List[Tuple[int, bool]] = []
    e20 = e50 = None
    for ts, c in _aggregate(m5, 3600):
        e20, e50 = _ema(e20, c, 20), _ema(e50, c, 50)
        h1.append((ts + 3600_000, e20 < e50))
    h4a: List[Tuple[int, bool]] = []
    e200 = None
    for ts, c in h4:
        e200 = _ema(e200, c, 200)
        h4a.append((ts + 14400_000, c < e200))
    feats = []
    ag = al = prev = None
    i1 = i4 = 0
    for n, (ts, c) in enumerate(_aggregate(m5, 900)):
        if prev is not None:
            ch = c - prev
            up, dn = max(ch, 0.0), max(-ch, 0.0)
            ag = up if ag is None else (ag * 13 + up) / 14
            al = dn if al is None else (al * 13 + dn) / 14
        prev = c
        close_ts = ts + 900_000
        while i1 + 1 < len(h1) and h1[i1 + 1][0] <= close_ts:
            i1 += 1
        while i4 + 1 < len(h4a) and h4a[i4 + 1][0] <= close_ts:
            i4 += 1
        if n < 60 or al is None or not h1 or not h4a or h1[i1][0] > close_ts or h4a[i4][0] > close_ts or close_ts not in idx5:
            continue
        rsi = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
        feats.append((close_ts, c, rsi, h4a[i4][1], h1[i1][1], idx5[close_ts]))
    return feats


def simulate_pair(m5: List[Bar], feats: List[tuple], params: Dict[str, Any]) -> List[Tuple[int, int, float]]:
    """Would-be trades for one pair as (entry_ts, exit_ts, result as a fraction of position size)."""
    trades: List[Tuple[int, int, float]] = []
    busy_until = 0
    arm, dist = params["trail_arm_pct"], params["trail_dist_pct"]
    for ts, close, rsi, h4_bear, h1_down, i in feats:
        if ts < busy_until:
            continue
        if h4_bear and rsi >= params["short_rsi_min"] and (h1_down or not params["require_1h"]):
            side, sgn, px = "short", -1, close * (1 + ENTRY_OFFSET)
        elif (not h4_bear) and rsi <= params["long_rsi_max"] and ((not h1_down) or not params["require_1h"]):
            side, sgn, px = "long", 1, close * (1 - ENTRY_OFFSET)
        else:
            continue
        filled = None
        for j in range(i, min(i + 6, len(m5))):  # the entry order rests for up to 30 minutes
            if (side == "short" and m5[j][2] >= px) or (side == "long" and m5[j][3] <= px):
                filled = j
                break
        if filled is None:
            busy_until = ts + 1800_000
            continue
        window = m5[max(0, filled - SWING_BARS_5M):filled + 1]
        if side == "short":
            sl = (max(b[2] for b in window) * (1 + SWING_BUFFER) - px) / px
        else:
            sl = (px - min(b[3] for b in window) * (1 - SWING_BUFFER)) / px
        stop_gain, peak, result, j = -min(MAX_STOP, max(MIN_STOP, sl)), 0.0, None, filled
        for j in range(filled, len(m5)):
            _, _, hi, lo, cl = m5[j]
            adverse = sgn * ((hi if side == "short" else lo) - px) / px
            favour = sgn * ((lo if side == "short" else hi) - px) / px
            if j == filled:
                favour = min(favour, sgn * (cl - px) / px)
            if adverse <= stop_gain:  # pessimistic: within a bar the adverse extreme is assumed to come first
                result = stop_gain - STOP_COST
                break
            peak = max(peak, favour)
            if peak >= arm:
                stop_gain = max(stop_gain, TRAIL_LOCK, peak - dist)
        if result is None:
            break  # still open at the end of the data
        trades.append((m5[filled][0], m5[j][0], result))
        busy_until = m5[j][0] + 900_000
    return trades


def portfolio(per_pair: List[List[Tuple[int, int, float]]], start_ms: int, end_ms: int) -> Tuple[int, float]:
    """Take trades in time order with one position open at a time. Returns (count, summed result)."""
    count, total, free_at = 0, 0.0, 0
    for entry, exit_, res in sorted(t for trades in per_pair for t in trades):
        if entry < start_ms or entry >= end_ms or entry < free_at:
            continue
        count, total, free_at = count + 1, total + res, exit_ + 120_000
    return count, total


class AutoTuner:
    def __init__(self, state_path: Optional[str] = None, cache_dir: str = "candle_cache",
                 history_days: int = 60, check_days: int = 14, min_trades_per_day: float = 3.0):
        self.state_path = state_path
        self.cache_dir = cache_dir
        self.history_days = history_days
        self.check_days = check_days
        self.min_trades_per_day = min_trades_per_day
        self.params: Dict[str, Any] = dict(DEFAULT_PARAMS)
        self.last_run_ts: float = 0.0
        self.last_report: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = data.get("params", {})
            if all(loaded.get(k) in GRID[k] for k in GRID):  # only accept values the grid could have produced
                self.params.update({k: loaded[k] for k in GRID})
                self.params["long_rsi_max"] = 100.0 - self.params["short_rsi_min"]
            self.last_run_ts = float(data.get("last_run_ts", 0.0))
            self.last_report = data.get("last_report", {})
        except Exception as e:
            logger.warning(f"Could not load tuner state from {self.state_path}: {e}")

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"params": self.params, "last_run_ts": self.last_run_ts, "last_report": self.last_report}, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save tuner state to {self.state_path}: {e}")

    def due(self, now_ts: Optional[float] = None, every_sec: float = 24 * 3600.0) -> bool:
        return ((now_ts if now_ts is not None else time.time()) - self.last_run_ts) >= every_sec

    def tune(self, history: Optional[Dict[str, Tuple[List[Bar], List[Tuple[int, float]]]]] = None,
             now_ms: Optional[int] = None, pause: Callable[[], None] = lambda: time.sleep(0.01)) -> Dict[str, Any]:
        """Run one tuning pass. `history` and `now_ms` are injectable for tests."""
        if history is None:
            history = {p: load_history(p, self.history_days, self.cache_dir) for p in PAIRS}
        feats = {p: build_features(m5, h4) for p, (m5, h4) in history.items()}
        ends = [m5[-1][0] for m5, _ in history.values() if m5]
        if not ends or not any(feats.values()):
            report = {"status": "no data", "changed": False}
            self.last_report = report
            return report
        end_ms = now_ms or max(ends)
        check_start = end_ms - self.check_days * 86400_000
        train_start = end_ms - self.history_days * 86400_000
        train_days = max(1.0, (check_start - train_start) / 86400_000)

        def evaluate(params: Dict[str, Any]) -> Tuple[Tuple[int, float], Tuple[int, float]]:
            per_pair = [simulate_pair(history[p][0], feats[p], params) for p in history]
            pause()
            return portfolio(per_pair, train_start, check_start), portfolio(per_pair, check_start, end_ms + 1)

        current = dict(self.params)
        cur_train, cur_check = evaluate(current)
        best, best_train, best_check = None, None, None
        for values in itertools.product(*GRID.values()):
            cand = dict(zip(GRID.keys(), values))
            cand["long_rsi_max"] = 100.0 - cand["short_rsi_min"]
            train, check = evaluate(cand)
            if train[0] / train_days < self.min_trades_per_day:
                continue
            if best_train is None or train[1] > best_train[1]:
                best, best_train, best_check = cand, train, check

        changed = False
        reason = "no setting met the trades-per-day target; kept current"
        if best is not None:
            same = all(best[k] == current.get(k) for k in GRID)
            if same:
                reason = "current setting is still the best in training"
            elif best_check[1] > cur_check[1]:
                self.params.update(best)
                changed = True
                reason = "new setting was best in training and also beat the current one on the unseen recent days"
            else:
                reason = "best training setting did not beat the current one on the unseen recent days; kept current"
        self.last_run_ts = time.time()
        report = {
            "status": "ok", "changed": changed, "reason": reason, "params": dict(self.params),
            "train_days": round(train_days, 1), "check_days": self.check_days,
            "current_train": {"trades": cur_train[0], "total_pct": round(cur_train[1] * 100, 2)},
            "current_check": {"trades": cur_check[0], "total_pct": round(cur_check[1] * 100, 2)},
            "best_train": None if best_train is None else {"trades": best_train[0], "total_pct": round(best_train[1] * 100, 2)},
            "best_check": None if best_check is None else {"trades": best_check[0], "total_pct": round(best_check[1] * 100, 2)},
            "ran_at": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST"),
        }
        self.last_report = report
        self._save()
        return report
