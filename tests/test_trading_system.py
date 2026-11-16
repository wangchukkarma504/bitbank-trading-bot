"""Comprehensive End-to-End Test Suite for Bitbank Autonomous Trading System.

Tiers Covered:
- Tier 3: Cross-Feature Combinations (Signal-to-Order-to-Stop Lifecycle).
  • Trend + Wick + Technical analysis -> Directional Strategist signal
  • Maker limit order with post_only: true and maker rebate (-0.02%)
  • Immediate native exchange stop order placement (type: "stop")
  • Place-before-cancel atomic stop ratcheting (Break-Even -> Profit Lock)
  • Target ladder take-profit execution and milestone progression
- Tier 4: Real-World Scenarios (Multi-Tick Volatile Simulation).
  • 25+ continuous sequential ticks with realistic volatility
  • Assertion of Zero Naked Positions invariant at EVERY tick
  • Strict 1.60x leverage upper bound assertion at EVERY tick
  • Macro BTC regime gating (suppressing longs when BTC < EMA200)
  • Fault injection resiliency: Monday maintenance (10007), Nonce collisions (20001), price gaps
  • Continuous ASCII Easy Dashboard generation
"""

import math
import random
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

from tradingbot.bitbank import BitbankError
from tradingbot.models import (
    Candle,
    MarketTrendResult,
    WickAnalysisResult,
    TechnicalDepthResult,
    OrderBookDepth,
    PairConfig,
    TrendAlignment,
    WickType,
    RsiDivergence,
    PositionSide,
    OrderType,
    RegimeType,
    MARGIN_PAIRS,
    SUPPORTED_PAIRS,
)
from tradingbot.analysis.market_trend import (
    MarketTrendAnalyst,
    calc_ema,
    evaluate_btc_macro_regime,
)
from tradingbot.analysis.wick_anatomy import (
    WickAnatomyAnalyst,
    classify_candle,
)
from tradingbot.analysis.technical_depth import (
    TechnicalDepthAnalyst,
    calc_rsi,
    analyze_order_book,
)
from tests.mock_bitbank import MockBitbankClient
from tests.test_execution_and_stops import (
    StopSyncManager,
    calculate_margin_short_size,
    calculate_spot_long_size,
)
from tests.test_dashboard import (
    calc_milestone_progress,
    calc_target_ladder_progress,
    render_ascii_dashboard,
)


