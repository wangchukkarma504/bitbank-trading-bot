import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()

def ema(data, window):
    alpha = 2 / (window + 1)
    res = [data[0]]
    for x in data[1:]:
        res.append(alpha * x + (1 - alpha) * res[-1])
    return res

for pair in ['sol_jpy', 'doge_jpy', 'btc_jpy']:
    today = dt.datetime.now(dt.timezone.utc).date()
    rows = []
    for d in (today - dt.timedelta(days=i) for i in (3, 2, 1, 0)):
        try:
            c = api.candles(pair, '1hour', d.strftime('%Y%m%d'))
            rows += [(int(t), float(o), float(h), float(l), float(c)) for o, h, l, c, v, t in c]
        except Exception:
            pass
    rows.sort()
    seen = set()
    dedup = []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            dedup.append(r)
    closes = [r[4] for r in dedup]
    ema12 = ema(closes, 12)[-1]
    ema26 = ema(closes, 26)[-1]
    ema50 = ema(closes, 50)[-1]
    curr_px = float(api.ticker(pair)['last'])
    hi24 = max(r[2] for r in dedup[-24:])
    lo24 = min(r[3] for r in dedup[-24:])
    hi12 = max(r[2] for r in dedup[-12:])
    lo12 = min(r[3] for r in dedup[-12:])
    print(f"=== {pair} ===")
    print(f"Last Price: {curr_px}")
    print(f"1h EMAs: EMA12={ema12:.1f}, EMA26={ema26:.1f}, EMA50={ema50:.1f}")
    print(f"24h Range: High={hi24:.1f}, Low={lo24:.1f} | 12h Range: High={hi12:.1f}, Low={lo12:.1f}")
    recent_highs = [r[2] for r in dedup[-12:]]
    print(f"Recent Hourly Highs: {recent_highs[-6:]}")
    print()
