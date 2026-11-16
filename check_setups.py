import datetime as dt
from tradingbot import bot  # loads .env
from tradingbot.bitbank import Bitbank

api = Bitbank()
pairs = ['doge_jpy', 'sol_jpy', 'eth_jpy']
today = dt.datetime.now(dt.timezone.utc).date()

for p in pairs:
    rows = []
    for d in (today - dt.timedelta(days=i) for i in (3, 2, 1, 0)):
        try:
            c = api.candles(p, '1hour', d.strftime('%Y%m%d'))
            rows += [(int(t), float(o), float(h), float(l), float(c)) for o, h, l, c, v, t in c]
        except Exception:
            pass
    rows.sort()
    last = rows[-48:]
    hi48 = max(r[2] for r in last)
    lo48 = min(r[3] for r in last)
    hi24 = max(r[2] for r in rows[-24:])
    lo24 = min(r[3] for r in rows[-24:])
    curr = float(api.ticker(p)['last'])
    depth = api._pub(f'/{p}/depth')
    bids = depth['bids'][:3]
    asks = depth['asks'][:3]
    info = api.pair_info(p)
    print(f"=== {p} ===")
    print(f"Current: {curr} | 24h Hi: {hi24} Lo: {lo24} | 48h Hi: {hi48} Lo: {lo48}")
    print(f"Digits: price={info['price_digits']}, amount={info['amount_digits']}")
    print(f"Bids: {bids}")
    print(f"Asks: {asks}")
    print()
