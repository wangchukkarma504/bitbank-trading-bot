"""News and trend snapshot for the bot's pairs. Read-only.

Headlines are context for a human, not a trading signal: they cannot be backtested.
Only numeric signals (like the Fear & Greed index) get tested before the bot uses them.

    python3 -m tradingbot.market_intel
"""
import datetime as dt
import xml.etree.ElementTree as ET

import requests

from .bitbank import Bitbank
from .strategy import Params, Signals

FEEDS = {"CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
         "Cointelegraph": "https://cointelegraph.com/rss"}
UA = {"User-Agent": "Mozilla/5.0 (trading-bot market_intel)"}
P = Params(fast=30, slow=90, trend=200, stop_atr=4.0)


def fng(limit=1):
    """Fear & Greed Index, newest first: (unix_ts, value 0-100, label). limit=0 returns all history."""
    d = requests.get("https://api.alternative.me/fng/", params={"limit": limit}, headers=UA, timeout=15).json()["data"]
    return [(int(x["timestamp"]), int(x["value"]), x["value_classification"]) for x in d]


def headlines(per_feed=5):
    out = []
    for name, url in FEEDS.items():
        n = 0
        try:
            root = ET.fromstring(requests.get(url, headers=UA, timeout=15).content)
            for it in root.iter("item"):
                out.append((name, it.findtext("pubDate", ""), it.findtext("title", "").strip()))
                n += 1
                if n >= per_feed:
                    break
        except Exception as e:
            out.append((name, "", f"(feed failed: {e})"))
    return out


def trend(pair):
    b, rows = Bitbank(), []
    year = dt.datetime.now(dt.timezone.utc).year
    for y in (year - 1, year):
        rows += [(int(t), float(o), float(h), float(l), float(c), float(v)) for o, h, l, c, v, t in b.candles(pair, "4hour", str(y))]
    rows.sort()
    sg = Signals(rows, P)
    i = len(rows) - 1
    px = rows[i][4]
    return dict(pair=pair, px=px, chg_7d=px / rows[i - 42][4] - 1, vs_ema200=px / sg.t[i] - 1,
                trend="UP" if sg.f[i] > sg.s[i] else "DOWN", entry=sg.entry(i))


if __name__ == "__main__":
    f = fng(8)
    print(f"Fear & Greed: {f[0][1]} ({f[0][2]}) | 7 days ago: {f[-1][1]} ({f[-1][2]})")
    print("\nTrend (4h, bot strategy view):")
    for pair in ("btc_jpy", "eth_jpy", "doge_jpy"):
        t = trend(pair)
        print(f"  {pair:9} px {t['px']:>12,.3f} | 7d {t['chg_7d']:+.1%} | vs EMA200 {t['vs_ema200']:+.1%} "
              f"| trend {t['trend']} | bot would enter now: {t['entry']}")
    print("\nHeadlines (context only):")
    for src, when, title in headlines():
        print(f"  [{src}] {title}")
