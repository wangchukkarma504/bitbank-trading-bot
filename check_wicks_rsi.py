import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

pair = 'sol_jpy'
today = dt.datetime.now(dt.timezone.utc).date()

# 1hour candles
rows_1h = []
for d in (today - dt.timedelta(days=i) for i in (3, 2, 1, 0)):
    try:
        c = api.candles(pair, '1hour', d.strftime('%Y%m%d'))
        rows_1h += [(int(t), float(o), float(h), float(l), float(c), float(v)) for o, h, l, c, v, t in c]
    except Exception:
        pass
rows_1h.sort()
seen = set()
dedup_1h = []
for r in rows_1h:
    if r[0] not in seen:
        seen.add(r[0])
        dedup_1h.append(r)

closes_1h = [r[4] for r in dedup_1h]
rsi_1h = calc_rsi(closes_1h, 14)

print(f"=== {pair.upper()} WICK & RSI TECHNICAL ANALYSIS ===")
print(f"1h RSI (14): {rsi_1h:.1f}")

print("\nRecent 1h Candlestick Wick Analysis (Upper vs Lower Wicks):")
for r in dedup_1h[-8:]:
    t, o, h, l, c, v = r
    ts = dt.datetime.fromtimestamp(t/1000).strftime('%m-%d %H:%M')
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    wick_ratio = upper_wick / (body + 1e-5)
    bias = "BEARISH WICK (Rejection)" if upper_wick > body * 1.5 and upper_wick > lower_wick else ("BULLISH WICK (Absorption)" if lower_wick > body * 1.5 and lower_wick > upper_wick else "Neutral/Trend Body")
    print(f"{ts} | O:{o:.1f} H:{h:.1f} L:{l:.1f} C:{c:.1f} | UpWick:{upper_wick:.1f} LoWick:{lower_wick:.1f} Body:{body:.1f} -> {bias}")
