import os
import sys
import datetime

sys.path.insert(0, "/home/karma/Trading-bot")

def load_env(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass

load_env("/home/karma/Trading-bot/.env")
from tradingbot.bitbank import Bitbank

b = Bitbank()
# Fetch daily/15m candles
today = datetime.datetime.now().strftime("%Y%m%d")
candles = b.candles("cyber_jpy", "15min", today)
if candles:
    last_10 = candles[-10:]
    for c in last_10:
        o, h, l, cl, vol, ts = c
        dt = datetime.datetime.fromtimestamp(ts/1000).strftime("%H:%M")
        print(f"{dt}: O={o} H={h} L={l} C={cl} Vol={vol}")
