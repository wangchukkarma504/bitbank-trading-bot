from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
d = api._pub("/doge_jpy/depth")
print("Top 15 DOGE Asks:")
for px, qty in d["asks"][:15]:
    print(f"  {px}: {qty}")
print("Top 15 DOGE Bids:")
for px, qty in d["bids"][:15]:
    print(f"  {px}: {qty}")
