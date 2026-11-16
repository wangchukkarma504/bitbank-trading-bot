#!/usr/bin/env python3
from tradingbot import bot
from tradingbot.bitbank import Bitbank
api = Bitbank()
pairs = api._get("/spot/pairs").get("pairs", [])
margin_pairs = [p['name'] for p in pairs if p.get('margin_open_maker_fee_rate_quote') is not None]
spot_only_pairs = [p['name'] for p in pairs if p.get('margin_open_maker_fee_rate_quote') is None and p['name'].endswith('_jpy')]
print("Margin Pairs:", margin_pairs)
print(f"Spot Only Pairs ({len(spot_only_pairs)}):", spot_only_pairs[:15])
