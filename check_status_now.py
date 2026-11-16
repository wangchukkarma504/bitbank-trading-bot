import os, sys
sys.path.insert(0, '/home/karma/Trading-bot')

def load_env(path='/home/karma/Trading-bot/.env'):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip().strip('\'"')

load_env()

from tradingbot.bitbank import Bitbank
bb = Bitbank()

# Cancel all active orders for all pairs
for pair in ['sol_jpy', 'doge_jpy', 'eth_jpy', 'btc_jpy', 'xrp_jpy']:
    orders = bb._get('/user/spot/active_orders', {'pair': pair})
    if isinstance(orders, dict) and 'orders' in orders:
        for o in orders['orders']:
            print(f"Cancelling order {o['order_id']} for {pair}")
            res = bb._post('/user/spot/cancel_order', {'pair': pair, 'order_id': o['order_id']})
            print(f"Cancel result: {res}")

print("\n--- ASSETS ---")
assets_raw = bb._get('/user/assets')
if isinstance(assets_raw, dict):
    for a in assets_raw.get('assets', []):
        if float(a.get('onhand_amount', 0)) > 0:
            print(f"Asset: {a['asset']}, onhand: {a['onhand_amount']}, free: {a['free_amount']}, locked: {a['locked_amount']}")

print("\n--- MARGIN POSITIONS ---")
for pair in ['sol_jpy', 'doge_jpy', 'eth_jpy', 'btc_jpy', 'xrp_jpy']:
    pos = bb._get('/user/margin/positions', {'pair': pair})
    print(pair, pos)
