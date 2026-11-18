"""Replay of the trading rule on Bitbank history, through the same strategy.py the live engine uses.

    python3 -m tradingbot.backtest                 # every year available, 4h candles
    python3 -m tradingbot.backtest --fine 500      # last 500 days replayed on 5-minute candles
    python3 -m tradingbot.backtest --json out.json # also write trades and the equity curve

Assumptions, all on the cautious side: signals are read at a 4h close and acted on afterwards; inside a
candle the low is taken before the high; a candle that opens below the stop fills at the open; the taker
fee plus slippage is charged on market and stop fills, and margin interest for every started day. With
5-minute candles the entry first rests as a maker order for Params.maker_wait_sec (a touch is not a fill).

Candles come from Bitbank's public API and are cached in candle_cache/.
"""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from tradingbot import strategy
from tradingbot.strategy import BAR_MS, FEE_MAKER, FEE_TAKER, INTEREST_PER_DAY, Bar, Params, Snapshot

PUBLIC = "https://public.bitbank.cc"
PAIRS = ("btc_jpy", "eth_jpy", "xrp_jpy", "sol_jpy", "doge_jpy")
M5 = 300_000
DAY = 86_400_000
JST = timezone(timedelta(hours=9))


# ----------------------------------------------------------------------------- data

def fetch_rows(pair: str, tf: str, period: str, cache_dir: str, session: Optional[requests.Session] = None,
               allow_network: bool = True) -> List[list]:
    """Candles for one day (5min) or one year (4hour) as [o, h, l, c, v, ts] rows. Finished periods are cached."""
    path = os.path.join(cache_dir, f"{pair}_{tf}_{period}.json")
    now = datetime.now(timezone.utc)
    current = period in (now.strftime("%Y%m%d"), now.strftime("%Y"))
    if os.path.exists(path) and (not current or not allow_network):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if not allow_network:
        return []
    session = session or requests.Session()
    for attempt in range(4):
        try:
            d = session.get(f"{PUBLIC}/{pair}/candlestick/{tf}/{period}", timeout=20).json()
            if d.get("success") == 1:
                rows = d["data"]["candlestick"][0]["ohlcv"]
                os.makedirs(cache_dir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(rows, f)
                time.sleep(0.15)
                return rows
            if d.get("data", {}).get("code") == 10000:   # nothing for that period (pair not listed yet)
                return []
        except Exception:
            pass
        time.sleep(1.0 + attempt)
    return []


def to_bars(rows: Sequence[list]) -> List[Bar]:
    return sorted({int(r[5]): (int(r[5]), float(r[0]), float(r[1]), float(r[2]), float(r[3])) for r in rows}.values())


def load_4h(pair: str, cache_dir: str = "candle_cache", first_year: int = 2017, allow_network: bool = True) -> List[Bar]:
    session = requests.Session()
    rows: List[list] = []
    for year in range(first_year, datetime.now(timezone.utc).year + 1):
        rows += fetch_rows(pair, "4hour", str(year), cache_dir, session, allow_network)
    return to_bars(rows)


def load_5m(pair: str, days: int, cache_dir: str = "candle_cache", allow_network: bool = True) -> List[Bar]:
    session = requests.Session()
    end = datetime.now(timezone.utc) - timedelta(days=1)
    rows: List[list] = []
    for d in range(days, -1, -1):
        rows += fetch_rows(pair, "5min", (end - timedelta(days=d)).strftime("%Y%m%d"), cache_dir, session, allow_network)
    return to_bars(rows)


# ----------------------------------------------------------------------------- replay

@dataclass
class Trade:
    pair: str
    signal_ts: int
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    dist: float       # initial stop distance as a share of the signal price
    result: float     # net result as a share of the position's value
    maker: bool       # entered with the resting maker order

    @property
    def r(self) -> float:
        """Result in units of the amount risked (1.0 = made what the stop would have lost)."""
        return self.result / self.dist


def replay(bars_4h: Dict[str, List[Bar]], p: Params, start_ms: int, end_ms: int,
           fine: Optional[Dict[str, List[Bar]]] = None, slip: float = 0.0005,
           interest: float = INTEREST_PER_DAY) -> List[Trade]:
    """Replay [start_ms, end_ms). With `fine` (5-minute candles per pair) fills and stops use those candles
    and the maker-first entry; without it everything runs on the 4h candles with market entries."""
    snaps: Dict[str, Dict[int, Snapshot]] = {
        pair: {s.ts: s for s in strategy.snapshots(bars, p)} for pair, bars in bars_4h.items()}
    series = fine if fine is not None else bars_4h
    step = M5 if fine is not None else BAR_MS
    index = {pair: {b[0]: b for b in bars} for pair, bars in series.items()}
    trades: List[Trade] = []
    pending: Dict[str, dict] = {}
    open_: Dict[str, dict] = {}
    t = start_ms // step * step
    while t < end_ms:
        if t % BAR_MS == 0 and len(open_) + len(pending) < p.max_positions:
            found = []
            for pair in bars_4h:
                s = snaps[pair].get(t)
                if s is not None and pair not in open_ and pair not in pending and strategy.signal(s, p):
                    found.append((-s.momentum, pair, s))
            for _, pair, s in sorted(found)[:p.max_positions - len(open_) - len(pending)]:
                pending[pair] = {"plan": strategy.make_plan(s, p), "ts": t}
        for pair in list(pending):
            bar = index[pair].get(t)
            if bar is None:
                continue
            pe = pending.pop(pair)
            plan = pe["plan"]
            _, o, h, l, c = bar
            if fine is not None and t < pe["ts"] + p.maker_wait_sec * 1000:
                if l < plan.entry:      # the resting buy at the signal price was traded through
                    open_[pair] = _opened(pe, t, plan.entry, True, FEE_MAKER)
                else:
                    pending[pair] = pe
                    continue
            else:                       # not filled in time (or 4h mode): buy at market
                open_[pair] = _opened(pe, t, o, False, FEE_TAKER + slip)
            open_[pair]["fresh"] = True
        for pair in list(open_):
            bar = index[pair].get(t)
            if bar is None:
                continue
            ps = open_[pair]
            _, o, h, l, c = bar
            fresh = ps.pop("fresh", False)
            exit_px = None
            if not fresh and o <= ps["stop"]:
                exit_px = o                       # gapped through the stop
            elif l <= ps["stop"]:
                exit_px = ps["stop"]
            if exit_px is None:
                ps["best"] = max(ps["best"], c if fresh else h)   # in the entry candle only the close is safe
                ps["stop"] = strategy.trailing_stop(ps["entry"], ps["plan"].dist, ps["best"], ps["stop"])
                continue
            days = math.ceil((t + step - ps["entry_ts"]) / DAY)
            net = (exit_px - ps["entry"]) / ps["entry"] - ps["fee"] - (FEE_TAKER + slip) - days * interest
            trades.append(Trade(pair, ps["signal_ts"], ps["entry_ts"], t + step, ps["entry"], exit_px,
                                ps["plan"].dist, net, ps["maker"]))
            del open_[pair]
        t += step
    return trades


def _opened(pe: dict, t: int, price: float, maker: bool, fee: float) -> dict:
    return {"plan": pe["plan"], "signal_ts": pe["ts"], "entry_ts": t, "entry": price, "best": price,
            "stop": pe["plan"].stop, "maker": maker, "fee": fee}


# ----------------------------------------------------------------------------- reporting

def equity_curve(trades: List[Trade], p: Params) -> List[Tuple[int, float]]:
    """Equity (starting at 1.0) after each closed trade, compounding with the rule's position sizing."""
    eq, out = 1.0, []
    for t in sorted(trades, key=lambda x: x.exit_ts):
        eq *= 1.0 + strategy.notional_share(t.dist, p) * t.result
        out.append((t.exit_ts, eq))
    return out


def summary(trades: List[Trade], p: Params, start_ms: int, end_ms: int) -> Dict[str, float]:
    n = len(trades)
    years = max((end_ms - start_ms) / DAY / 365.25, 1e-9)
    if n < 2:
        return {"trades": n, "per_year": n / years, "win": 0.0, "avg_r": 0.0, "total_r": 0.0, "t": 0.0,
                "cagr": 0.0, "max_dd": 0.0, "final": 1.0}
    rs = [t.r for t in trades]
    mean = sum(rs) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1))
    curve = equity_curve(trades, p)
    peak, dd = 1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        dd = max(dd, 1.0 - eq / peak)
    final = curve[-1][1]
    return {"trades": n, "per_year": n / years, "win": sum(1 for r in rs if r > 0) / n, "avg_r": mean,
            "total_r": sum(rs), "t": mean / (sd / math.sqrt(n)) if sd > 0 else 0.0,
            "cagr": final ** (1.0 / years) - 1.0, "max_dd": dd, "final": final}


