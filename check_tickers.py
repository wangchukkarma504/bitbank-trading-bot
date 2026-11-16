#!/usr/bin/env python3
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

pairs = ['arb_jpy', 'render_jpy', 'sol_jpy', 'doge_jpy', 'xrp_jpy', 'eth_jpy', 'btc_jpy']
for p in pairs:
    tk = api.ticker(p)
    last = float(tk.get('last', 0))
    buy = float(tk.get('buy', 0))
    sell = float(tk.get('sell', 0))
    hi = float(tk.get('high', 0))
    lo = float(tk.get('low', 0))
    print(f"{p:<10} | last: {last:<9.3f} | bid: {buy:<9.3f} | ask: {sell:<9.3f} | hi: {hi:<9.3f} | lo: {lo:<9.3f}")
