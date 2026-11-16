# Bitbank Autonomous Trading Bot & Dashboard

An autonomous, regime-gated Spot Long and Margin Short trading system for the **Bitbank** exchange, powered by a FastAPI web dashboard, exchange-side stop protection, and a 3-role multi-agent execution pipeline.

---

## Features

- **10-Pair Market Radar:**
  - **Margin Pairs (Long & Short):** `btc_jpy`, `eth_jpy`, `sol_jpy`, `doge_jpy`, `xrp_jpy`
  - **Spot-Only Altcoins (Long Only):** `ada_jpy`, `link_jpy`, `avax_jpy`, `dot_jpy`, `ltc_jpy`
- **Multi-Agent Architecture (`tradingbot/execution/`):**
  - `DirectionalStrategist`: Scores macro/trend alignment (`15m`, `1h`, `4h`) and strictly gates `SHORT` signals to margin-eligible pairs.
  - `RiskManager` & `StopSyncManager`: Handles spot/margin sizing, maker limit entries, exchange-side `stop` orders, trailing stop ratchets, and automatic partial-stop deduplication.
  - `PositionReviewer`: Audits open positions to ensure every margin position has an active exchange-side stop.
- **FastAPI Live Dashboard (`tradingbot/server.py`, `tradingbot/dashboard_html.py`):**
  - Real-time equity, PnL vs baseline, open positions, active exchange stops, and 10-pair radar signals.
  - Shows **Estimated Net Close PnL** (after 0.12% taker fee) and **If Stop Hits** loss estimates.
  - Includes one-click **Close Position** buttons (`POST /api/close-position`) to cancel resting orders on a pair and market-close immediately.
  - **Settings Modal:** Update **Baseline Capital (JPY)** (with a `+¥10,000` deposit button), **Custom Goal Target (JPY)** (or leave `0` to auto-adjust `2x / 5x / 10x`), and **Spot Long-Only** mode for accounts without margin/short access.
  - Optional dashboard login gate via `DASHBOARD_USER` / `DASHBOARD_PASS`.

---

## One-Command Install & Run

Clone the repository and run `install_and_run.sh`:

```bash
git clone git@github.com:wangchukkarma504/bitbank-trading-bot.git
cd bitbank-trading-bot
chmod +x install_and_run.sh start.sh stop.sh
./install_and_run.sh
```

By default, `./install_and_run.sh`:
1. Creates a `.venv` virtual environment (if missing)
2. Installs dependencies from `requirements.txt`
3. Creates `.env` from `.env.example` (if missing)
4. Starts the FastAPI server in **paper mode** on `http://localhost:8000`

To install and run in **live mode** (after adding your Bitbank credentials to `.env`):

```bash
./install_and_run.sh --mode live --baseline 98874.1 --port 8000
```

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in your credentials:

```ini
# Bitbank API Credentials (required for --mode live)
API_KEY=your_bitbank_api_key_here
SECRET_KEY=your_bitbank_api_secret_here

# Optional Web Dashboard Authentication (leave DASHBOARD_PASS blank to disable login gate)
DASHBOARD_USER=admin
DASHBOARD_PASS=
```

> **Security Note:** `.env` is gitignored. Never commit API keys or secrets.

---

## Starting & Stopping the Server

### Linux / macOS / WSL (`.sh`)

- **Start in background:**
  ```bash
  ./start.sh live 8000 98874.1
  # Arguments: [mode: live|paper] [port: 8000] [optional baseline JPY]
  ```
  Logs are written to `trading_server.log` and the process ID is saved to `.server.pid`.

- **Stop the server:**
  ```bash
  ./stop.sh
  ```
  *(Note: Stopping the local server does **not** cancel existing native exchange-side stop orders on Bitbank.)*

- **Run in foreground (manual):**
  ```bash
  python3 -u -m tradingbot.server --mode live --baseline 98874.1 --port 8000
  # Add --spot-only for accounts without margin/short access
  ```

### Windows + WSL (`.bat`)

- **Start:** Double-click `start_trading_server.bat` (stops any previous WSL server instance, opens `http://localhost:8000`, and starts the live server in WSL `Ubuntu-26.04`).
- **Stop:** Double-click `stop_trading_server.bat` (terminates `tradingbot.server` inside WSL).

---

## Auto-Learn Engine (`LossLearningEngine`)

The bot includes an automatic self-learning module in [`tradingbot/analysis/loss_learner.py`](tradingbot/analysis/loss_learner.py) that monitors every closed trade, diagnoses losing trades, persists lessons to `loss_lessons.json`, and applies **bounded, reversible** safety adjustments so the bot stops repeating the same mistake.

### How It Works
When an open position closes, `LossLearningEngine.record_trade_close()` checks whether `exit_equity_jpy < entry_equity_jpy * 0.9995`:

1. **If the trade was a loss:**
   - Diagnoses the most likely root cause using the trade's hold duration, macro bias, orderbook depth ratio, and entry conviction:
     | Root Cause | Trigger Condition | Automatic Adaptation Applied |
     |---|---|---|
     | `FAST_WHIPSAW_STOP` | Closed in `< 180s` | Raises `pair` min conviction (`+0.08`) **and** widens `stop_width_mult` by `+0.10x` (up to `1.25x` max) |
     | `COUNTER_MACRO_BIAS` | Shorted into `BULLISH` macro or longed into `BEARISH` macro | Raises `pair` min conviction (`+0.08`) |
     | `ORDERBOOK_IMBALANCE_TRAP` | Shorted with bid-heavy book (`depth_ratio >= 1.8`) or longed with ask-heavy book (`depth_ratio <= 0.55`) | Raises `pair` min conviction (`+0.08`) **and** enables `orderbook_penalty_active` (`-0.10` conviction penalty when book opposes trade) |
     | `WEAK_CONVICTION_ENTRY` | Entry conviction `< 0.70` | Raises `pair` min conviction (`+0.08`) |
     | `TREND_REVERSAL_EXHAUSTION` | Default when none of the above triggered | Raises `pair` min conviction (`+0.08`) |
   - **Consecutive Loss Cooldown Scaling:** If a pair loses `2` or more times in a row, its post-loss cooldown scales by `streak` (up to `3.0x` via `get_pair_cooldown_multiplier()`).
   - **Hard Safety Bounds:**
     - `MAX_CONVICTION_BOOST = 0.25` (effective minimum conviction is always capped at `0.92` so the bot never locks itself out permanently).
     - `MAX_STOP_WIDTH_MULT = 1.25` (stops are never widened beyond `+25%` and hard exchange-side stops always remain mandatory).
     - `MAX_COOLDOWN_MULT = 3.0`

2. **If the trade was a win or breakeven:**
   - Resets `pair_loss_streaks[pair] = 0`.
   - Gradually relaxes `pair_conviction_boost[pair]` by `-0.05` and `stop_width_mult` by `-0.05` (back toward `1.0x`), so temporary caution fades as market conditions improve.

### Concrete Examples

- **Example 1 — Fast Whipsaw Stop on `btc_jpy`:**
  1. Bot enters a `btc_jpy` short with base `MIN_CONVICTION = 0.70`, and gets stopped out in `65s` for `-1,200 JPY`.
  2. `diagnose_loss()` classifies it as **`FAST_WHIPSAW_STOP`** (`hold_duration_sec < 180s`).
  3. Auto-Learn logs: `[AUTO-LEARN] Loss detected on btc_jpy (-1,200.0 JPY / -1.20%, 65s) | Cause=FAST_WHIPSAW_STOP | Fix=btc_jpy min_conv+0.08, stop_width_mult=1.10x`.
  4. On the next `btc_jpy` signal, `btc_jpy` now requires **`0.78`** conviction instead of `0.70`, and its stop distance is automatically given **`1.10x`** breathing room.

- **Example 2 — Orderbook Imbalance Trap on `sol_jpy`:**
  1. Bot shorts `sol_jpy` while bids outweigh asks (`depth_ratio = 2.1 >= 1.8`) and loses `-1,000 JPY` after `400s`.
  2. `diagnose_loss()` classifies it as **`ORDERBOOK_IMBALANCE_TRAP`**.
  3. Auto-Learn enables `orderbook_imbalance_filter=ON` and raises `sol_jpy` min conviction by `+0.08`. Future opposing-book signals receive a `-0.10` conviction penalty.

- **Example 3 — Recovery After a Win:**
  1. `btc_jpy` later closes a winning trade (`+2,400 JPY`).
  2. Auto-Learn resets `btc_jpy` loss streak to `0`, lowers `pair_conviction_boost["btc_jpy"]` by `0.05`, and reduces `stop_width_mult` from `1.10x` back down to `1.05x`.

---

## Anti-Churn & Capital Preservation Guardrails

- **Exchange-Side Stops:** Every open margin position is audited on every tick by `PositionReviewer` and protected by a native Bitbank `stop` order (`StopSyncManager`). Duplicate/partial stops are automatically deduplicated so full-coverage stops are always retained.
- **Circuit Breakers:** Pauses new entries for 30 minutes if **2 consecutive losses** occur, **5+ entries** happen within 1 hour, or equity experiences a rapid drawdown from peak.
- **Stale Limit Cleanup:** Resting maker limit orders older than 10 minutes, whose signal flipped, or whose target price drifted `> 1.0%` are cancelled automatically.

---

## Progressive Web App (PWA) & Mobile Support

The dashboard is a full **Progressive Web App** served over HTTPS (e.g. `https://your-domain.example.com` via Cloudflare Tunnel) with custom app icons (`/static/icon-180.png`, `icon-192.png`, `icon-512.png`), `/manifest.webmanifest`, and `/sw.js`:

- **iPhone / iPad (Safari):** Open the dashboard URL → tap **Share** → **Add to Home Screen**.
- **Android / Desktop (Chrome / Edge):** Tap **Menu → Install App** inside the dashboard (or click the browser address bar's **Install** icon).
- **Mobile-Responsive Candlestick Chart:** The top **Live Bitbank Price Chart** automatically scales to your phone width (`1:1` crisp rendering, 36-candle mobile window, touch crosshair for OHLC inspection, and **Entry / Stop Loss / TP / Last** price overlays).

---

## Running Tests

Run the unit and integration test suite (uses `MockBitbank` — no live API calls):

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```
