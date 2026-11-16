#!/usr/bin/env python3
import os, sys, json, time

def load_env(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("\"'")
    except FileNotFoundError:
        pass

load_env("/home/karma/Trading-bot/.env")
load_env("./.env")

from tradingbot.bitbank import Bitbank
api = Bitbank()

assets = api.assets()
jpy_free = assets.get("jpy", 0.0)

pos = []
try:
    raw_pos = api.margin_positions()
    pos = [p for p in raw_pos if float(p.get("open_amount", 0)) > 0]
except Exception as e:
    pos = f"err: {e}"

orders = {}
pairs = ["btc_jpy", "eth_jpy", "sol_jpy", "xrp_jpy", "doge_jpy"]
for p in pairs:
    time.sleep(0.2)
    try:
        res = api._get("/user/spot/active_orders", {"pair": p})
        orders[p] = res.get("orders", [])
    except Exception as e:
        orders[p] = f"err: {e}"

print(json.dumps({
    "jpy_free": jpy_free,
    "positions": pos,
    "orders": orders
}, indent=2))