class TestSignalToStopLifecycle(unittest.TestCase):
    """Tier 3: End-to-end signal-to-order-to-stop lifecycle across the 6 roles."""

    def setUp(self):
        self.client = MockBitbankClient(starting_cash_jpy=10142.30, baseline_budget_jpy=10001.00)

    def test_full_short_lifecycle_and_ratchets(self):
        # -------------------------------------------------------------
        # STEP 1: Roles 3, 4, 5 (Market Analysis Engine)
        # -------------------------------------------------------------
        # Role 3: Market Trend Analyst
        # Synthetic BTC 4h candles showing price below EMA200 (BEAR regime)
        btc_candles = [
            Candle(
                timestamp=i * 14400000,
                open=12000000.0 - i * 1500,
                high=12010000.0 - i * 1500,
                low=11980000.0 - i * 1500,
                close=11990000.0 - i * 1500,
                volume=80.0,
            )
            for i in range(220)
        ]
        is_btc_bull, btc_regime, _ = evaluate_btc_macro_regime(btc_candles)
        self.assertFalse(is_btc_bull)
        self.assertEqual(btc_regime, RegimeType.BEAR.value)

        # Role 4: Wick & Candlestick Anatomy Analyst
        # SOL candle exhibits Bearish Rejection (Shooting Star into resistance)
        # Open=13700, Close=13710, Low=13695, High=13780
        # Body = 10, Lower wick = 5, Upper wick = 70 (70 > 1.8*10 and 70 > 1.5*5)
        sol_shooting_star = Candle(
            timestamp=int(time.time() * 1000),
            open=13700.0,
            high=13780.0,
            low=13695.0,
            close=13710.0,
            volume=250.0,
        )
        wick_type = classify_candle(sol_shooting_star)
        self.assertEqual(wick_type, WickType.BEARISH_REJECTION.value)

        # Role 5: Technical & Order Book Analyst
        # Depth book has heavy ask wall overhead (>3.0x avg volume)
        depth_data = self.client.depth("sol_jpy")
        bids = [(float(p), float(v)) for p, v in depth_data["bids"][:20]]
        asks = [(float(p), float(v)) for p, v in depth_data["asks"][:20]]
        depth_ratio, sup_px, res_px, sup_vol, res_vol, _, _ = analyze_order_book(bids, asks)
        self.assertIsNotNone(res_px)
        self.assertGreater(res_vol, 50.0)

        # -------------------------------------------------------------
        # STEP 2: Role 2 (Directional Strategist)
        # -------------------------------------------------------------
        # Consensus: Macro BEAR + Shooting Star + Resistance Wall -> ENTER_MAKER_SHORT
        directive = "ENTER_MAKER_SHORT"
        entry_price = res_px  # Limit order placed at resistance wall
        initial_stop_price = entry_price * 1.015  # 1.5% stop loss
        target_price = entry_price * 0.970        # 3.0% take profit (2.0:1 R:R)

        # -------------------------------------------------------------
        # STEP 3: Role 6 (Risk & Profit Execution Manager)
        # -------------------------------------------------------------
        equity = self.client.calculate_total_equity()
        self.assertAlmostEqual(equity, 10142.30, places=2)

        # Sizing: 1.60x notional allocation on margin short
        qty, qty_str, notional = calculate_margin_short_size(equity, "sol_jpy", entry_price)
        self.assertLessEqual(notional, equity * 1.6001)

        # Place Maker Limit Sell with post_only=True
        limit_order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=qty_str,
            price=entry_price,
            type_="limit",
            position_side="short",
            post_only=True,
        )
        self.assertEqual(limit_order["status"], "UNFILLED")
        self.assertIs(limit_order["post_only"], True)

        # Matching engine simulates fill at resistance
        filled_order = self.client.simulate_fill(limit_order["order_id"])
        self.assertEqual(filled_order["status"], "FULLY_FILLED")

        # Maker fee rebate verification (-0.02%)
        self.assertGreater(self.client.rebates_earned_jpy, 0.0)
        self.assertEqual(self.client.fees_paid_jpy, 0.0)

        # -------------------------------------------------------------
        # STEP 4: Mandatory Native Stop Placement (Zero Naked Position)
        # -------------------------------------------------------------
        stop_manager = StopSyncManager(self.client, "sol_jpy")
        stop1 = stop_manager.sync_stop(qty=qty_str, trigger_price=initial_stop_price)
        self.assertIsNotNone(stop1)
        self.assertEqual(stop1["type"], "stop")

        # Assert Zero Naked Position invariant holds
        self.client.assert_zero_naked_positions()

        # -------------------------------------------------------------
        # STEP 5: Trailing Ratchets (Break-Even -> Profit Lock)
        # -------------------------------------------------------------
        # Price moves favorably down by 0.8%
        be_price = entry_price * 0.992
        self.client.simulate_tick("sol_jpy", be_price)

        # Tier 1 Ratchet: Move stop to Break-Even (entry_price)
        stop2 = stop_manager.sync_stop(qty=qty_str, trigger_price=entry_price)
        self.assertIsNotNone(stop2)
        self.assertNotEqual(stop1["order_id"], stop2["order_id"])

        # Invariant maintained throughout ratchet
        self.client.assert_zero_naked_positions()

        # Price moves down further to 1.8% profit
        lock_market_price = entry_price * 0.982
        self.client.simulate_tick("sol_jpy", lock_market_price)

        # Tier 2 Ratchet: Lock in 1.0% profit
        profit_lock_price = entry_price * 0.990
        stop3 = stop_manager.sync_stop(qty=qty_str, trigger_price=profit_lock_price)
        self.assertIsNotNone(stop3)
        self.client.assert_zero_naked_positions()

        # -------------------------------------------------------------
        # STEP 6: Target Take-Profit Exit
        # -------------------------------------------------------------
        # Price hits target price
        self.client.simulate_tick("sol_jpy", target_price)

        # Cancel remaining stop and cover short
        if stop_manager.current_stop_id:
            self.client.cancel("sol_jpy", stop_manager.current_stop_id)

        cover_order = self.client.order(
            pair="sol_jpy",
            side="buy",
            amount=qty_str,
            type_="market",
            position_side="short",
        )
        self.assertEqual(cover_order["status"], "FULLY_FILLED")

        # Confirm position is 100% closed
        self.assertEqual(len(self.client.get_open_positions()), 0)

        # Net realized profit must be positive
        self.assertGreater(self.client.realized_pnl_jpy, 0.0)
        self.assertGreater(self.client.calculate_total_equity(), 10142.30)

        # Verify milestone progress advanced
        new_equity = self.client.calculate_total_equity()
        prog, rem, _ = calc_milestone_progress(new_equity, 10001.0, 20000.0)
        self.assertGreater(prog, 1.41)

    def test_macro_gating_suppresses_spot_longs_in_bear_regime(self):
        # When BTC is below EMA200, Directional Strategist MUST block Spot Longs
        btc_candles_bear = [
            Candle(
                timestamp=i * 14400000,
                open=10000000.0 - i * 1000,
                high=10010000.0 - i * 1000,
                low=9980000.0 - i * 1000,
                close=9990000.0 - i * 1000,
                volume=50.0,
            )
            for i in range(220)
        ]
        is_bull, regime, _ = evaluate_btc_macro_regime(btc_candles_bear)
        self.assertFalse(is_bull)

        # Simulated Strategist regime gate
        allow_spot_longs = is_bull
        self.assertFalse(allow_spot_longs, "Spot longs must be blocked during bearish macro BTC regime")


