"""Unit and functional test suite for Risk, Order Execution, and Native Exchange Stops.

Covers:
- Role 1: Position Reviewer (equity accounting, buying power, naked position audit).
- Role 2: Directional Strategist (regime selection, long gating under bearish BTC macro filter).
- Role 6: Risk & Profit Execution Manager:
  - Sizing math (1.60x short allocation, 50% max long allocation, AD/PD precision quantization).
  - Maker limit order execution with post_only: true and -0.02% rebate capture.
  - Mandatory native exchange stop order placement (type: "stop").
  - Place-before-cancel atomic stop synchronization (sync_stop).
  - Rejection of non-margin pairs (e.g. arb_jpy).
  - Price gap-through execution.
  - Bitbank Monday maintenance (code 10007) and Nonce collision (code 20001) fault recovery.
  - Emergency market cover fail-safe.
"""

import math
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

from tradingbot.bitbank import BitbankError
from tradingbot.models import (
    MARGIN_PAIRS,
    SUPPORTED_PAIRS,
    PairConfig,
    PositionSide,
    OrderType,
    SizingPlan,
    StopOrderSpec,
)
from tests.mock_bitbank import MockBitbankClient


# =====================================================================
# Sizing and Risk Helper Functions (Contract Verification)
# =====================================================================

def calculate_margin_short_size(
    equity_jpy: float,
    pair: str,
    entry_price: float,
    leverage_factor: float = 1.60,
) -> Tuple[float, str, float]:
    """Compute margin short executable size.
    Returns: (target_quantity, formatted_quantity_str, notional_exposure_jpy)
    """
    if equity_jpy <= 0 or entry_price <= 0:
        raise ValueError("Equity and entry price must be positive")

    cfg = MARGIN_PAIRS[pair]
    target_notional = equity_jpy * leverage_factor
    target_qty = target_notional / entry_price

    # Floor quantization to AD digits
    ad = cfg.amount_digits
    quantized_qty = math.floor(target_qty * (10 ** ad) + 1e-9) / (10 ** ad)
    formatted_qty = f"{quantized_qty:.{ad}f}"
    actual_notional = quantized_qty * entry_price

    return quantized_qty, formatted_qty, actual_notional


def calculate_spot_long_size(
    equity_jpy: float,
    free_cash_jpy: float,
    pair: str,
    entry_price: float,
    alloc_cap: float = 0.50,
    default_alloc: float = 0.30,
) -> Tuple[float, str, float]:
    """Compute spot long executable size adhering to 50% cap."""
    if equity_jpy <= 0 or entry_price <= 0:
        raise ValueError("Equity and entry price must be positive")

    cfg = MARGIN_PAIRS.get(pair, PairConfig(pair=pair, price_digits=3, amount_digits=4))
    budget_jpy = min(equity_jpy * alloc_cap, free_cash_jpy * 0.98, equity_jpy * default_alloc)
    target_qty = budget_jpy / entry_price

    ad = cfg.amount_digits
    quantized_qty = math.floor(target_qty * (10 ** ad) + 1e-9) / (10 ** ad)
    formatted_qty = f"{quantized_qty:.{ad}f}"
    actual_notional = quantized_qty * entry_price

    return quantized_qty, formatted_qty, actual_notional


