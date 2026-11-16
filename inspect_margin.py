import json
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()
s = api._get('/user/margin/status')
print(json.dumps(s, indent=2))
