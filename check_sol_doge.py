from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()

for p in ["sol_jpy", "doge_jpy"]:
    print(f"=== {p} ===")
    d = api._pub(f"/{p}/depth")
    print("Top 5 bids:", d["bids"][:5])
    print("Top 5 asks:", d["asks"][:5])
    t = api.ticker(p)
    print("Ticker:", t)
    info = api.pair_info(p)
    print("Info:", info["price_digits"], info["amount_digits"])
    print()
