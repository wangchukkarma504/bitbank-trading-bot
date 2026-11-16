from forex_bot.backtest import run_forex_backtest
import json

res = run_forex_backtest(symbol='EURUSDT', candle_limit=1000, interval='1h', initial_capital=10000.0)
trades = res.pop('trades', [])
print(json.dumps(res, indent=2))
print(f'Total trades executed: {len(trades)}')
