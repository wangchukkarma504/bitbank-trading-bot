import os
import sys

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

sys.path.insert(0, "/home/karma/Trading-bot")
load_env("/home/karma/Trading-bot/.env")
from tradingbot.bitbank import Bitbank

b = Bitbank()

try:
    tk = b.ticker("cyber_jpy")
    print("CYBER/JPY ticker:", tk)
except Exception as e:
    print("CYBER/JPY ticker error:", e)

try:
    pairs = b._get("/user/spot/pairs")
    print("User spot pairs:", [p.get("name") for p in pairs.get("pairs", []) if "cyber" in p.get("name", "")])
except Exception as e:
    pass

try:
    # Check public ticker list or pairs
    import requests
    res = requests.get("https://public.bitbank.cc/tickers").json()
    cyber_data = [d for d in res.get("data", []) if "cyber" in d.get("pair", "")]
    print("Public tickers cyber:", cyber_data)
except Exception as e:
    print("Public tickers error:", e)
