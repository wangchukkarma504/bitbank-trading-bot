"""Tests for LossLearningEngine (auto-detect, diagnose, learn, persist, and adapt)."""

import os
import tempfile
import unittest

from tradingbot.analysis.loss_learner import LossLearningEngine


class TestLossLearner(unittest.TestCase):
    def test_fast_whipsaw_loss_raises_conviction_and_widens_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "lessons.json")
            engine = LossLearningEngine(state_path=path)

            lesson = engine.record_trade_close(
                pair="xrp_jpy",
                side="short",
                entry_equity_jpy=100000.0,
                exit_equity_jpy=99000.0,
                hold_duration_sec=65.0,
                entry_conviction=0.75,
                depth_ratio=1.1,
                macro_bias="BEARISH",
            )
            self.assertTrue(lesson.is_loss)
            self.assertEqual(lesson.root_cause, "FAST_WHIPSAW_STOP")
            self.assertGreater(engine.get_effective_min_conviction("xrp_jpy", 0.65), 0.70)
            self.assertGreater(engine.stop_width_mult, 1.0)
            self.assertGreater(engine.adjust_stop_price(155.0, 157.0, "short"), 157.0)

            # Verify persistence across reload
            reloaded = LossLearningEngine(state_path=path)
            self.assertEqual(len(reloaded.lessons), 1)
            self.assertEqual(reloaded.stop_width_mult, engine.stop_width_mult)

    def test_orderbook_imbalance_trap_enables_conviction_filter(self):
        engine = LossLearningEngine(state_path="")
        lesson = engine.record_trade_close(
            pair="btc_jpy",
            side="short",
            entry_equity_jpy=100000.0,
            exit_equity_jpy=98800.0,
            hold_duration_sec=400.0,
            entry_conviction=0.80,
            depth_ratio=2.3,
            macro_bias="BEARISH",
        )
        self.assertEqual(lesson.root_cause, "ORDERBOOK_IMBALANCE_TRAP")
        self.assertTrue(engine.orderbook_penalty_active)
        self.assertLess(engine.adjust_signal_conviction(0.75, "short", depth_ratio=2.1), 0.75)

    def test_consecutive_losses_scale_cooldown_and_win_relaxes_penalties(self):
        engine = LossLearningEngine(state_path="")
        engine.record_trade_close("sol_jpy", "short", 100000.0, 99000.0, 300.0, 0.68, 1.0, macro_bias="BEARISH")
        engine.record_trade_close("sol_jpy", "short", 99000.0, 98000.0, 300.0, 0.75, 1.0, macro_bias="BEARISH")
        self.assertEqual(engine.get_pair_cooldown_multiplier("sol_jpy"), 2.0)

        win = engine.record_trade_close("sol_jpy", "short", 98000.0, 100500.0, 600.0, 0.85, 0.8, macro_bias="BEARISH")
        self.assertFalse(win.is_loss)
        self.assertEqual(engine.pair_loss_streaks["sol_jpy"], 0)
        self.assertEqual(engine.get_pair_cooldown_multiplier("sol_jpy"), 1.0)

    def test_dashboard_scales_milestones_and_shows_in_trade_pnl(self):
        from tradingbot.dashboard.ascii_dashboard import render_ascii_dashboard
        out = render_ascii_dashboard(
            starting_budget=98874.1,
            total_equity=101000.0,
            open_positions=[{
                "pair": "xrp_jpy",
                "position_side": "short",
                "open_amount": "100.0",
                "avg_price": 155.0,
                "last_price": 150.0,
            }],
        )
        self.assertIn("2X Milestone  [¥200,000 JPY]", out)
        self.assertIn("5X Milestone  [¥500,000 JPY]", out)
        self.assertIn("10X Milestone [¥1,000,000 JPY]", out)
        self.assertIn("In-Trade Unrealized   : +¥500.0", out)


if __name__ == "__main__":
    unittest.main()
