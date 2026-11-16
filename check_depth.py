from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
d = api._pub("/eth_jpy/depth")
print("Top 10 asks:")
for px, qty in d["asks"][:10]:
    print(f"  {px}: {qty}")
print("Top 10 bids:")
for px, qty in d["bids"][:10]:
    print(f"  {px}: {qty}")
