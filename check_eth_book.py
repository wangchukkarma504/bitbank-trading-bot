from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
depth = api._pub('/eth_jpy/depth')
print("Top 10 Asks ETH:")
for ask in depth['asks'][:10]:
    print(f"  {ask[0]}: {ask[1]}")
print("Top 10 Bids ETH:")
for bid in depth['bids'][:10]:
    print(f"  {bid[0]}: {bid[1]}")
