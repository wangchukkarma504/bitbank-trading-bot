#!/usr/bin/env python3
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
print(api.pair_info('arb_jpy'))
