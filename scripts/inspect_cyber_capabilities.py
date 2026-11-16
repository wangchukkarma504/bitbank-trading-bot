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
from tradingbot.bitbank import Bitbank, BitbankError

b = Bitbank()

# Check pair info
try:
    p_info = b.pair_info("cyber_jpy")
    print("cyber_jpy pair_info:", p_info)
except Exception as e:
    print("cyber_jpy pair_info err:", e)

# Test placing a dummy stop order on cyber_jpy
try:
    res = b.order("cyber_jpy", side="buy", amount=1.0, type_="stop", trigger_price=60.0)
    print("Stop order on cyber_jpy result:", res)
except BitbankError as e:
    print("Stop order on cyber_jpy error code:", e.code, e.msg)
except Exception as e:
    print("Stop order general error:", e)

# Check if cyber is in margin pairs
try:
    margin_pairs = b._get("/user/margin/pairs")
    print("Margin pairs:", margin_pairs)
except Exception as e:
    print("Margin pairs error:", e)
