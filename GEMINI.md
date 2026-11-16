# Autonomous Trading Operating Rules

## Operating Environment
- Live bots, API scripts, and daemons run exclusively in WSL: `Ubuntu-26.04` at `/home/karma/Trading-bot`.
- Never commit or print API keys from `/home/karma/Trading-bot/.env`.

## Autonomous Mandate & Strategy Execution
- **Full Delegation:** Execute trades autonomously across both Long (spot) and Short (margin) setups without requiring manual step-by-step user confirmation.
- **Long Trading:** Managed by `tradingbot.bot` (4h EMA30/90 crossover, 4h EMA200 trend filter, 4-ATR trailing stop). Longs only enter when BTC regime confirms an uptrend.
- **Short Trading:** Managed by `short_limit.py` (patient maker limit shorts into resistance during confirmed 4h downtrends). Always utilize maker orders to capture the -0.02% maker rebate rather than paying taker fees.

## Capital Preservation & Risk Controls (Non-Negotiable)
1. **Exchange-Side Stops:** Every margin short MUST have an active exchange-side stop order placed immediately upon fill. Never leave naked positions.
2. **Sizing & Leverage (High-Velocity Aggressive Mode):**
   - Spot Longs: Maximum 30% equity allocation per pair (`PAIR_ALLOC = 0.3`).
   - Margin Shorts: Sized at 80% of 2.0x leverage (1.60x notional equity allocation) on high-conviction intraday 15m/1h breakdown-retest setups. Hard stop loss strictly mandatory on every fill. Never overleverage beyond 2.0x.
3. **No Unmanaged Orders:** Never leave resting limit orders far away without a managing process or attached risk plan.
4. **Market Intelligence & Research:**
   - Use internet search / news intel for macro context, regulatory changes, and catalyst awareness.
   - Headlines are context, never unbacked signals: strategy parameter changes require offline 4h backtests showing edge across both split halves.
