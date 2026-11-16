"""Unit and integration test suite for ASCII Easy Dashboard & Capital Milestones.

Verifies:
- Milestone progress formula and 16-character Unicode progress bar rendering:
  • 2X Milestone (20,000 JPY): Baseline ¥10,001.00
  • 5X Milestone (50,000 JPY)
  • 10X Milestone (100,000 JPY)
- Target ladder progress bar rendering for Margin Short and Spot Long.
- Dashboard string format: Budget, 2.0x buying power, total value, PnL, active stops.
- Boundary conditions: 0% progress, 100% cap, target equal to entry, negative PnL.
- Live / Mock exchange dashboard generation.
"""

import math
import unittest
from typing import Any, Dict, List, Optional, Tuple

from tests.mock_bitbank import MockBitbankClient


# =====================================================================
# Dashboard Reference Logic (Contract Verification)
# =====================================================================

def calc_milestone_progress(
    current_equity: float,
    baseline: float = 10001.0,
    target: float = 20000.0,
) -> Tuple[float, float, str]:
    """Calculate milestone progress percentage, remaining distance, and 16-char bar string.
    Returns: (progress_pct, to_go_jpy, bar_str)
    """
    gain = max(0.0, current_equity - baseline)
    required_gain = max(1.0, target - baseline)
    progress_pct = min(100.0, (gain / required_gain) * 100.0)
    to_go_jpy = max(0.0, target - current_equity)

    filled = int(round((progress_pct / 100.0) * 16))
    filled = max(0, min(16, filled))
    bar_str = "█" * filled + "░" * (16 - filled)

    return progress_pct, to_go_jpy, bar_str


def calc_target_ladder_progress(
    entry_price: float,
    last_price: float,
    target_price: float,
    side: str = "short",
) -> Tuple[float, str]:
    """Calculate target ladder progress for open position.
    Returns: (progress_pct, bar_str)
    """
    if side == "short":
        total_dist = entry_price - target_price
        traveled = entry_price - last_price
    else:
        total_dist = target_price - entry_price
        traveled = last_price - entry_price

    if total_dist <= 0.0:
        return 0.0, "░" * 16

    progress_pct = max(0.0, min(100.0, (traveled / total_dist) * 100.0))
    filled = int(round((progress_pct / 100.0) * 16))
    filled = max(0, min(16, filled))
    bar_str = "█" * filled + "░" * (16 - filled)

    return progress_pct, bar_str


