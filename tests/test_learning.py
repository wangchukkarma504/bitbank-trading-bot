"""Tests for the adaptive setup learner."""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis.adaptive_learner import AdaptiveLearner
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


if __name__ == "__main__":
    unittest.main()
