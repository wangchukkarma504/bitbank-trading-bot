import os
import sys

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
res = b.cancel("cyber_jpy", 62067935520)
print("Cancel result:", res)
