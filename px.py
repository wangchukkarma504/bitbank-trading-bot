"""Read-only: current prices for the main pairs."""
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
for p in ("btc_jpy", "eth_jpy", "doge_jpy", "sol_jpy"):
    print(p, api.ticker(p)["last"])
