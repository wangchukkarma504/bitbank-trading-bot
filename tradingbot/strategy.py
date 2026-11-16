"""Long-only trend following: EMA cross + trend filter, ATR chandelier trailing stop."""
from dataclasses import dataclass


def ema(vals, n):
    k = 2 / (n + 1)
    out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def atr(c, n):
    trs, prev = [], None
    for _, o, h, l, cl, _v in c:
        tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        trs.append(tr)
        prev = cl
    return ema(trs, n)


@dataclass
class Params:
    fast: int = 20
    slow: int = 60
    trend: int = 200
    atr_n: int = 14
    stop_atr: float = 3.0   # trailing stop distance in ATRs
    risk: float = 0.5       # fraction of equity committed per position (spot, no leverage)


class Signals:
    """Computes indicators over candle list; evaluate at index i (closed candle)."""

    def __init__(self, candles, p: Params):
        self.p = p
        closes = [x[4] for x in candles]
        self.f = ema(closes, p.fast)
        self.s = ema(closes, p.slow)
        self.t = ema(closes, p.trend)
        self.a = atr(candles, p.atr_n)
        self.c = closes

    def warm(self, i):
        return i >= self.p.trend

    def entry(self, i):
        return self.warm(i) and self.f[i] > self.s[i] and self.c[i] > self.t[i] and self.s[i] > self.s[i - 3]

    def stop_level(self, i, high_since_entry):
        return high_since_entry - self.p.stop_atr * self.a[i]

    def exit_trend(self, i):
        return self.f[i] < self.s[i]
