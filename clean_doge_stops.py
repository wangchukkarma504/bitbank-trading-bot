import time
from tradingbot import bot  # noqa: F401
from tradingbot.bitbank import Bitbank

api = Bitbank()

tk = api.ticker('doge_jpy')
print('Current DOGE Ticker:', tk)

res = api._get('/user/spot/active_orders', {'pair': 'doge_jpy'})
orders = res.get('orders', [])
print(f'Total active orders on doge_jpy: {len(orders)}')

if orders:
    keep_order = orders[0]
    print(f"Keeping order: {keep_order.get('order_id')} (type={keep_order.get('type')}, trigger={keep_order.get('trigger_price')}, amount={keep_order.get('start_amount')})")
    to_cancel = orders[1:]
    print(f"Cancelling {len(to_cancel)} redundant orders...")
    for o in to_cancel:
        oid = o.get('order_id')
        try:
            api.cancel('doge_jpy', oid)
            print(f"Cancelled {oid}")
            time.sleep(0.15)
        except Exception as e:
            print(f"Error cancelling {oid}: {e}")

res_remaining = api._get('/user/spot/active_orders', {'pair': 'doge_jpy'})
remaining = res_remaining.get('orders', [])
print(f"Remaining active orders on doge_jpy: {len(remaining)}")
for r in remaining:
    print(f"Active order: ID={r.get('order_id')}, type={r.get('type')}, side={r.get('side')}, trigger={r.get('trigger_price')}, amount={r.get('start_amount')}, status={r.get('status')}")
