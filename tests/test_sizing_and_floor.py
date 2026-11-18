"""Tests for the operator sizing overrides and the equity floor."""

import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.execution.directional_strategist import DirectionalSignal
from tradingbot.execution.position_reviewer import PositionReviewResult
from tradingbot.orchestrator import TradingOrchestrator


def _review(equity: float) -> PositionReviewResult:
    return PositionReviewResult(
        baseline_budget_jpy=20000.0, total_equity_jpy=equity, free_cash_jpy=equity, locked_cash_jpy=0.0,
        buying_power_jpy=equity * 2.0, pnl_jpy=equity - 20000.0, pnl_pct=0.0, open_positions=[],
        active_stops=[], naked_positions=[], is_fully_protected=True, open_risk_jpy=0.0,
        active_orders=[], has_query_error=False, timestamp=int(time.time() * 1000),
    )


class TestSizingOverridesAndFloor(unittest.TestCase):
    def _orch(self, **kw) -> TradingOrchestrator:
        client = MagicMock()
        client.order.return_value = {"order_id": 1, "status": "UNFILLED"}
        orch = TradingOrchestrator(client=client, baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"], **kw)
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=DirectionalSignal(
            pair="eth_jpy", action="SHORT", position_type="margin", conviction=0.95,
            entry_price=290000.0, stop_loss_price=292000.0, take_profit_price=281300.0,
        ))
        return orch

    def test_operator_leverage_override_uses_the_full_exchange_limit(self):
        orch = self._orch()
        rm = orch.risk_manager
        self.assertAlmostEqual(rm.SHORT_LEVERAGE_FACTOR, 1.60)
        self.assertAlmostEqual(rm.MAX_RISK_PCT_PER_TRADE, 0.020)
        orch.set_sizing_overrides(leverage=2.0, max_risk_pct=1.0)
        self.assertAlmostEqual(rm.SHORT_LEVERAGE_FACTOR, 1.95)  # 2.0x requested, capped at what the exchange fits
        plan = rm.create_sizing_plan(equity_jpy=19000.0, pair="eth_jpy", side="sell", entry_price=290000.0,
                                     stop_loss_price=290000.0 * 1.012, take_profit_price=281300.0)
        self.assertGreater(plan.allocation_notional_jpy, 19000.0 * 1.90)
        self.assertLessEqual(plan.allocation_notional_jpy, 19000.0 * 1.95)
        orch.set_sizing_overrides()  # the override can be cleared
        self.assertAlmostEqual(rm.SHORT_LEVERAGE_FACTOR, 1.60)
        self.assertAlmostEqual(rm.MAX_RISK_PCT_PER_TRADE, 0.020)

    def test_equity_floor_blocks_new_entries(self):
        orch = self._orch(equity_floor_jpy=15000.0)
        orch.position_reviewer.review = MagicMock(return_value=_review(14990.0))
        orch._day_start_equity_jpy, orch._day_key = 14990.0, time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))
        orch._peak_equity_jpy = 14990.0
        orch.tick()
        self.assertTrue(orch.equity_floor_hit)
        orch.client.order.assert_not_called()

        orch.position_reviewer.review = MagicMock(return_value=_review(15500.0))
        orch.tick()
        self.assertFalse(orch.equity_floor_hit)
        self.assertEqual(orch.client.order.call_count, 1)


if __name__ == "__main__":
    unittest.main()