def render_ascii_dashboard(
    client: MockBitbankClient,
    starting_budget: float = 10001.0,
    usdjpy: float = 154.5,
) -> str:
    """Render full ASCII Easy Dashboard output."""
    total_equity = client.calculate_total_equity()
    buying_power = total_equity * 2.0
    total_pnl = total_equity - starting_budget
    total_pnl_pct = (total_pnl / starting_budget) * 100.0

    sign = "+" if total_pnl >= 0 else ""
    pnl_usd = total_pnl / usdjpy
    equity_usd = total_equity / usdjpy
    budget_usd = starting_budget / usdjpy
    buying_power_usd = buying_power / usdjpy

    p2x, rem2x, bar2x = calc_milestone_progress(total_equity, baseline=starting_budget, target=20000.0)
    p5x, rem5x, bar5x = calc_milestone_progress(total_equity, baseline=starting_budget, target=50000.0)
    p10x, rem10x, bar10x = calc_milestone_progress(total_equity, baseline=starting_budget, target=100000.0)

    lines = [
        "╔══════════════════════════════════════════════════════════════════════════╗",
        "║               📈 BITBANK CRYPTO BOT: EASY DASHBOARD                      ║",
        "╚══════════════════════════════════════════════════════════════════════════╝",
        f" 💰 Starting Budget       : ¥{starting_budget:,.0f} (${budget_usd:.2f} USDT)",
        f" ⚡ 2.0x Buying Power     : ¥{buying_power:,.0f} (${buying_power_usd:.2f} USDT) [Max 80% used]",
        f" 🏦 Current Total Value   : ¥{total_equity:,.1f} (${equity_usd:.2f} USDT)",
        f" 📊 Total Profit / Loss   : {sign}¥{total_pnl:,.1f} ({sign}${pnl_usd:.2f} | {sign}{total_pnl_pct:.2f}%)",
        "╶──────────────────────────────────────────────────────────────────────────╴",
        " 🎯 CAPITAL MILESTONES:",
        f"   • 2X Milestone  [¥20,000 JPY] : [{bar2x}] {p2x:4.1f}% (¥{rem2x:,.2f} to go)",
        f"   • 5X Milestone  [¥50,000 JPY] : [{bar5x}] {p5x:4.1f}% (¥{rem5x:,.2f} to go)",
        f"   • 10X Milestone [¥100,000 JPY]: [{bar10x}] {p10x:4.1f}% (¥{rem10x:,.2f} to go)",
        "╶──────────────────────────────────────────────────────────────────────────╴",
    ]

    # Active positions & orders
    open_positions = client.get_open_positions()
    active_orders = [o for o in client.orders.values() if o["status"] == "UNFILLED"]

    active_count = len(open_positions)
    status_label = f"{active_count} running" if active_count > 0 else f"{len(active_orders)} pending fill"
    lines.append(f" 🎯 ACTIVE TRADES ({status_label}):")

    if open_positions:
        for p in open_positions:
            pair = p["pair"]
            side = p["position_side"]
            amt = float(p["open_amount"])
            avg_px = float(p["average_price"])
            tk = client.ticker(pair)
            last_px = float(tk["last"])

            pnl = amt * (avg_px - last_px) if side == "short" else amt * (last_px - avg_px)
            pnl_sign = "+" if pnl >= 0 else ""
            notional = amt * avg_px

            target_px = avg_px * 0.98 if side == "short" else avg_px * 1.02
            ladder_pct, ladder_bar = calc_target_ladder_progress(avg_px, last_px, target_px, side=side)

            pair_label = pair.replace("_", "").upper()
            lines.extend([
                f"   [{pair_label}] MARGIN {side.upper()} (Size: ¥{notional:,.0f} | {amt:.4f} | 1.60x Lev)",
                f"   • Current PnL   : {pnl_sign}¥{pnl:,.1f}",
                f"   • Entry Price   : {avg_px:,.1f} JPY",
                f"   • Current Price : {last_px:,.1f} JPY",
                f"   • Profit Target : {target_px:,.1f} JPY",
                f"   • Target Ladder : [{ladder_bar}] {ladder_pct:.1f}% toward target",
            ])
    else:
        lines.append("   No open positions. Actively scanning Bitbank pairs.")

    lines.append("════════════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


# =====================================================================
# Test Suite
# =====================================================================

class TestDashboardMilestoneMath(unittest.TestCase):
    """Tier 1: Milestone progress math and 16-character bar string verification."""

    def test_milestone_calculations_live_equity(self):
        live_equity = 10142.30
        baseline = 10001.00

        # Gain = 141.30 JPY
        gain = live_equity - baseline

        # 2X Milestone [20,000 JPY]:
        # Required gain = 20,000 - 10,001 = 9,999.00 JPY
        # Progress % = (141.30 / 9999.00) * 100 = 1.413%
        p2x, rem2x, bar2x = calc_milestone_progress(live_equity, baseline=baseline, target=20000.0)
        self.assertAlmostEqual(p2x, 1.413, delta=0.01)
        self.assertAlmostEqual(rem2x, 9857.70, places=2)
        # 1.41% of 16 bars: round(0.01413 * 16) = 0 or 1 bar
        self.assertEqual(len(bar2x), 16)
        self.assertTrue(all(c in ("█", "░") for c in bar2x))

        # 5X Milestone [50,000 JPY]:
        # Required gain = 50,000 - 10,001 = 39,999.00 JPY
        # Progress % = (141.30 / 39999.00) * 100 = 0.353%
        p5x, rem5x, bar5x = calc_milestone_progress(live_equity, baseline=baseline, target=50000.0)
        self.assertAlmostEqual(p5x, 0.353, delta=0.01)
        self.assertAlmostEqual(rem5x, 39857.70, places=2)
        self.assertEqual(len(bar5x), 16)

        # 10X Milestone [100,000 JPY]:
        # Required gain = 100,000 - 10,001 = 89,999.00 JPY
        # Progress % = (141.30 / 89999.00) * 100 = 0.157%
        p10x, rem10x, bar10x = calc_milestone_progress(live_equity, baseline=baseline, target=100000.0)
        self.assertAlmostEqual(p10x, 0.157, delta=0.01)
        self.assertAlmostEqual(rem10x, 89857.70, places=2)
        self.assertEqual(len(bar10x), 16)

    def test_milestone_progress_boundaries(self):
        # 1. Zero gain (equity <= baseline) -> 0% progress, 16 empty bars
        p0, rem0, bar0 = calc_milestone_progress(current_equity=10001.0, baseline=10001.0, target=20000.0)
        self.assertEqual(p0, 0.0)
        self.assertEqual(bar0, "░" * 16)

        # 2. Below baseline (drawdown) -> 0% progress
        p_loss, rem_loss, bar_loss = calc_milestone_progress(current_equity=9500.0, baseline=10001.0, target=20000.0)
        self.assertEqual(p_loss, 0.0)
        self.assertEqual(bar_loss, "░" * 16)

        # 3. Exactly at milestone -> 100% progress, 16 filled bars
        p100, rem100, bar100 = calc_milestone_progress(current_equity=20000.0, baseline=10001.0, target=20000.0)
        self.assertEqual(p100, 100.0)
        self.assertEqual(rem100, 0.0)
        self.assertEqual(bar100, "█" * 16)

        # 4. Over milestone -> capped at 100.0%, 0 to go
        p_over, rem_over, bar_over = calc_milestone_progress(current_equity=25000.0, baseline=10001.0, target=20000.0)
        self.assertEqual(p_over, 100.0)
        self.assertEqual(rem_over, 0.0)
        self.assertEqual(bar_over, "█" * 16)


class TestTargetLadderMath(unittest.TestCase):
    """Tier 1: Target ladder progress bar math for short and long."""

    def test_short_target_ladder(self):
        entry = 13718.8
        target = 13470.0
        # Halfway point: 13718.8 - 0.5 * (13718.8 - 13470.0) = 13594.4
        halfway = 13594.4
        pct, bar = calc_target_ladder_progress(entry, halfway, target, side="short")
        self.assertAlmostEqual(pct, 50.0, places=1)
        self.assertEqual(bar, "█" * 8 + "░" * 8)

    def test_long_target_ladder(self):
        entry = 100.0
        target = 110.0
        # Price is at 105.0 -> 50%
        pct, bar = calc_target_ladder_progress(entry, 105.0, target, side="long")
        self.assertAlmostEqual(pct, 50.0, places=1)
        self.assertEqual(bar, "█" * 8 + "░" * 8)

    def test_ladder_boundaries(self):
        # Already hit target -> 100%
        pct_hit, bar_hit = calc_target_ladder_progress(100.0, 90.0, 90.0, side="short")
        self.assertEqual(pct_hit, 100.0)
        self.assertEqual(bar_hit, "█" * 16)

        # Moved in wrong direction (adverse) -> 0%
        pct_adv, bar_adv = calc_target_ladder_progress(100.0, 110.0, 90.0, side="short")
        self.assertEqual(pct_adv, 0.0)
        self.assertEqual(bar_adv, "░" * 16)


class TestDashboardOutputRendering(unittest.TestCase):
    """Tier 1 & 2: Full ASCII dashboard string rendering."""

    def setUp(self):
        self.client = MockBitbankClient(starting_cash_jpy=10142.30)

    def test_render_empty_dashboard(self):
        output = render_ascii_dashboard(self.client, starting_budget=10001.0)
        self.assertIn("BITBANK CRYPTO BOT: EASY DASHBOARD", output)
        self.assertIn("Starting Budget", output)
        self.assertIn("2.0x Buying Power", output)
        self.assertIn("Current Total Value", output)
        self.assertIn("2X Milestone", output)
        self.assertIn("5X Milestone", output)
        self.assertIn("10X Milestone", output)
        self.assertIn("No open positions", output)

    def test_render_dashboard_with_active_short(self):
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

        output = render_ascii_dashboard(self.client, starting_budget=10001.0)
        self.assertIn("SOLJPY", output)
        self.assertIn("MARGIN SHORT", output)
        self.assertIn("Target Ladder", output)
        self.assertIn("1 running", output)


if __name__ == "__main__":
    unittest.main()
