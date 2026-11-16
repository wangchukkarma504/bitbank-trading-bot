import datetime as dt
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
for p in ['sol_jpy', 'doge_jpy', 'eth_jpy']:
    try:
        res = api._get('/user/spot/trade_history', {'pair': p, 'count': 5})
        print(f"=== {p} TRADES ===")
        for t in res.get('trades', []):
            ts = dt.datetime.fromtimestamp(t['executed_at']/1000).strftime('%Y-%m-%d %H:%M:%S')
            print(f"{ts} | order {t['order_id']} | {t['side']} {t['amount']} @ {t['price']} | fee: {t.get('fee_amount_base') or t.get('fee_amount_quote')}")
    except Exception as e:
        print(f"Error {p}:", e)
