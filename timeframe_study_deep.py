import datetime as dt
from tradingbot.bitbank import Bitbank
from tradingbot.strategy import ema, atr

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

def get_history(pair, candle_type='1hour', days=20):
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

def aggregate_candles(candles_1h, bar_size=5):
    agg = []
    for i in range(0, len(candles_1h) - bar_size + 1, bar_size):
        chunk = candles_1h[i:i+bar_size]
        t = chunk[0][0]
        o = chunk[0][1]
        h = max(c[2] for c in chunk)
        l = min(c[3] for c in chunk)
        cl = chunk[-1][4]
        v = sum(c[5] for c in chunk)
        agg.append((t, o, h, l, cl, v))
    return agg

def analyze_candles(candles, tf_name):
    if len(candles) < 30:
        return None
    closes = [c[4] for c in candles]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema90 = ema(closes, 90)
    ema200 = ema(closes, 200)
    
    rsi = calc_rsi(closes, 14)
    
    # Wick calculations over last 15 candles
    up_wicks = []
    lo_wicks = []
    bodies = []
    for _, o, h, l, cl, _ in candles[-15:]:
        up = h - max(o, cl)
        lo = min(o, cl) - l
        b = abs(cl - o)
        up_wicks.append(up)
        lo_wicks.append(lo)
        bodies.append(b)
        
    avg_up = sum(up_wicks) / len(up_wicks)
    avg_lo = sum(lo_wicks) / len(lo_wicks)
    avg_b = sum(bodies) / len(bodies)
    
    last_c = closes[-1]
    e20, e50, e90, e200 = ema20[-1], ema50[-1], ema90[-1], ema200[-1]
    
    # Trend scoring
    bull_count = sum([last_c > e20, last_c > e50, last_c > e90, last_c > e200])
    
    if bull_count >= 3:
        bias = "BULLISH UPTREND (Favors LONGS)"
    elif bull_count <= 1:
        bias = "BEARISH DOWNTREND (Favors SHORTS)"
    else:
        bias = "NEUTRAL / CHOPPING RANGE"
        
    dist_e200 = ((last_c / e200) - 1.0) * 100.0 if len(candles) >= 200 else 0.0
    
    return {
        'tf': tf_name,
        'bars': len(candles),
        'close': last_c,
        'rsi': rsi,
        'ema20': e20,
        'ema50': e50,
        'ema90': e90,
        'ema200': e200,
        'dist_ema200': dist_e200,
        'avg_up_wick': avg_up,
        'avg_lo_wick': avg_lo,
        'up_lo_ratio': avg_up / (avg_lo + 1e-6),
        'bias': bias
    }

pairs = ['btc_jpy', 'sol_jpy', 'eth_jpy', 'doge_jpy']
print("=" * 85)
print("MULTI-TIMEFRAME ANALYSIS: 1-HOUR vs 4-HOUR vs 5-HOUR")
print("=" * 85)

for pair in pairs:
    c_1h = get_history(pair, '1hour', days=25)
    # Pull 4h candles
    c_4h_raw = []
    for y in [2025, 2026]:
        try:
            for o, h, l, c, v, ts in api.candles(pair, '4hour', str(y)):
                c_4h_raw.append((int(ts), float(o), float(h), float(l), float(c), float(v)))
        except:
            pass
    c_4h_raw.sort()
    seen = set()
    c_4h = []
    for r in c_4h_raw:
        if r[0] not in seen:
            seen.add(r[0])
            c_4h.append(r)
            
    c_5h = aggregate_candles(c_1h, bar_size=5)
    
    print(f"\n>>> PAIR: {pair.upper()} <<<")
    for c_data, name in [(c_1h, '1-Hour'), (c_4h, '4-Hour'), (c_5h, '5-Hour')]:
        r = analyze_candles(c_data, name)
        if r:
            print(f"[{r['tf']:6}] Close: {r['close']:10.2f} | RSI: {r['rsi']:5.1f} | EMA50: {r['ema50']:10.2f} | EMA200: {r['ema200']:10.2f} ({r['dist_ema200']:+5.1f}%) | Up/Lo Wick: {r['up_lo_ratio']:.2f} | {r['bias']}")