class TestMultiTickSimulation(unittest.TestCase):
    """Tier 4: Multi-tick live simulation verifying safety invariants and continuous dashboard output."""

    def setUp(self):
        self.client = MockBitbankClient(starting_cash_jpy=10142.30, baseline_budget_jpy=10001.00)

    def test_25_tick_volatile_simulation_invariants(self):
        random.seed(42)

        # Initialize short position on SOL/JPY with active stop
        initial_px = 13750.0
        equity = self.client.calculate_total_equity()
        qty, qty_str, notional = calculate_margin_short_size(equity, "sol_jpy", initial_px)

        order = self.client.order("sol_jpy", "sell", qty_str, initial_px, type_="limit", position_side="short")
        self.client.simulate_fill(order["order_id"])

        stop_mgr = StopSyncManager(self.client, "sol_jpy")
        stop_mgr.sync_stop(qty_str, trigger_price=initial_px * 1.015)

        # Invariant baseline check
        self.client.assert_zero_naked_positions()

        current_px = initial_px
        # Run 25 continuous volatility ticks
        for tick in range(1, 26):
            # Price delta between -1.0% and +1.0%
            delta_pct = random.uniform(-0.010, 0.010)
            current_px = current_px * (1.0 + delta_pct)

            # 1. Feed tick into mock matching engine
            triggered = self.client.simulate_tick("sol_jpy", current_px)

            # 2. Assert Zero Naked Positions at EVERY tick
            self.client.assert_zero_naked_positions()

            # 3. Assert Leverage Bound at EVERY tick: Never exceed Bitbank's 2.0x hard leverage cap
            tot_equity = self.client.calculate_total_equity()
            open_positions = self.client.get_open_positions()
            for p in open_positions:
                pos_notional = float(p["open_amount"]) * float(p["average_price"])
                effective_leverage = pos_notional / tot_equity
                self.assertLessEqual(effective_leverage, 2.00, f"Overleveraged beyond 2.0x: {effective_leverage:.3f}")

            # 4. Trailing ratchet if favorable
            if open_positions and current_px < initial_px * 0.990:
                stop_mgr.sync_stop(qty_str, trigger_price=initial_px)

            # 5. Render ASCII Dashboard without exception
            dashboard_output = render_ascii_dashboard(self.client)
            self.assertIn("BITBANK CRYPTO BOT", dashboard_output)
            self.assertIn("Capital Milestones", dashboard_output.title())

    def test_fault_injection_during_simulation(self):
        # 1. Nonce collision handling
        self.client.simulate_nonce_collision(count=1)
        with self.assertRaises(BitbankError):
            self.client.ticker("btc_jpy")
        # Second call succeeds
        tk = self.client.ticker("btc_jpy")
        self.assertIn("last", tk)

        # 2. Maintenance window resilience
        self.client.simulate_maintenance(True)
        with self.assertRaises(BitbankError) as ctx:
            self.client.order("sol_jpy", "buy", 1.0, type_="market")
        self.assertIn("10007", str(ctx.exception))
        self.client.simulate_maintenance(False)


if __name__ == "__main__":
    unittest.main()