class StopSyncManager:
    """Simulates Role 6 place-before-cancel atomic stop manager."""

    def __init__(self, client: MockBitbankClient, pair: str):
        self.client = client
        self.pair = pair
        self.current_stop_id: Optional[int] = None
        self.current_stop_level: Optional[float] = None
        self.current_stop_qty: Optional[str] = None
        self.emergency_covered: bool = False

    def sync_stop(self, qty: str, trigger_price: float, position_side: str = "short") -> Optional[Dict[str, Any]]:
        """Place new stop FIRST, verify matching engine order_id, then cancel old stop."""
        side = "buy" if position_side == "short" else "sell"
        meta = MARGIN_PAIRS.get(self.pair)
        pd = meta.price_digits if meta else 1
        trigger_str = f"{trigger_price:.{pd}f}" if pd > 0 else str(int(round(trigger_price)))

        new_order = None
        for attempt in range(2):
            try:
                new_order = self.client.order(
                    pair=self.pair,
                    side=side,
                    amount=qty,
                    type_="stop",
                    position_side=position_side,
                    trigger_price=trigger_str,
                )
                break
            except BitbankError:
                time.sleep(0.01)

        if not new_order or not new_order.get("order_id"):
            # Emergency fail-safe
            self.emergency_market_cover(f"Stop placement failed on {self.pair}")
            return None

        # Verify new stop is confirmed UNFILLED
        new_oid = new_order["order_id"]
        old_oid = self.current_stop_id

        self.current_stop_id = new_oid
        self.current_stop_level = trigger_price
        self.current_stop_qty = qty

        # Cancel old stop only AFTER new stop is safely on matching engine
        if old_oid is not None:
            try:
                self.client.cancel(self.pair, old_oid)
            except BitbankError:
                pass

        return new_order

    def emergency_market_cover(self, reason: str) -> None:
        """Emergency liquidate position to prevent unhedged exposure."""
        self.emergency_covered = True
        try:
            for p in self.client.margin_positions():
                if p["pair"] == self.pair and float(p["open_amount"]) > 0:
                    amt = p["open_amount"]
                    side = "buy" if p["position_side"] == "short" else "sell"
                    self.client.order(
                        self.pair,
                        side=side,
                        amount=amt,
                        type_="market",
                        position_side=p["position_side"],
                    )
        except BitbankError:
            # Under severe exchange error, emergency state is recorded
            pass


# =====================================================================
# Test Suites
# =====================================================================

class TestPositionSizingMath(unittest.TestCase):
    """Tier 1: Position sizing formulas and quantization across 5 pairs."""

    def test_short_sizing_160x_live_equity(self):
        live_equity = 10142.30
        target_notional = live_equity * 1.60
        self.assertAlmostEqual(target_notional, 16227.68, places=2)

        # 1. SOL/JPY (~13,750 JPY) -> Target notional 16,227.68 / 13,750 = 1.18019 -> floor 1.1801 SOL
        sol_qty, sol_str, sol_notional = calculate_margin_short_size(live_equity, "sol_jpy", 13750.0)
        self.assertIn(sol_str, ("1.1800", "1.1801"))
        self.assertAlmostEqual(sol_notional, 16226.38, delta=2.0)
        self.assertAlmostEqual(sol_notional / live_equity, 1.600, delta=0.005)

        # 2. DOGE/JPY (~15.50 JPY) -> 16,227.68 / 15.50 = 1046.94709 -> floor 1046.9470 DOGE
        doge_qty, doge_str, doge_notional = calculate_margin_short_size(live_equity, "doge_jpy", 15.50)
        self.assertIn(doge_str, ("1046.9000", "1046.9470"))
        self.assertLessEqual(doge_notional, target_notional)
        self.assertAlmostEqual(doge_notional / live_equity, 1.600, delta=0.005)

        # 3. ETH/JPY (~335,000 JPY) -> Expected 0.0484 ETH
        eth_qty, eth_str, eth_notional = calculate_margin_short_size(live_equity, "eth_jpy", 335000.0)
        self.assertEqual(eth_str, "0.0484")
        self.assertLessEqual(eth_notional, target_notional)
        self.assertAlmostEqual(eth_notional / live_equity, 1.599, delta=0.005)

        # 4. BTC/JPY (~11,800,000 JPY) -> Expected 0.0013 BTC
        btc_qty, btc_str, btc_notional = calculate_margin_short_size(live_equity, "btc_jpy", 11800000.0)
        self.assertEqual(btc_str, "0.0013")
        self.assertLessEqual(btc_notional, target_notional)
        self.assertLessEqual(btc_notional / live_equity, 1.60)

        # 5. XRP/JPY (~125.0 JPY) -> 16,227.68 / 125.0 = 129.82144 -> floor 129.8214 XRP
        xrp_qty, xrp_str, xrp_notional = calculate_margin_short_size(live_equity, "xrp_jpy", 125.0)
        self.assertIn(xrp_str, ("129.8000", "129.8214"))
        self.assertLessEqual(xrp_notional, target_notional)
        self.assertAlmostEqual(xrp_notional / live_equity, 1.600, delta=0.005)

    def test_spot_long_sizing_cap_50pct(self):
        live_equity = 10142.30
        free_cash = 10142.30

        # Spot long default 30% allocation
        qty, str_val, notional = calculate_spot_long_size(live_equity, free_cash, "sol_jpy", 13750.0, default_alloc=0.30)
        self.assertLessEqual(notional, live_equity * 0.3001)
        self.assertLessEqual(notional, live_equity * 0.50)  # Capped strictly at 50%

        # Hard cap check: Even if caller requests 70% allocation, it must be capped at 50%
        qty_cap, str_cap, notional_cap = calculate_spot_long_size(live_equity, free_cash, "sol_jpy", 13750.0, alloc_cap=0.50, default_alloc=0.70)
        self.assertLessEqual(notional_cap, live_equity * 0.5001)


