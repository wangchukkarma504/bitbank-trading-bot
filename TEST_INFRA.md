# TEST_INFRA — Bitbank Autonomous Trading System Test Infrastructure

## 1. Test Philosophy & Design Principles

The Bitbank Autonomous Trading System controls real capital on the Bitbank cryptocurrency exchange. Reliability, determinism, and capital preservation are non-negotiable invariants. 

The test infrastructure is governed by the following core testing principles:

1. **Opaque-Box Requirement-Driven Testing:**
   Tests verify observable system behavior against the requirements defined in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and exchange API specifications rather than verifying internal implementation details.
2. **Deterministic Matching Engine Simulation:**
   No live API network calls or external flakiness are permitted in the automated test suite. The custom `MockBitbankClient` replicates Bitbank REST responses, order books, matching state machines, fee accounting, maintenance windows, and error codes with 100% determinism.
3. **Strict Invariant Verification:**
   The test suite continuously asserts three non-negotiable safety invariants:
   - **Zero Naked Margin Positions:** Every filled margin position must have an active native exchange stop order (`type: "stop"`) registered on the Bitbank matching engine.
   - **Atomic Place-Before-Cancel Synchronization:** When updating or ratcheting stops, the replacement stop order must be confirmed by the matching engine before any previous stop is cancelled.
   - **Strict Leverage & Sizing Caps:** Margin shorts must never exceed 1.60x notional equity allocation (80% of 2.0x leverage), and spot longs must never exceed 50% allocation.
4. **Adversarial & Fault Injection Testing:**
   The mock engine injects nonce collisions (`code 20001`), maintenance downtime (`code 10007`), price slippage, gap-through events, and invalid pair requests to verify fault tolerance.

---

## 2. Test Architecture & Directory Topology

```
c:\Users\user\OneDrive\Desktop\Trading bot\
├── TEST_INFRA.md                     # Test infrastructure blueprint & coverage specification
├── TEST_READY.md                     # Test runner instructions, execution logs, and readiness gate
├── tests/
│   ├── __init__.py                   # Test package marker
│   ├── mock_bitbank.py               # Deterministic Bitbank matching engine & API mock
│   ├── test_analysis_roles.py        # Tier 1 tests for Roles 3, 4, 5 (Trend, Wick, Technical)
│   ├── test_execution_and_stops.py   # Tier 1 & 2 tests for Roles 1, 2, 6 (Position, Strategy, Risk)
│   ├── test_dashboard.py             # Tier 1 & 2 tests for ASCII Easy Dashboard & milestones
│   └── test_trading_system.py        # Tier 3 & 4 E2E integration & multi-tick simulation tests
```

---

## 3. Mock Bitbank Matching Engine Specification (`tests/mock_bitbank.py`)

The mock engine mirrors the full Bitbank REST API interface used by the trading bot:

### 3.1 Public Endpoints
- `GET /{pair}/ticker`: Returns best bid, best ask, last price, 24h volume, and timestamp.
- `GET /{pair}/depth`: Returns order book bids and asks with realistic volume distributions and user-configurable liquidity walls.
- `GET /{pair}/candlestick/{tf}/{day}`: Returns multi-timeframe OHLCV candle records (`15min`, `1hour`, `4hour`). Supports Bitbank timeframe date formats (`YYYY` for $\ge 4$h, `YYYYMMDD` for $\le 1$h).

### 3.2 Private Endpoints
- `GET /user/assets`: Free and locked balances for JPY and cryptocurrencies.
- `GET /user/margin/positions`: Open margin short and long positions (`open_amount`, `average_price`).
- `GET /user/margin/status`: Margin collateral, margin maintenance ratio (50%), and 2.0x buying power.
- `POST /user/spot/order`:
  - Limit orders (`type: "limit"`) with `post_only` boolean support.
  - Market orders (`type: "market"`).
  - Native exchange stop orders (`type: "stop"`, `trigger_price`, `position_side`).
  - Strict pair validation: Accepts `type: "stop"` only on the 5 supported margin pairs (`sol_jpy`, `doge_jpy`, `eth_jpy`, `btc_jpy`, `xrp_jpy`). Rejects non-margin pairs (e.g., `arb_jpy`) with error simulation.
- `GET /user/spot/order`: Single order lookup by `order_id` returning current status (`UNFILLED`, `FULLY_FILLED`, `CANCELED_UNFILLED`).
- `POST /user/spot/cancel_order`: Cancels resting or stop orders.
- `GET /user/spot/active_orders`: Returns all open resting limit and native stop orders for a pair.

### 3.3 Simulation & Fault Injection Controls
- `simulate_tick(pair, price)`: Moves market price, triggers stop market orders whose trigger price is reached, and fills resting limit orders.
- `simulate_fill(order_id, fill_amount=None)`: Forces partial or full execution of resting limit orders.
- `set_maintenance_mode(active: bool)`: Emits Bitbank weekly Monday maintenance `{"success": 0, "data": {"code": 10007}}`.
- `set_nonce_collision_countdown(count: int)`: Emits authentication nonce collision `{"success": 0, "data": {"code": 20001}}` for the next $N$ calls to verify client backoff and retry.
- `fee_rate`: Computes maker rebate (-0.02% on altcoins, 0.00% on BTC) and taker fee (+0.12% on altcoins, +0.10% on BTC).

---

## 4. Multi-Tier Test Suite Specification

### Tier 1: Feature Coverage (Unit & Functional Verification)
- **Role 3 (Market Trend Analyst):**
  - EMA mathematical accuracy (EMA20, EMA50, EMA200, EMA30, EMA90).
  - Date format resolution (`YYYY` for $\ge 4$h, `YYYYMMDD` for $\le 1$h).
  - Forming candle culling (`now - candle_ts < tf_seconds`).
  - BTC macro regime filter ($Close > EMA200 \implies BULL$, $Close < EMA200 \implies BEAR$).
