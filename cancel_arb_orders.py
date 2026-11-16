#!/usr/bin/env python3
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

orders = api._get("/user/spot/active_orders", {"pair": "arb_jpy"}).get("orders", [])
for o in orders:
    oid = o.get("order_id")
    try:
        api.cancel("arb_jpy", oid)
        print(f"Cancelled ARB order {oid}")
    except Exception as e:
        print(f"Error cancelling {oid}: {e}")