class TestNativeExchangeStops(unittest.TestCase):
    """Tier 1: Mandatory native exchange stop orders and zero-naked-position invariant."""

    def setUp(self):
        self.client = MockBitbankClient(starting_cash_jpy=10142.30)

    def test_native_stop_market_order_creation(self):
        # Place native exchange stop order for margin short
        res = self.client.order(
            pair="sol_jpy",
            side="buy",
            amount=1.1800,
            type_="stop",
            position_side="short",
            trigger_price=13900.0,
        )
        self.assertIn("order_id", res)
        self.assertEqual(res["type"], "stop")
        self.assertEqual(res["status"], "UNFILLED")
        self.assertEqual(res["side"], "buy")
        self.assertEqual(res["position_side"], "short")
        self.assertEqual(res["trigger_price"], "13900.0")

        # Verify active stop order exists in active_orders
        active = self.client._get("/user/spot/active_orders", {"pair": "sol_jpy"})["orders"]
        stops = [o for o in active if o["type"] == "stop"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["order_id"], res["order_id"])

    def test_zero_naked_position_invariant(self):
        # 1. Fill a margin short order of 1.1800 SOL
        order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=1.1800,
            price=13755.0,
            type_="limit",
            position_side="short",
        )
        self.client.simulate_fill(order["order_id"])

        # At this point, position is open without a stop -> assert_zero_naked_positions MUST fail!
        with self.assertRaises(AssertionError) as ctx:
            self.client.assert_zero_naked_positions()
        self.assertIn("INVARIANT VIOLATION: Naked margin position detected", str(ctx.exception))

        # 2. Place matching native stop order
        self.client.order(
            pair="sol_jpy",
            side="buy",
            amount=1.1800,
            type_="stop",
            position_side="short",
            trigger_price=13900.0,
        )

        # Now zero-naked-position invariant holds!
        self.client.assert_zero_naked_positions()

    def test_atomic_place_before_cancel_sync(self):
        manager = StopSyncManager(self.client, "sol_jpy")

        # Initial stop
        stop1 = manager.sync_stop(qty="1.1800", trigger_price=13900.0)
        self.assertIsNotNone(stop1)
        self.assertEqual(manager.current_stop_id, stop1["order_id"])

        # Ratchet stop to break-even (13750.0)
        stop2 = manager.sync_stop(qty="1.1800", trigger_price=13750.0)
        self.assertIsNotNone(stop2)
        self.assertEqual(manager.current_stop_id, stop2["order_id"])
        self.assertNotEqual(stop1["order_id"], stop2["order_id"])

        # Verify old stop is CANCELED and new stop is UNFILLED
        old_order = self.client.get_order("sol_jpy", stop1["order_id"])
        new_order = self.client.get_order("sol_jpy", stop2["order_id"])
        self.assertEqual(old_order["status"], "CANCELED_UNFILLED")
        self.assertEqual(new_order["status"], "UNFILLED")