- **Role 4 (Wick & Candlestick Anatomy Analyst):**
  - Bearish rejection shooting stars ($W_{up} > 1.8 \times Body$ and $W_{up} > 1.5 \times W_{lower}$).
  - Bullish absorption hammers ($W_{lower} > 1.8 \times Body$ and $W_{lower} > 1.5 \times W_{upper}$).
  - Spinning top / indecision ($W_{up} > 1.0 \times Body$ and $W_{lower} > 1.0 \times Body$).
  - Momentum body ($Body > 1.5 \times \text{total wicks}$) and exhaustion patterns.
- **Role 5 (Technical & Order Book Analyst):**
  - Wilder's smoothed RSI(14) computation, boundedness $[0, 100]$, zero loss / zero gain handling.
  - Regular bullish divergence (lower price low, higher RSI low).
  - Regular bearish divergence (higher price high, lower RSI high).
  - Top-20 order book depth ratio ($\sum Bids / \sum Asks$).
  - Support and resistance liquidity wall detection ($>3.0\times$ average level volume).
- **Role 1 (Position Reviewer):**
  - Live total equity computation ($\text{Cash} + \text{Crypto Valuation} + \text{Margin PnL}$).
  - Buying power ($2.0\times$ equity) and allocation budgeting ($1.60\times$ equity).
  - Identification of naked margin positions lacking active exchange stops.
- **Role 2 (Directional Strategist):**
  - Macro regime gating: suppress altcoin longs when BTC is bearish.
  - Multi-indicator conviction scoring and trade directive generation.
- **Role 6 (Risk & Profit Execution Manager):**
  - Sizing plan computation: Margin shorts sized at $1.60\times$ notional equity allocation, Spot longs capped at $50\%$.
  - Precision quantization using pair Price Digits (PD) and Amount Digits (AD).
  - Maker limit order execution with `post_only: true` and fee rebate (-0.02%).
  - Immediate native exchange stop order placement upon fill (`type: "stop"`).
  - Place-before-cancel atomic stop replacement (`sync_stop`).
- **ASCII Easy Dashboard:**
  - Rendering of ASCII table headers, budget (¥10,001.00), equity, PnL, and buying power.
  - 16-character Unicode progress bars (`█` and `░`) for 2X (20,000 JPY), 5X (50,000 JPY), and 10X (100,000 JPY) milestones.
  - Target ladder progress bar rendering.

### Tier 2: Boundary, Corner & Adversarial Cases
- **Low / Zero Cash Collateral:** Handles boundary equity gracefully without division by zero or negative size requests.
- **Maximum Leverage Bound:** Asserts margin short size never exceeds $1.60\times$ equity under extreme price inputs.
- **Non-Margin Pair Rejection:** Confirms attempting a stop order on non-margin pairs (e.g. `arb_jpy`) is strictly rejected and prevented.
- **Price Gap-Through:** Confirms stop market order executes unconditionally when market price gaps past the trigger price.
- **Bitbank Maintenance Resiliency:** Confirms code `10007` responses trigger retry/wait without application termination.
- **Nonce Collision Recovery:** Confirms code `20001` responses trigger jittered backoff and successfully recover without loss of state.
- **Emergency Market Cover:** Confirms failure of stop placement triggers immediate position liquidation.

### Tier 3: Cross-Feature Combinations (End-to-End Pipeline)
- **Complete Signal-to-Exit Lifecycle:**
  1. Market Trend + Wick + Technical analysis emit consensus bearish setup.
  2. Directional Strategist issues `ENTER_MAKER_SHORT`.
  3. Risk Manager places maker limit sell with `post_only: true` at resistance wall.
  4. Matching engine fills maker order, capturing -0.02% rebate.
  5. Risk Manager verifies fill and immediately places native exchange stop order.
  6. Price trends favorably -> Tier 1 Break-Even ratchet engages: new stop is placed and confirmed BEFORE old stop is cancelled.
  7. Price trends further -> Tier 2 Profit-Lock ratchet engages.
  8. Price reaches Take-Profit Target -> Order is covered, stops cancelled, and profit realized.

### Tier 4: Real-World Scenarios (Multi-Tick Simulation)
- **Continuous Multi-Tick Market Simulation:**
  - 20+ sequential ticks of synthetic market volatility across the 5 margin pairs.
  - Strict invariant assertions at every tick:
    - Zero naked positions: $\text{unhedged\_positions} == 0$.
    - Leverage strictly bounded: $\text{margin\_notional} / \text{equity} \le 1.60$.
    - Collateral health maintained: $\text{free\_collateral} > 0$.
    - Dashboard string successfully generated at every tick without runtime exceptions.

---

## 5. Coverage Thresholds & Quality Gates

| Metric | Target Threshold | Scope |
|---|---|---|
| **Test Pass Rate** | 100% | All test suites across Tiers 1–4 |
| **Safety Invariants Tested** | 100% | Zero naked positions, place-before-cancel, 1.60x leverage bound |
| **API Endpoint Coverage** | 100% | All public & private Bitbank endpoints used by the bot |
| **Supported Pairs Verification** | 100% | All 5 margin pairs (`sol_jpy`, `doge_jpy`, `eth_jpy`, `btc_jpy`, `xrp_jpy`) |
| **Error Code Handlers** | 100% | Maintenance (`10007`), Nonce collision (`20001`), Pair rejection |

---

## 6. Test Runner Command

The test suite is executed inside the WSL `Ubuntu-26.04` environment:

```bash
cd /mnt/c/Users/user/OneDrive/Desktop/Trading\ bot && pytest tests/ -v --tb=short
```
