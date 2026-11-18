"""Tests for the gradual (50% / 20% / 30%) short entry."""

import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.execution.directional_strategist import DirectionalSignal
from tradingbot.execution.position_reviewer import PositionReviewResult
from tradingbot.orchestrator import TradingOrchestrator

ENTRY, STOP = 290000.0, 293480.0  # stop 1.2% above the entry


def _review(positions=None, stops=None, orders=None, naked=None) -> PositionReviewResult:
    return PositionReviewResult(
        baseline_budget_jpy=20000.0, total_equity_jpy=20000.0, free_cash_jpy=20000.0, locked_cash_jpy=0.0,
        buying_power_jpy=40000.0, pnl_jpy=0.0, pnl_pct=0.0, open_positions=positions or [],
        active_stops=stops or [], naked_positions=naked or [], is_fully_protected=not naked, open_risk_jpy=0.0,
        active_orders=orders or [], has_query_error=False, timestamp=int(time.time() * 1000),
    )


def _pos(amount: str, last: float = 290100.0, avg: float = ENTRY) -> dict:
    return {"pair": "eth_jpy", "position_side": "short", "position_type": "margin", "avg_price": avg,
            "last_price": last, "open_amount": amount, "amount": amount, "unrealized_pnl_jpy": 0.0, "notional_jpy": 0.0}


def _stop(order_id: int, amount: str, trigger: float = STOP) -> dict:
    return {"pair": "eth_jpy", "order_id": order_id, "side": "buy", "type": "stop", "status": "INACTIVE",
            "trigger_price": str(trigger), "remaining_amount": amount}


class TestGradualEntry(unittest.TestCase):
    def _orch(self, scale_in: bool = True) -> TradingOrchestrator:
        client = MagicMock()
        self._next_id = 100
        def order(**kwargs):
            self._next_id += 1
            return {"order_id": self._next_id, "status": "UNFILLED"}
        client.order.side_effect = order
        orch = TradingOrchestrator(client=client, baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"])
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.scale_in = scale_in
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.dashboard.render = MagicMock(return_value="OK")
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=DirectionalSignal(
            pair="eth_jpy", action="SHORT", position_type="margin", conviction=0.95, entry_price=ENTRY,
            stop_loss_price=STOP, take_profit_price=281300.0, rsi=64.0, trend_1h="NEUTRAL",
        ))
        return orch

    def _full_size(self) -> float:
        plain = self._orch(scale_in=False)
        plain.position_reviewer.review = MagicMock(return_value=_review())
        plain.tick()
        return float(plain.client.order.call_args.kwargs["amount"])

    def _limit_calls(self, orch):
        return [c.kwargs for c in orch.client.order.call_args_list if c.kwargs.get("type_") == "limit"]

    def test_first_order_is_half_and_adds_rest_at_better_prices_after_the_fill(self):
        full = self._full_size()
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=_review())
        orch.tick()
        first = self._limit_calls(orch)
        self.assertEqual(len(first), 1)  # nothing else rests until the first step has filled
        half = float(first[0]["amount"])
        self.assertAlmostEqual(half, full * 0.5, delta=0.0001)

        orch.position_reviewer.review = MagicMock(return_value=_review([_pos(first[0]["amount"])], [_stop(7, first[0]["amount"])]))
        orch.tick()
        adds = self._limit_calls(orch)[1:]
        self.assertEqual([a["side"] for a in adds], ["sell", "sell"])
        self.assertAlmostEqual(float(adds[0]["amount"]), full * 0.2, delta=0.0001)
        self.assertAlmostEqual(float(adds[1]["amount"]), full * 0.3, delta=0.0001)
        self.assertAlmostEqual(float(adds[0]["price"]), ENTRY + 0.35 * (STOP - ENTRY), delta=1.0)
        self.assertAlmostEqual(float(adds[1]["price"]), ENTRY + 0.65 * (STOP - ENTRY), delta=1.0)
        self.assertLessEqual(half + float(adds[0]["amount"]) + float(adds[1]["amount"]), full + 1e-9)  # never above the plan
        self.assertTrue(all(a["post_only"] for a in adds))

        orch.tick()  # adds are placed once only
        self.assertEqual(len(self._limit_calls(orch)), 3)

    def _with_resting_adds(self):
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=_review())
        orch.tick()
        amt = self._limit_calls(orch)[0]["amount"]
        orch.position_reviewer.review = MagicMock(return_value=_review([_pos(amt)], [_stop(7, amt)]))
        orch.tick()
        ids = list(orch._scale_plans["eth_jpy"]["add_ids"])
        self.assertEqual(len(ids), 2)
        old = int(time.time() * 1000) - 3_600_000
        resting = [{"pair": "eth_jpy", "order_id": i, "side": "sell", "type": "limit", "price": "291500",
                    "ordered_at": old} for i in ids]
        return orch, amt, ids, resting

    def test_adds_survive_the_stale_order_rule_while_the_position_is_open(self):
        orch, amt, ids, resting = self._with_resting_adds()
        orch.position_reviewer.review = MagicMock(return_value=_review([_pos(amt)], [_stop(7, amt)], resting))
        orch.tick()
        orch.client.cancel.assert_not_called()

    def test_adds_are_cancelled_when_the_position_is_gone(self):
        orch, amt, ids, resting = self._with_resting_adds()
        orch.position_reviewer.review = MagicMock(return_value=_review(orders=resting))
        orch.tick()
        cancelled = {c.args[1] for c in orch.client.cancel.call_args_list}
        self.assertTrue(set(ids) <= cancelled)
        self.assertNotIn("eth_jpy", orch._scale_plans)

    def test_adds_are_cancelled_before_the_stop_moves_into_profit(self):
        orch, amt, ids, resting = self._with_resting_adds()
        near_arm = ENTRY * (1 - 0.0155)  # default trail arms at +1.6%
        orch.position_reviewer.review = MagicMock(return_value=_review([_pos(amt, last=near_arm)], [_stop(7, amt)], resting))
        orch.tick()
        cancelled = {c.args[1] for c in orch.client.cancel.call_args_list}
        self.assertTrue(set(ids) <= cancelled)

    def test_stop_is_resized_at_the_planned_price_when_an_add_fills(self):
        orch, amt, ids, resting = self._with_resting_adds()
        bigger = f"{float(amt) * 1.4:.4f}"
        better_avg = ENTRY + 300.0
        pos = _pos(bigger, last=291300.0, avg=better_avg)
        naked = dict(pos, unprotected_amount=float(bigger) - float(amt), covered_amount=float(amt))
        orch.position_reviewer.review = MagicMock(return_value=_review([pos], [_stop(7, amt)], resting[1:], [naked]))
        orch.tick()
        stops = [c.kwargs for c in orch.client.order.call_args_list if c.kwargs.get("type_") == "stop"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["amount"], bigger)                    # covers the whole position
        self.assertAlmostEqual(float(stops[0]["trigger_price"]), STOP)  # not 1.2% above the new average

    def test_news_trades_and_disabled_flag_enter_in_one_step(self):
        orch = self._orch(scale_in=False)
        orch.position_reviewer.review = MagicMock(return_value=_review())
        orch.tick()
        self.assertEqual(orch._scale_plans, {})


if __name__ == "__main__":
    unittest.main()
