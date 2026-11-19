# Bitbank Trend Bot & Dashboard

A long-only trend-following bot for the **Bitbank** exchange (BTC, ETH, XRP, SOL and DOGE against JPY, on margin), with a web dashboard, exchange-side stops on every position, and a backtester that runs the same rule code the live bot runs.

---

## The rule

Everything the bot decides is in [`tradingbot/strategy.py`](tradingbot/strategy.py), on 4-hour candles:

- **Buy** a coin when a 4h candle closes above the highest high of the previous 120 candles (20 days).
- **Stop** 3 × ATR below the entry (never closer than 1.5% nor further than 15%). The stop is a real stop order on the exchange. It follows the best price at that same distance and never moves down.
- **No profit target.** A trade ends only when the trailing stop is hit, so losers are cut at about the planned amount and winners run until the trend turns.
- **Size** each trade so that hitting the initial stop costs 2% of equity, capped at 65% of equity per position. At most 3 positions at once.
- **Entry order:** a maker (post-only) buy rests at the signal price for 10 minutes to earn the 0.02% rebate; whatever has not filled is then bought at market.

It does not short. It does nothing in a falling market except wait.

### What the bot does about manual trades

- A position you open yourself is never managed or closed by the bot. If it has no stop, the bot gives it one 1.2% from its entry on the second check (about 20 seconds later). You can move or cancel that stop. A stop-loss you set in the Bitbank app (or a stop or stop-limit order) counts: then the bot adds nothing.
- Orders you place yourself are never cancelled.
- A pair with a manual position is not traded by the bot, and manual positions count toward the 3-position limit.
- **Pause** and **Emergency Stop** switch off new entries and survive a restart. Open positions keep their stops in both states, and the bot's own positions keep trailing.

---

## Evidence

`python3 -m tradingbot.backtest` replays the rule on Bitbank's own candles. Assumptions are on the cautious side: entries after the signal candle closes, the low of a candle taken before its high, gaps through the stop filled at the open, taker fee (0.12%) plus 0.05% slippage on market and stop fills, and margin interest (0.04% per day).

Results at 2% risk per trade, up to 3 positions. `R` is the result of a trade divided by the amount it risked.

| Period | Trades | Winners | Average | Growth per year | Worst drawdown |
|---|---|---|---|---|---|
| 2017-01 to 2026-11, 4h candles | 436 | 46% | +0.32R | +27.7% | 17.3% |
| 2023-01 to 2026-11 only (not used to choose the settings) | 218 | 42% | +0.28R | +30.2% | 17.3% |
| 2025-06 to 2026-11 on 5-minute candles | 72 | 42% | +0.38R | +37.8% | 15.5% |

Every calendar year from 2017 to 2026 was positive (between +2R and +28R). The nearby settings (channels of 10 to 30 days, stops of 2 to 4.5 ATR) were all positive in both the first and the second half of the history, so the result does not hang on one lucky setting.

What this means in practice:

- Fewer than half the trades win. The profit comes from a few large winners; the typical trade is a small loss.
- About 45 trades a year, usually held for 2 to 6 days. Whole weeks pass without a trade, and long flat stretches are normal.
- Past results do not guarantee future ones. The edge was smaller in 2023 to 2026 than in 2017 to 2022.

What was tested and rejected on the same data:

