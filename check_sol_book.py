from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
depth = api._pub('/sol_jpy/depth')
print("Top 15 Asks:")
for ask in depth['asks'][:15]:
    print(f"  {ask[0]}: {ask[1]}")
