import os, sys, time, json
import urllib.request

sys.path.insert(0, '/home/karma/Trading-bot')

env_path = '/home/karma/Trading-bot/.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k.strip()] = v.strip().strip('\'"')

pairs = ['btc_jpy', 'eth_jpy', 'sol_jpy', 'xrp_jpy', 'doge_jpy']
tickers = {}
for p in pairs:
    try:
        url = f"https://public.bitbank.cc/{p}/ticker"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            tickers[p] = float(data.get('data', {}).get('last', 0))
    except Exception as e:
        tickers[p] = str(e)

jpy_free = None
active_orders = {}
try:
    import python_bitbankcc
    api_key = os.environ.get('BITBANK_API_KEY')
    api_secret = os.environ.get('BITBANK_API_SECRET')
    if api_key and api_secret:
        prv = python_bitbankcc.private(api_key, api_secret)
        assets = prv.get_asset()
        for a in assets.get('assets', []):
            if a.get('asset') == 'jpy':
                jpy_free = float(a.get('free_amount', 0.0))
        for p in pairs:
            time.sleep(0.15)
            orders = prv.get_active_orders(p)
            active_orders[p] = orders.get('orders', [])
except Exception as e:
    active_orders['error'] = str(e)

result = {
    'jpy_free': jpy_free,
    'tickers': tickers,
    'active_orders': active_orders
}

print(json.dumps(result, indent=2))