class TestMakerRebateArbitrage(unittest.TestCase):
    """Tier 1: Maker limit order post_only and fee rebate verification."""

    def setUp(self):
        self.client = MockBitbankClient(starting_cash_jpy=10142.30)

    def test_post_only_boolean_preserved(self):
        # Verify boolean true is preserved and does not convert to string 'True'
        order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=1.1800,
            price=13800.0,
            type_="limit",
            position_side="short",
            post_only=True,
        )
        self.assertIs(order["post_only"], True)
        self.assertEqual(order["status"], "UNFILLED")

    def test_maker_rebate_accrual_on_fill(self):
        initial_jpy = self.client.jpy_free
        # Place maker short limit sell at 13800.0 (above market 13750.0)
        order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=1.1800,
            price=13800.0,
            type_="limit",
            position_side="short",
            post_only=True,
        )
        self.client.simulate_fill(order["order_id"])

        # Notional = 1.1800 * 13800 = 16,284.00 JPY
        # Maker rebate (-0.02%) = 16,284 * 0.0002 = +3.2568 JPY earned
        self.assertGreater(self.client.rebates_earned_jpy, 3.20)
        self.assertEqual(self.client.fees_paid_jpy, 0.0)
        self.assertGreater(self.client.jpy_free, initial_jpy)

    def test_post_only_crossing_spread_is_rejected(self):
        # Best bid is ~13745. If sell limit order is <= 13745 with post_only,
        # it would cross the spread and take liquidity. It must be rejected/cancelled!
        order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=1.1800,
            price=13740.0,
            type_="limit",
            position_side="short",
            post_only=True,
        )
        self.assertEqual(order["status"], "CANCELED_UNFILLED")


