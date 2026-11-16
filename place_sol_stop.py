from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
PAIR = "sol_jpy"
AMOUNT = "0.7100"
TRIGGER = "14040.0"

print(f"Placing exchange stop order for {AMOUNT} {PAIR} @ trigger {TRIGGER}...")
res = api._post("/user/spot/order", {
    "pair": PAIR,
    "amount": AMOUNT,
    "trigger_price": TRIGGER,
    "side": "buy",
    "type": "stop",
    "position_side": "short"
})
print("Result:", res)