def fmt(name: str, s: Dict[str, float]) -> str:
    return (f"{name:22s} trades={s['trades']:4d} ({s['per_year']:4.1f}/yr) win={s['win'] * 100:4.1f}% "
            f"avg={s['avg_r']:+.3f}R total={s['total_r']:+6.1f}R t={s['t']:+.2f} "
            f"growth/yr={s['cagr'] * 100:+6.1f}% maxDD={s['max_dd'] * 100:4.1f}%")


def by_year(trades: List[Trade]) -> Dict[int, Tuple[int, float]]:
    out: Dict[int, Tuple[int, float]] = {}
    for t in trades:
        y = datetime.fromtimestamp(t.entry_ts / 1000, JST).year
        n, tot = out.get(y, (0, 0.0))
        out[y] = (n + 1, tot + t.r)
    return dict(sorted(out.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay the trading rule on Bitbank history")
    ap.add_argument("--cache", default="candle_cache")
    ap.add_argument("--fine", type=int, metavar="DAYS", help="replay the last DAYS days on 5-minute candles")
    ap.add_argument("--from", dest="start", metavar="YYYY-MM-DD", help="start of the replay (4h mode)")
    ap.add_argument("--risk", type=float, help="risk per trade as a share of equity (default from Params)")
    ap.add_argument("--offline", action="store_true", help="use cached candles only")
    ap.add_argument("--json", help="write trades and the equity curve to this file")
    args = ap.parse_args()
    p = Params() if args.risk is None else Params(risk_per_trade=args.risk)
    net = not args.offline
    bars = {pair: load_4h(pair, args.cache, allow_network=net) for pair in PAIRS}
    end = max(b[-1][0] for b in bars.values()) + BAR_MS
    fine = None
    if args.fine:
        fine = {pair: load_5m(pair, args.fine, args.cache, allow_network=net) for pair in PAIRS}
        start = min(b[0][0] for b in fine.values())
    elif args.start:
        start = int(datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=JST).timestamp() * 1000)
    else:
        start = min(b[0][0] for b in bars.values())
    trades = replay(bars, p, start, end, fine)
    print(f"{datetime.fromtimestamp(start / 1000, JST):%Y-%m-%d} to {datetime.fromtimestamp(end / 1000, JST):%Y-%m-%d}, "
          f"{'5-minute' if fine else '4-hour'} candles, {len(PAIRS)} coins, up to {p.max_positions} positions, "
          f"risk {p.risk_per_trade * 100:.0f}% of equity per trade. R = result / amount risked.")
    print(fmt("all", summary(trades, p, start, end)))
    for y, (n, tot) in by_year(trades).items():
        print(f"  {y}  trades={n:3d}  total={tot:+6.1f}R")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"params": asdict(p), "start": start, "end": end, "summary": summary(trades, p, start, end),
                       "trades": [dict(asdict(t), r=t.r) for t in trades],
                       "equity": equity_curve(trades, p)}, f)


if __name__ == "__main__":
    main()
