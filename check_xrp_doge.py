import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
today = dt.datetime.now(dt.timezone.utc).date()

for pair in ['doge_jpy', 'xrp_jpy']:
    print(f"\n==================== {pair.upper()} ====================")
    rows = []
    for d in (today - dt.timedelta(days=i) for i in (3, 2, 1, 0)):
        try:
            c = api.candles(pair, '1hour', d.strftime('%Y%m%d'))
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
    
    ticker = api.ticker(pair)
    curr = float(ticker['last'])
    info = api.pair_info(pair)
    depth = api._pub(f"/{pair}/depth")
    
    print(f"Current Price: {curr} | Buy: {ticker['buy']} | Sell: {ticker['sell']}")
    print(f"Digits: price={info['price_digits']}, amount={info['amount_digits']}")
    print("Top 5 Asks:")
    for a in depth['asks'][:5]:
        print(f"  {a[0]}: {a[1]}")
    print("Top 5 Bids:")
    for b in depth['bids'][:5]:
        print(f"  {b[0]}: {b[1]}")
    print("\nLast 6 1h Candles:")
    for r in dedup[-6:]:
        ts = dt.datetime.fromtimestamp(r[0]/1000).strftime('%m-%d %H:%M')
        body = abs(r[4] - r[1])
        up_wick = r[2] - max(r[1], r[4])
        lo_wick = min(r[1], r[4]) - r[3]
        print(f"  {ts} | O:{r[1]} H:{r[2]} L:{r[3]} C:{r[4]} V:{r[5]:.0f} | UpWick:{up_wick:.3f} LoWick:{lo_wick:.3f}")
