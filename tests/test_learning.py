"""Tests for the adaptive setup learner and the daily auto-tuner."""

import json
import math
import os
import random
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis import auto_tuner
from tradingbot.analysis.adaptive_learner import AdaptiveLearner
from tradingbot.analysis.auto_tuner import AutoTuner, DEFAULT_PARAMS, GRID, build_features, portfolio, simulate_pair
from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.execution.directional_strategist import DirectionalSignal
from tradingbot.execution.position_reviewer import PositionReviewResult
from tradingbot.orchestrator import TradingOrchestrator

KEY = "eth_jpy|short|rsi60-70|1h:NEUTRAL"


def _review(equity: float, positions=None) -> PositionReviewResult:
    return PositionReviewResult(
        baseline_budget_jpy=20000.0, total_equity_jpy=equity, free_cash_jpy=equity, locked_cash_jpy=0.0,
        buying_power_jpy=equity * 2.0, pnl_jpy=equity - 20000.0, pnl_pct=0.0, open_positions=positions or [],
        active_stops=[], naked_positions=[], is_fully_protected=True, open_risk_jpy=0.0,
        active_orders=[], has_query_error=False, timestamp=int(time.time() * 1000),
    )


class TestAdaptiveLearner(unittest.TestCase):
    def test_new_setups_trade_at_full_size_until_there_is_evidence(self):
        learner = AdaptiveLearner()
        for _ in range(5):
            learner.record(KEY, -2.6)
        self.assertEqual(learner.decision(KEY)[:2], (True, 1.0))  # five trades is not enough to judge

    def test_persistent_loser_is_halved_then_blocked_then_probed(self):
        learner = AdaptiveLearner()
        now = 1_000_000.0
        for i in range(6):
            learner.record(KEY, -0.6, now + i)
        allowed, mult, _ = learner.decision(KEY, now + 10)
        self.assertEqual((allowed, mult), (True, 0.5))            # mildly negative: half size
        for i in range(6):
            learner.record(KEY, -2.6, now + 20 + i)
        self.assertFalse(learner.decision(KEY, now + 60)[0])       # clearly negative: blocked
        allowed, mult, why = learner.decision(KEY, now + 60 + learner.RETEST_AFTER_SEC + 1)
        self.assertEqual((allowed, mult), (True, 0.5))             # a day later: one half-size probe
        self.assertIn("probe", why)

    def test_bucket_recovers_when_results_improve(self):
        learner = AdaptiveLearner()
        for _ in range(8):
            learner.record(KEY, -2.6)
        self.assertFalse(learner.decision(KEY)[0])
        for _ in range(30):
            learner.record(KEY, +1.0)
        self.assertEqual(learner.decision(KEY)[:2], (True, 1.0))

    def test_winning_setup_never_gets_more_than_full_size(self):
        learner = AdaptiveLearner()
        for _ in range(40):
            learner.record(KEY, +2.0)
        self.assertEqual(learner.decision(KEY)[1], 1.0)

    def test_state_survives_restart(self):
        path = os.path.join(tempfile.mkdtemp(), "learner_state.json")
        first = AdaptiveLearner(state_path=path)
        for _ in range(8):
            first.record(KEY, -2.6)
        self.assertFalse(AdaptiveLearner(state_path=path).decision(KEY)[0])


class TestLearnerInTradingLoop(unittest.TestCase):
    def _orch(self) -> TradingOrchestrator:
        client = MagicMock()
        client.order.return_value = {"order_id": 1, "status": "UNFILLED"}
        orch = TradingOrchestrator(client=client, baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"])
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.dashboard.render = MagicMock(return_value="OK")
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=DirectionalSignal(
            pair="eth_jpy", action="SHORT", position_type="margin", conviction=0.95, entry_price=290000.0,
            stop_loss_price=293480.0, take_profit_price=281300.0, rsi=64.0, trend_1h="NEUTRAL",
        ))
        return orch

    def test_closed_trade_feeds_the_learner(self):
        orch = self._orch()
        now = time.time()
        orch._pending_entry_signals["eth_jpy"] = orch.directional_strategist.evaluate_pair()
        orch._update_churn_guards(_review(20000.0, [{"pair": "eth_jpy", "position_side": "short", "avg_price": 290000.0}]), now)
        orch._update_churn_guards(_review(19800.0), now + 600)
        stats = orch.learner.buckets[KEY]
        self.assertEqual(stats.trades, 1)
        self.assertAlmostEqual(stats.total_pct, -1.0, places=3)

    def test_blocked_setup_is_not_entered_and_half_size_is_applied(self):
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=_review(20000.0))
        for _ in range(8):
            orch.learner.record(KEY, -2.6)
        orch.tick()
        orch.client.order.assert_not_called()

        orch.learner.buckets.clear()
        for _ in range(6):
            orch.learner.record(KEY, -0.6)
        orch.tick()
        full = 20000.0 * orch.risk_manager.MAX_RISK_PCT_PER_TRADE / (0.012 + orch.risk_manager.STOP_EXIT_COST_PCT) / 290000.0
        placed = float(orch.client.order.call_args.kwargs["amount"])
        self.assertAlmostEqual(placed, full / 2, delta=0.0002)

    def test_tuned_settings_reach_the_strategy_and_the_trailing_stop(self):
        orch = self._orch()
        orch.apply_tuned_params({"short_rsi_min": 65.0, "long_rsi_max": 35.0, "require_1h": True,
                                 "trail_arm_pct": 0.009, "trail_dist_pct": 0.004})
        strat = orch.directional_strategist
        self.assertEqual((strat.FREQ_SHORT_RSI_MIN, strat.FREQ_LONG_RSI_MAX, strat.freq_require_1h), (65.0, 35.0, True))
        self.assertEqual((orch.FREQ_TRAIL_ARM_PCT, orch.FREQ_TRAIL_DIST_PCT), (0.009, 0.004))


