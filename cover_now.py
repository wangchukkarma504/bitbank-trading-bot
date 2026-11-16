import os, sys
sys.path.insert(0, '/home/karma/Trading-bot')
from bitbank_dashboard import load_env
load_env('/home/karma/Trading-bot/.env')
from tradingbot.bitbank import Bitbank
bb = Bitbank()
res = bb._post('/user/spot/order', {'pair': 'sol_jpy', 'amount': '1.1800', 'side': 'buy', 'type': 'market', 'position_side': 'short'})
print('Cover order result:', res)
