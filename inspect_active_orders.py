#!/usr/bin/env python3
import os, sys, json

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

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    load_env(env_path)
else:
    load_env('/home/karma/Trading-bot/.env')

from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
res = api._get("/user/spot/active_orders", {"pair": "sol_jpy"})
print(json.dumps(res, indent=2))
