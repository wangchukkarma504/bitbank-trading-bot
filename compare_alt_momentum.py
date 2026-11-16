#!/usr/bin/env python3
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

for p in ['arb_jpy', 'render_jpy', 'avax_jpy', 'sui_jpy']:
    tk = api.ticker(p)
    d = api._pub(f"/{p}/depth")
    bids = sum([float(b[1]) for b in d.get('bids', [])[:10]])
    asks = sum([float(a[1]) for a in d.get('asks', [])[:10]])
    last = float(tk.get('last', 0))
    vol = float(tk.get('vol', 0))
    print(f"{p}: Last={last:.2f} | 24h Vol={vol:,.0f} (¥{vol*last:,.0f}) | Bid Vol={bids:,.0f} vs Ask Vol={asks:,.0f} (Ratio: {bids/asks if asks>0 else 1:.2f})")
