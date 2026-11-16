#!/usr/bin/env python3
import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

today = dt.datetime.now(dt.timezone.utc).date()
c_15m = api.candles("arb_jpy", "15min", today.strftime("%Y%m%d"))
print("=== ARB_JPY LAST 8 15m CANDLES ===")
for o, h, l, cl, v, t in c_15m[-8:]:
    tm = dt.datetime.fromtimestamp(t/1000, dt.timezone(dt.timedelta(hours=9))).strftime("%H:%M")
    print(f"{tm}: Open={float(o):.3f} High={float(h):.3f} Low={float(l):.3f} Close={float(cl):.3f} Vol={float(v):,.1f}")

tk = api.ticker("arb_jpy")
print("ARB Ticker:", tk)
depth = api._pub("/arb_jpy/depth")
print("Top 5 Bids:", depth.get("bids", [])[:5])
print("Top 5 Asks:", depth.get("asks", [])[:5])
