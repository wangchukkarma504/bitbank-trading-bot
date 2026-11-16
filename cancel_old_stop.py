import os, sys
sys.path.insert(0, '/home/karma/Trading-bot')
from bitbank_dashboard import load_env
load_env('/home/karma/Trading-bot/.env')
from tradingbot.bitbank import Bitbank
bb = Bitbank()
res = bb.cancel('sol_jpy', 62044051560)
print('Cancel result:', res)
