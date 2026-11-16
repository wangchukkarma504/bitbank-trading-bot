from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
res = api._get('/user/spot/status')
print("Status:", res)
pairs = [p['name'] for p in api._get('/spot/pairs')['pairs'] if p['name'].endswith('_jpy')]
for p in pairs:
    info = api.pair_info(p)
    # check if margin order is accepted
    print(p, "margin:", info.get('is_margin', info.get('margin_trading_enable', 'unknown')))
