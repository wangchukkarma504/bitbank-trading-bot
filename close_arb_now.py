#!/usr/bin/env python3
import sys
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
assets = api._get("/user/assets").get("assets", [])
arb_amt = 0.0
for a in assets:
    if a.get("asset") == "arb":
        arb_amt = float(a.get("free_amount", 0.0))
        break

print(f"Found {arb_amt} free ARB. Selling at market to secure profit...")
if arb_amt >= 1.0:
    res = api._post("/user/spot/order", {
        "pair": "arb_jpy",
        "amount": f"{arb_amt:.4f}",
        "side": "sell",
        "type": "market"
    })
    print("Market Sell Executed Successfully:", res)
else:
    print("No ARB to sell.")