def _synthetic_history(days: int = 30, seed: int = 7, drift: float = -0.00002):
    """Deterministic 5m random walk in a downtrend, plus 4h closes that keep it below its 4h EMA200."""
    rng = random.Random(seed)
    start = 1_790_000_000_000 // 300_000 * 300_000
    px, m5 = 10000.0, []
    for i in range(days * 288):
        o = px
        px = max(100.0, px * (1 + drift + rng.gauss(0, 0.0012) + 0.004 * math.sin(i / 37.0) / 20))
        hi, lo = max(o, px) * (1 + abs(rng.gauss(0, 0.0005))), min(o, px) * (1 - abs(rng.gauss(0, 0.0005)))
        m5.append((start + i * 300_000, o, hi, lo, px))
    h4 = [(start - (300 - k) * 14_400_000, 12000.0 - k * 5.0) for k in range(300)]
    h4 += [(start + k * 14_400_000, m5[min(len(m5) - 1, k * 48)][4]) for k in range(days * 6)]
    return m5, h4


class TestAutoTuner(unittest.TestCase):
    def test_replay_produces_trades_and_respects_one_position_at_a_time(self):
        m5, h4 = _synthetic_history()
        feats = build_features(m5, h4)
        self.assertGreater(len(feats), 1000)
        trades = simulate_pair(m5, feats, dict(DEFAULT_PARAMS))
        self.assertGreater(len(trades), 5)
        for entry, exit_, res in trades:
            self.assertLessEqual(entry, exit_)
            self.assertGreaterEqual(res, -(auto_tuner.MAX_STOP + auto_tuner.STOP_COST) - 1e-9)  # loss never exceeds the stop
        count, _ = portfolio([trades, trades], m5[0][0], m5[-1][0] + 1)
        self.assertEqual(count, portfolio([trades], m5[0][0], m5[-1][0] + 1)[0])  # a duplicate pair adds no overlapping trades

    def test_tune_only_ever_returns_grid_settings_and_keeps_current_when_target_is_unreachable(self):
        history = {"btc_jpy": _synthetic_history(seed=1), "eth_jpy": _synthetic_history(seed=2)}
        tuner = AutoTuner(history_days=28, check_days=7, min_trades_per_day=1.0)
        report = tuner.tune(history=history, pause=lambda: None)
        self.assertEqual(report["status"], "ok")
        for k, allowed in GRID.items():
            self.assertIn(tuner.params[k], allowed)
        self.assertEqual(tuner.params["long_rsi_max"], 100.0 - tuner.params["short_rsi_min"])

        strict = AutoTuner(history_days=28, check_days=7, min_trades_per_day=500.0)
        report = strict.tune(history=history, pause=lambda: None)
        self.assertFalse(report["changed"])
        self.assertEqual({k: strict.params[k] for k in GRID}, {k: DEFAULT_PARAMS[k] for k in GRID})

    def test_new_setting_must_also_win_on_unseen_recent_days(self):
        history = {"btc_jpy": _synthetic_history(seed=3)}
        tuner = AutoTuner(history_days=28, check_days=7, min_trades_per_day=0.1)
        report = tuner.tune(history=history, pause=lambda: None)
        if report["changed"]:
            self.assertGreater(report["best_check"]["total_pct"], report["current_check"]["total_pct"])
        else:
            self.assertEqual({k: tuner.params[k] for k in GRID}, {k: DEFAULT_PARAMS[k] for k in GRID})

    def test_saved_state_with_off_grid_values_is_ignored(self):
        path = os.path.join(tempfile.mkdtemp(), "tuner_state.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"params": {"short_rsi_min": 20.0, "require_1h": False, "trail_arm_pct": 0.5, "trail_dist_pct": 0.004},
                       "last_run_ts": time.time()}, f)
        self.assertEqual(AutoTuner(state_path=path).params["short_rsi_min"], DEFAULT_PARAMS["short_rsi_min"])

    def test_due_once_a_day(self):
        tuner = AutoTuner()
        self.assertTrue(tuner.due())
        tuner.last_run_ts = time.time()
        self.assertFalse(tuner.due())
        self.assertTrue(tuner.due(now_ts=time.time() + 25 * 3600))


if __name__ == "__main__":
    unittest.main()
