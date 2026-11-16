import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def get_candles(pair, candle_type='1hour', days=4):
    today = dt.datetime.now(dt.timezone.utc).date()
    rows = []
    for d in (today - dt.timedelta(days=i) for i in range(days, -1, -1)):
        try:
            c = api.candles(pair, candle_type, d.strftime('%Y%m%d'))
            rows += [(int(t), float(o), float(h), float(l), float(c), float(v)) for o, h, l, c, v, t in c]
        except Exception:
            pass
    rows.sort()
    seen = set()
    dedup = []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            dedup.append(r)
    return dedup

def analyze_pair(pair):
    c_15m = get_candles(pair, '15min', days=1)
    c_1h = get_candles(pair, '1hour', days=4)
    c_4h = get_candles(pair, '4hour', days=14)

    rsi_15m = calc_rsi([r[4] for r in c_15m], 14) if len(c_15m) >= 15 else 50.0
    rsi_1h = calc_rsi([r[4] for r in c_1h], 14) if len(c_1h) >= 15 else 50.0
    rsi_4h = calc_rsi([r[4] for r in c_4h], 14) if len(c_4h) >= 15 else 50.0

    print(f"\n=======================================================")
    print(f"PAIR: {pair.upper()} | RSI -> 15m: {rsi_15m:.1f} | 1h: {rsi_1h:.1f} | 4h: {rsi_4h:.1f}")
    print(f"=======================================================")

    print("--- 1H RECENT CANDLESTICKS & WICK STRUCTURE ---")
    for r in c_1h[-6:]:
        t, o, h, l, c, v = r
        ts = dt.datetime.fromtimestamp(t/1000).strftime('%m-%d %H:%M')
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        
        # Classification
        if upper_wick > body * 1.8 and upper_wick > lower_wick * 1.5:
            wick_type = "BEARISH REJECTION WICK (Sellers Swept Liquidity / Capped High)"
        elif lower_wick > body * 1.8 and lower_wick > upper_wick * 1.5:
            wick_type = "BULLISH ABSORPTION WICK (Buyers Defending Dip)"
        elif upper_wick > body * 1.0 and lower_wick > body * 1.0:
            wick_type = "INDECISION / SPINNING TOP (Two-Way Wick Squeeze)"
        elif body > (upper_wick + lower_wick) * 1.5:
            wick_type = "STRONG MOMENTUM BODY"
        else:
            wick_type = "CONSOLIDATION"
            
        print(f"[{ts}] O:{o:10.3f} H:{h:10.3f} L:{l:10.3f} C:{c:10.3f} | UpWick:{upper_wick:7.3f} LoWick:{lower_wick:7.3f} | {wick_type}")

    # 15m latest candle check
    if c_15m:
        last_15 = c_15m[-1]
        t, o, h, l, c, v = last_15
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        ts = dt.datetime.fromtimestamp(t/1000).strftime('%H:%M')
        print(f"Latest 15m Candle ({ts}): C={c:.3f}, UpWick={upper_wick:.3f}, LoWick={lower_wick:.3f}")

for p in ['doge_jpy', 'sol_jpy', 'xrp_jpy', 'btc_jpy']:
    analyze_pair(p)
