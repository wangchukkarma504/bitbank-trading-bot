from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
try:
    print(api.cancel("eth_jpy", 61825743887))
except Exception as e:
    print("Error:", e)