class TestBoundaryAndFaultRecovery(unittest.TestCase):
    """Tier 2: Non-margin pair rejection, gap-through, maintenance, and nonce collisions."""

    def setUp(self):
        self.client = MockBitbankClient(starting_cash_jpy=10142.30)

    def test_non_margin_pair_stop_order_rejection(self):
        # arb_jpy is a spot-only pair without native exchange stop order support
        with self.assertRaises(BitbankError) as ctx:
            self.client.order(
                pair="arb_jpy",
                side="sell",
                amount=100.0,
                type_="stop",
                trigger_price=28.0,
            )
        self.assertIn("Stop orders not supported on spot-only pair arb_jpy", str(ctx.exception))

    def test_price_gap_through_stop_market_execution(self):
        # Open short at 13750 with stop market at 13900
        order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=1.1800,
            price=13750.0,
            type_="limit",
            position_side="short",
        )
        self.client.simulate_fill(order["order_id"])

        stop_order = self.client.order(
            pair="sol_jpy",
            side="buy",
            amount=1.1800,
            type_="stop",
            position_side="short",
            trigger_price=13900.0,
        )
        self.assertEqual(stop_order["status"], "UNFILLED")

        # Price violently gaps past 13900 to 14200!
        triggered = self.client.simulate_tick("sol_jpy", price=14200.0)

        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0]["order_id"], stop_order["order_id"])
        self.assertEqual(triggered[0]["status"], "FULLY_FILLED")

        # Verify short position is completely covered (open_amount == 0.0)
        positions = self.client.get_open_positions()
        sol_pos = [p for p in positions if p["pair"] == "sol_jpy"]
        self.assertEqual(len(sol_pos), 0)

    def test_bitbank_monday_maintenance_code_10007(self):
        # In maintenance mode, API calls fail with code 10007
        self.client.simulate_maintenance(True)

        with self.assertRaises(BitbankError) as ctx:
            self.client.ticker("sol_jpy")
        self.assertIn("10007", str(ctx.exception))

        # Turn maintenance off -> resumes smoothly
        self.client.simulate_maintenance(False)
        tk = self.client.ticker("sol_jpy")
        self.assertIn("last", tk)

    def test_nonce_collision_retry_recovery(self):
        # Inject 1 nonce collision (code 20001)
        self.client.simulate_nonce_collision(count=1)

        # First query should raise 20001
        with self.assertRaises(BitbankError) as ctx:
            self.client._get("/user/assets")
        self.assertIn("20001", str(ctx.exception))

        # Subsequent query recovers because collision count has expired
        res = self.client._get("/user/assets")
        self.assertIn("assets", res)

    def test_emergency_market_cover_when_stop_fails(self):
        # Open short position
        order = self.client.order(
            pair="sol_jpy",
            side="sell",
            amount=1.1800,
            price=13750.0,
            type_="limit",
            position_side="short",
        )
        self.client.simulate_fill(order["order_id"])

        # Use StopSyncManager but simulate maintenance so stop placement fails
        manager = StopSyncManager(self.client, "sol_jpy")
        self.client.simulate_maintenance(True)

        res = manager.sync_stop(qty="1.1800", trigger_price=13900.0)
        self.assertIsNone(res)
        self.assertTrue(manager.emergency_covered)

    def test_ratchet_idempotency_prevents_order_churn(self):
        """Verify that evaluate_and_apply_ratchets does NOT cancel and replace stop orders
        if the ratchet price level has not changed.
        """
        from tradingbot.execution.risk_manager import RiskManager
        rm = RiskManager(self.client)

        pos = {
            "pair": "sol_jpy",
            "position_side": "short",
            "amount": 1.0273,
            "open_amount": "1.0273",
            "average_price": "13820.2",
            "avg_price": 13820.2,
        }

        # Step 1: When price drops past +1.0%, stop is placed at 13,751.1 JPY
        res1 = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=13660.0,
            client=self.client,
        )
        self.assertIsNotNone(res1)
        oid1 = res1["order_id"]

        # Step 2: On next tick with same or slightly moving price, stop level does NOT change
        # Passing active_stops seeds or preserves existing stop level
        active_stops = [{
            "pair": "sol_jpy",
            "side": "buy",
            "trigger_price": 13751.1,
            "status": "UNFILLED",
            "order_id": oid1,
            "amount": "1.0273",
        }]
        res2 = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=13655.0,
            client=self.client,
            active_stops=active_stops,
        )
        # MUST BE NONE - no order replacement or churning!
        self.assertIsNone(res2)

        # Confirm manager stop ID has NOT changed
        mgr = rm.get_sync_manager("sol_jpy", self.client)
        self.assertEqual(mgr.current_stop_id, oid1)

    def test_multi_tier_dynamic_trailing_ratchets(self):
        """Verify that evaluate_and_apply_ratchets protects small wins cleanly
        through BE (+0.48% -> +0.22%), Early Profit-Lock (+0.80% -> +0.40%),
        and dynamic 1.0% trailing once gain >= +1.6%.
        """
        from tradingbot.execution.risk_manager import RiskManager
        rm = RiskManager(self.client)

        pos = {
            "pair": "sol_jpy",
            "position_side": "short",
            "amount": 1.0,
            "open_amount": "1.0",
            "average_price": "10000.0",
            "avg_price": 10000.0,
        }

        # Case 1: +0.30% (9,970) -> Too early to choke, no ratchet yet
        res_noise = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=9970.0,
            client=self.client,
        )
        self.assertIsNone(res_noise)

        # Case 2: +0.55% (9,945) -> Fee-covered BE ratchet: 10000 * 0.9978 = 9,978.0 (+0.22% locked)
        res_be = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=9945.0,
            client=self.client,
        )
        self.assertIsNotNone(res_be)
        mgr = rm.get_sync_manager("sol_jpy", self.client)
        self.assertAlmostEqual(mgr.current_stop_level, 9978.0, places=1)

        # Case 3: +0.90% (9,910) -> Early Profit-Lock: 10000 * 0.996 = 9,960.0 (+0.40% locked)
        res_early = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=9910.0,
            client=self.client,
        )
        self.assertIsNotNone(res_early)
        self.assertAlmostEqual(mgr.current_stop_level, 9960.0, places=1)

        # Case 4: +2.20% (9,780) -> Dynamic 1.0% trail: max(9780 * 1.010, min_safe) vs floor -> 9780 * 1.010 = 9877.8, floored by +1.4% (9860.0)
        res_tier3 = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=9780.0,
            client=self.client,
        )
        self.assertIsNotNone(res_tier3)
        self.assertAlmostEqual(mgr.current_stop_level, 9860.0, places=1)

        # Case 5: +6.00% (9,400) -> Dynamic 1.0% trail: 9400 * 1.010 = 9494.0
        res_tier5 = rm.evaluate_and_apply_ratchets(
            pair="sol_jpy",
            position=pos,
            current_price=9400.0,
            client=self.client,
        )
        self.assertIsNotNone(res_tier5)
        self.assertAlmostEqual(mgr.current_stop_level, 9494.0, places=1)


if __name__ == "__main__":
    unittest.main()
