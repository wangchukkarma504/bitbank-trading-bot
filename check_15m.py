import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
pairs = ['doge_jpy', 'sol_jpy', 'eth_jpy']
today = dt.datetime.now(dt.timezone.utc).date()

for p in pairs:
    c = api.candles(p, '15min', today.strftime('%Y%m%d'))
    rows = [(int(t), float(o), float(h), float(l), float(c), float(v)) for o, h, l, c, v, t in c]
    rows.sort()
    last8 = rows[-8:]
    print(f"=== {p} last 2 hours (15m candles) ===")
    for t, o, h, l, cl, v in last8:
        tm = dt.datetime.fromtimestamp(t/1000, dt.timezone(dt.timedelta(hours=9))).strftime("%H:%M")
        print(f"{tm}: O={o} H={h} L={l} C={cl} V={v:.2f}")
    print()
