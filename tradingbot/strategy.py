"""The trading rule, as pure functions.

The live engine (engine.py) and the backtester (backtest.py) both go through this module to decide when
to buy, how much, and where the stop sits, so what is tested is what trades.

The rule, on 4-hour candles:

  * BUY a coin when a 4h candle closes above the highest high of the previous 120 candles (20 days).
  * STOP 3 x ATR below the entry. The stop then follows the best price at that same distance and never
    moves down, so losers are cut small and winners run until the trend turns.
  * SIZE each trade so that hitting the initial stop costs 2% of equity; hold at most 3 coins at once.

It is long-only. Selling breakdowns, and the earlier "sell the rally in a downtrend" rule, did not hold
up on years of Bitbank history (see README, "Evidence"); buying breakouts did, in every year 2017-2026.
"""

from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

FEE_MAKER = -0.0002     # Bitbank pays makers 0.02%
FEE_TAKER = 0.0012      # and charges takers 0.12% (market and stop orders)
INTEREST_PER_DAY = 0.0004   # margin interest on an open position, per started day
BAR_MS = 14_400_000     # the rule reads 4-hour candles

Bar = Tuple[int, float, float, float, float]   # open time (ms), open, high, low, close


@dataclass(frozen=True)
class Params:
    channel_bars: int = 120       # breakout level: highest high of this many previous 4h candles
    atr_bars: int = 14
    atr_mult: float = 3.0         # stop distance, and trailing distance, in ATRs
    min_stop: float = 0.015       # the stop is never closer than 1.5% ...
    max_stop: float = 0.15        # ... nor further than 15% from the entry
    max_positions: int = 3
    risk_per_trade: float = 0.02  # share of equity lost when a trade hits its initial stop
    max_notional: float = 0.65    # largest single position, as a multiple of equity (3 x 0.65 = 1.95x)
    maker_wait_sec: int = 600     # rest a maker buy at the signal price this long, then buy at market
    momentum_bars: int = 42       # 7 days; ranks coins when more break out than there are free slots


@dataclass(frozen=True)
class Snapshot:
    """What the rule looks at for one coin, taken at the close of a 4h candle."""
    ts: int               # close time of that candle, ms
    close: float
    channel_high: float   # highest high of the channel_bars candles before it
    atr: float            # average true range as a share of the close
    momentum: float       # close versus momentum_bars candles earlier


@dataclass(frozen=True)
class Plan:
    entry: float   # reference price: the signal candle's close
    stop: float    # initial stop price
    dist: float    # stop distance as a share of the entry; the stop trails this far behind the best price


def snapshots(bars: Sequence[Bar], p: Params) -> List[Snapshot]:
    """One snapshot per closed candle, starting once there is enough history for the channel and the ATR."""
    out: List[Snapshot] = []
    highs: deque = deque(maxlen=p.channel_bars)
    closes: deque = deque(maxlen=p.momentum_bars + 1)
    atr = prev_close = None
    warmup = p.channel_bars + 5 * p.atr_bars
    for i, (ts, _o, h, l, c) in enumerate(bars):
        tr = (h - l) if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close))
        atr = tr if atr is None else (atr * (p.atr_bars - 1) + tr) / p.atr_bars
        closes.append(c)
        if i >= warmup and c > 0:
            out.append(Snapshot(ts + BAR_MS, c, max(highs), atr / c, c / closes[0] - 1.0))
        highs.append(h)          # after the snapshot: the channel never includes the candle being judged
        prev_close = c
    return out


def signal(s: Snapshot, p: Params) -> bool:
    """True when this candle closed above the breakout level."""
    return s.close > s.channel_high


def stop_distance(s: Snapshot, p: Params) -> float:
    return min(p.max_stop, max(p.min_stop, p.atr_mult * s.atr))


def make_plan(s: Snapshot, p: Params) -> Plan:
    d = stop_distance(s, p)
    return Plan(s.close, s.close * (1.0 - d), d)


def notional_share(dist: float, p: Params) -> float:
    """Position value as a multiple of equity: sized by risk, capped by max_notional."""
    return min(p.risk_per_trade / dist, p.max_notional)


def trailing_stop(entry: float, dist: float, best_price: float, current_stop: float) -> float:
    """Stop price for a long whose best price since entry is best_price. Never lower than current_stop."""
    return max(current_stop, best_price - dist * entry)


def checks(s: Snapshot, p: Params) -> List[Tuple[str, bool]]:
    """The rule's condition and whether it holds, in words (shown on the dashboard)."""
    gap = (s.channel_high / s.close - 1.0) * 100.0
    days = p.channel_bars * BAR_MS // 86_400_000
    if s.close > s.channel_high:
        return [(f"4h close {s.close:g} is above the {days}-day high {s.channel_high:g}", True)]
    return [(f"4h close {s.close:g} is {gap:.1f}% below the {days}-day high {s.channel_high:g}", False)]