- **Selling rallies in a downtrend** (the previous rule: 4h down, 1h down, 15m RSI ≥ 65, 1.2% stop). Over 18 months of 5-minute candles it was between −0.09% and 0% per trade in every variant; its good results came only from the months it had been tuned on.
- **Shorting breakdowns** (the mirror image of the buy rule). About zero or negative from 2023 on.
- **Short channels** (3 days). Positive until 2022, negative since.
- **A machine-learning filter** (`research/ml_filter.py`): logistic regression and boosted trees reading 19 patterns at each breakout (volatility, breakout strength, momentum, trend, volume, candle shape, Bitcoin's trend, how many coins are rising), trained year by year only on earlier trades. On the unseen years it could not tell good breakouts from bad ones (AUC 0.44 to 0.57, where 0.50 is chance), and every variant grew the account more slowly than taking every breakout in 2023 to 2026 (+16.6% to +25.3% a year against +30.2%). The bot does not use it.

---

## Layout

| File | What it is |
|---|---|
| `tradingbot/strategy.py` | The rule: breakout level, stop distance, position size, trailing stop. Pure functions. |
| `tradingbot/backtest.py` | Replay on 4h candles (all years) or 5-minute candles (recent), through `strategy.py`. |
| `tradingbot/engine.py` | The live engine: account read, entries, stops, journal. |
| `tradingbot/bitbank.py` | Minimal Bitbank REST client. |
| `tradingbot/server.py`, `dashboard_html.py` | Control API and web dashboard. |
| `tradingbot/tax_japan.py` | Japan tax report (雑所得) from the exchange's trade history. |
| `tradingbot/forecast.py`, `forecast_model.json`, `predict_html.py` | The experimental Prediction page (never trades). |
| `research/` | Machine-learning tests: `ml_filter.py` (breakout filter), `train_forecast.py` (trains the Prediction page's model). Need `pip install numpy scikit-learn`. |
| `tests/` | Unit tests, a simulated exchange, and a randomised stress run of the engine. |

Runtime files (not committed): `bot_config.json` (settings), `bot_state.json` (the bot's open positions), `trade_journal.json` (closed trades), `equity_history.json`, `trading_server.log`.

---

## Settings (`bot_config.json`)

```json
{
  "baseline_jpy": 20000.66,
  "equity_floor_jpy": 15000.0,
  "capital_limit_jpy": null,
  "goal_target_jpy": null,
  "risk_per_trade_pct": 2.0,
  "max_positions": 3,
  "trading_enabled": true,
  "emergency_stopped": false
}
```

- `risk_per_trade_pct`: share of equity lost when a trade hits its initial stop (0 to 5). In the 2017 to 2026 replay, 1% gave about +14% a year with a 9% worst drawdown, 2% gave +28% with 17%, 3% gave +35% with 24%, and 5% gave +45% with 28%.
- `equity_floor_jpy`: at or below this equity the bot opens nothing new.
- `manual_stop_pct`: distance of the protective stop the bot gives a manual position that has none (default 1.2).
- `capital_limit_jpy`: size positions as if equity were at most this.
- `trading_enabled`, `emergency_stopped`: written by the dashboard's Pause, Resume and Emergency Stop buttons.

---

## Install and run

```bash
git clone git@github.com:wangchukkarma504/bitbank-trading-bot.git
cd bitbank-trading-bot
chmod +x install_and_run.sh start.sh stop.sh
./install_and_run.sh
```

Credentials go in `.env` (gitignored; copy `.env.example`):

```ini
API_KEY=your_bitbank_api_key_here
SECRET_KEY=your_bitbank_api_secret_here

# Optional dashboard login (leave DASHBOARD_PASS blank to disable it)
DASHBOARD_USER=admin
DASHBOARD_PASS=
```

Start, stop and run by hand:

```bash
./start.sh live 8000 20000.66      # mode (live or dry-run), port, baseline JPY; logs to trading_server.log
./stop.sh                          # stops the server; stop orders on the exchange stay in place
python3 -u -m tradingbot.server --mode live --baseline 20000.66 --port 8000
```

In `dry-run` mode the bot reads the account and the candles and logs what it would buy, but places no orders.

On Windows with WSL, `start_trading_server.bat` and `stop_trading_server.bat` do the same.

---

## Dashboard

The dashboard (`http://localhost:8000`, or your own HTTPS address through a tunnel) shows equity, open positions with their stops, a price chart with entry and stop lines, the breakout watch (how far each coin is from its 20-day high), closed trades, and the Japan tax report. It can be installed as an app from the browser (iPhone: Share, then Add to Home Screen; Android and desktop Chrome: Install App).

Buttons: **Pause / Resume**, **Close Position** for one pair, and **STOP ALL TRADES**, which cancels every order and closes every position at market.

**Prediction** (`/predict`, also in the menu) is a test page for machine learning. Pick the chart's candles (5m, 15m, 1h, 4h) and how far ahead to predict (1 hour, 4 hours, 1 day): 15-minute candles one hour ahead are 4 predicted candles, 1-hour candles one day ahead are 24. Predicted candles are drawn as faded green and red candles after the live one, with a cone where the price ended 80% of the time on test data. Drag to move, pinch or scroll to zoom, double-tap to reset, and use Full screen for landscape. A profit/loss calculator takes an amount, long or short, 1x or 2x and a holding time, and shows the predicted result after fees and interest with a good and a bad case. The model is a ridge regression on 12 candle patterns of all five coins; on months it never saw it called the direction right 47 to 50% of the time, no better than a coin flip, while its 80% range held 80% of the time. The candle now forming and every past model candle come from a second model, boosted trees on up to 62 normalized signals (returns, EMA 9/21/50/100, MACD, Bollinger, Stochastic, RSI 7/14/28, CCI, ADX, volume, candle shape, Bitcoin's and Ethereum's moves), trained on 5-minute history since January 2024 (`research/forecast_boost.py` compares the signal sets). On months it never saw it called the next candle's direction right 52 to 54% of the time (up to 64% on its most confident 10% of 5-minute candles), steady month by month, against 50% for guessing. It is shown for testing only and never trades.

---

## Tests

```bash
python3 -m unittest discover -s tests          # unit tests plus a short stress run (no live API calls)
python3 -m tests.test_engine_stress 12 2000    # longer stress run: failures, restarts, partial fills, manual trades
```
