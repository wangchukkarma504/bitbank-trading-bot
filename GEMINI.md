# Autonomous Trading Operating Rules

## Operating Environment
- Live bots, API scripts, and daemons run exclusively in WSL: `Ubuntu-26.04` at `/home/karma/Trading-bot`.
- Never commit or print API keys from `/home/karma/Trading-bot/.env`.

## Autonomous Mandate & Strategy Execution
- **Trading engine:** one process, `python3 -m tradingbot.server` (`tradingbot/engine.py`). The rule lives in `tradingbot/strategy.py` and is replayed by `python3 -m tradingbot.backtest`.
- **Rule (long only):** buy a coin when a 4h candle closes above its 20-day high; exchange stop 3 ATR below, trailing up behind the best price, never down; no profit target; 2% of equity at risk per trade; at most 3 positions.
- **No shorts.** Selling rallies and shorting breakdowns were tested on years of Bitbank candles and rejected (see README, "Evidence").
- **Manual trades:** never managed, closed or cancelled by the bot. A manual position without a stop gets a protective one 1.2% from entry.
- **Changing the rule:** only with a replay over all available years that is positive both before and after 2023.

## Capital Preservation & Risk Controls (Non-Negotiable)
1. **Exchange-Side Stops:** Every margin short MUST have an active exchange-side stop order placed immediately upon fill. Never leave naked positions.
2. **Sizing & Leverage (High-Velocity Aggressive Mode):**
   - Spot Longs: Maximum 30% equity allocation per pair (`PAIR_ALLOC = 0.3`).
   - Margin Shorts: Sized at 80% of 2.0x leverage (1.60x notional equity allocation) on high-conviction intraday 15m/1h breakdown-retest setups. Hard stop loss strictly mandatory on every fill. Never overleverage beyond 2.0x.
3. **No Unmanaged Orders:** Never leave resting limit orders far away without a managing process or attached risk plan.
4. **Market Intelligence & Research:**
   - Use internet search / news intel for macro context, regulatory changes, and catalyst awareness.
   - Headlines are context, never unbacked signals: strategy parameter changes require offline 4h backtests showing edge across both split halves.
