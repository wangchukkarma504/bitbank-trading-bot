#!/usr/bin/env python3
import sys
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

orders = api._get("/user/spot/active_orders", {"pair": "sol_jpy"}).get("orders", [])
for o in orders:
    oid = o.get("order_id")
    try:
        api.cancel("sol_jpy", oid)
        print(f"Cancelled {oid}")
    except Exception as e:
        print(f"Error cancelling {oid}: {e}")
