import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
year = str(dt.datetime.now(dt.timezone.utc).year)

for p in ['eth_jpy', 'btc_jpy', 'sol_jpy', 'doge_jpy']:
    c = api.candles(p, '4hour', year)
    rows = [(int(t), float(o), float(h), float(l), float(c), float(v)) for o, h, l, c, v, t in c]
    rows.sort()
    print(f"=== {p} Recent 4h Candles ===")
    for t, o, h, l, c, v in rows[-6:]:
        tm = dt.datetime.fromtimestamp(t/1000, dt.timezone(dt.timedelta(hours=9))).strftime("%m-%d %H:%M")
        print(f"  {tm}: O={o:.1f} H={h:.1f} L={l:.1f} C={c:.1f} V={v:.1f}")
    hi7 = max(r[2] for r in rows[-42:])
    lo7 = min(r[3] for r in rows[-42:])
    print(f"  7d Range: High={hi7:.1f}, Low={lo7:.1f}")
    print()
