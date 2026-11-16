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

## Running Tests

Run the unit and integration test suite (uses `MockBitbank` — no live API calls):

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```
