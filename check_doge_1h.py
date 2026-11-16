import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

today = dt.datetime.now(dt.timezone.utc).date()
rows = []
for d in (today - dt.timedelta(days=i) for i in (2, 1, 0)):
    c = api.candles("doge_jpy", "1hour", d.strftime("%Y%m%d"))
    rows += [(int(t), float(o), float(h), float(l), float(c), float(v)) for o, h, l, c, v, t in c]
rows.sort()
print("=== DOGE/JPY Last 12 1h candles ===")
for t, o, h, l, c, v in rows[-12:]:
    tm = dt.datetime.fromtimestamp(t/1000, dt.timezone(dt.timedelta(hours=9))).strftime("%m-%d %H:%M")
    print(f"{tm}: O={o:.3f} H={h:.3f} L={l:.3f} C={c:.3f} V={v:.1f}")

today_hi = max(r[2] for r in rows[-24:])
today_lo = min(r[3] for r in rows[-24:])
print(f"24h Hi: {today_hi:.3f}, 24h Lo: {today_lo:.3f}")
