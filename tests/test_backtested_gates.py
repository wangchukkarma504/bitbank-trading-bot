"""Tests for the backtest-derived short gate, exit geometry, risk-based sizing and daily loss limit."""

import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.execution.directional_strategist import DirectionalSignal, DirectionalStrategist
from tradingbot.execution.position_reviewer import PositionReviewResult
from tradingbot.execution.risk_manager import RiskManager
from tradingbot.models import MarketTrendResult, RsiDivergence, TechnicalDepthResult, TrendAlignment
from tradingbot.orchestrator import TradingOrchestrator


def _trend(tf: str, alignment: str, close: float = 290000.0) -> MarketTrendResult:
    return MarketTrendResult(
        pair="eth_jpy", timeframe=tf, ema20=close * 0.998, ema50=close, ema200=close * 1.02,
        trend_alignment=alignment, btc_regime_bullish=False, close=close,
    )


def _tech(rsi: float) -> TechnicalDepthResult:
    return TechnicalDepthResult(
        pair="eth_jpy", rsi=rsi, rsi_divergence=RsiDivergence.NONE.value, depth_ratio=0.60,
        support_wall_px=None, resistance_wall_px=None,
    )


def _evaluate(rsi: float, align_4h: str = TrendAlignment.BEARISH.value, hourly_up: bool = False) -> DirectionalSignal:
    hourly = _trend("1hour", TrendAlignment.NEUTRAL.value)  # helper default: 1h EMA20 below 1h EMA50
    if hourly_up:
        hourly.ema20 = hourly.ema50 * 1.003
    mtf = {
        "4hour": _trend("4hour", align_4h),
        "1hour": hourly,
        "15min": _trend("15min", TrendAlignment.BULLISH.value),
    }
    return DirectionalStrategist().evaluate_pair(
        pair="eth_jpy", mtf_trend=mtf, tech_result=_tech(rsi), btc_regime_bullish=False,
        ticker={"last": "290000", "buy": "289990", "sell": "290010"},
    )


def _review(equity: float) -> PositionReviewResult:
    return PositionReviewResult(
        baseline_budget_jpy=20000.0, total_equity_jpy=equity, free_cash_jpy=equity, locked_cash_jpy=0.0,
        buying_power_jpy=equity * 2.0, pnl_jpy=equity - 20000.0, pnl_pct=0.0, open_positions=[],
        active_stops=[], naked_positions=[], is_fully_protected=True, open_risk_jpy=0.0,
        active_orders=[], has_query_error=False, timestamp=int(time.time() * 1000),
    )


class TestShortGate(unittest.TestCase):
    def test_overbought_rally_in_4h_downtrend_is_shorted_with_wide_exits(self):
        sig = _evaluate(rsi=68.0)
        self.assertEqual(sig.action, "SHORT")
        self.assertAlmostEqual(sig.stop_loss_price / sig.entry_price, 1.012, places=4)
        self.assertAlmostEqual(sig.take_profit_price / sig.entry_price, 0.982, places=4)

    def test_no_short_below_overbought_rsi_even_with_bearish_scores(self):
        sig = _evaluate(rsi=55.0)
        self.assertEqual(sig.action, "NEUTRAL")
        self.assertTrue(any("Short gated: RSI" in r for r in sig.reasons))

    def test_no_short_when_1h_trend_is_up(self):
        sig = _evaluate(rsi=70.0, hourly_up=True)
        self.assertEqual(sig.action, "NEUTRAL")
        self.assertTrue(any("1h trend is up" in r for r in sig.reasons))

    def test_no_short_when_4h_trend_is_bullish(self):
        sig = _evaluate(rsi=75.0, align_4h=TrendAlignment.BULLISH.value)
        self.assertNotEqual(sig.action, "SHORT")

    def test_counter_trend_bounce_long_is_off_by_default(self):
        # 15m + 1h bullish inside a BTC bear regime used to qualify as a bounce long; it lost in backtest
        mtf = {tf: _trend(tf, a) for tf, a in (("4hour", TrendAlignment.BEARISH.value),
                                               ("1hour", TrendAlignment.BULLISH.value),
                                               ("15min", TrendAlignment.BULLISH.value))}
        sig = DirectionalStrategist().evaluate_pair(
            pair="eth_jpy", mtf_trend=mtf, tech_result=_tech(50.0), btc_regime_bullish=False,
            ticker={"last": "290000", "buy": "289990", "sell": "290010"},
        )
        self.assertNotEqual(sig.action, "LONG")
        self.assertFalse(DirectionalStrategist().allow_counter_trend_longs)


class TestRiskBasedSizing(unittest.TestCase):
    def test_stop_out_costs_at_most_two_percent_of_equity(self):
        rm = RiskManager(MagicMock())
        entry = 290000.0
        plan = rm.create_sizing_plan(
            equity_jpy=19000.0, pair="eth_jpy", side="sell", entry_price=entry,
            stop_loss_price=entry * 1.012, take_profit_price=entry * 0.982,
        )
        loss_at_stop = plan.allocation_notional_jpy * (0.012 + rm.STOP_EXIT_COST_PCT)
        self.assertLessEqual(loss_at_stop, 19000.0 * rm.MAX_RISK_PCT_PER_TRADE + 1.0)
        self.assertGreater(plan.allocation_notional_jpy, 19000.0 * 1.3)

    def test_leverage_never_exceeds_ceiling_on_a_tight_stop(self):
        rm = RiskManager(MagicMock())
        plan = rm.create_sizing_plan(
            equity_jpy=19000.0, pair="eth_jpy", side="sell", entry_price=290000.0,
            stop_loss_price=290000.0 * 1.002, take_profit_price=285000.0,
        )
        self.assertLessEqual(plan.allocation_notional_jpy, 19000.0 * rm.SHORT_LEVERAGE_FACTOR)


class TestDailyLossLimit(unittest.TestCase):
    def _orch(self) -> TradingOrchestrator:
        client = MagicMock()
        client.order.return_value = {"order_id": "1", "status": "UNFILLED"}
        orch = TradingOrchestrator(client=client, baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"])
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=DirectionalSignal(
            pair="eth_jpy", action="SHORT", position_type="margin", conviction=0.9,
            entry_price=290000.0, stop_loss_price=293480.0, take_profit_price=284780.0,
        ))
        return orch

    def test_three_percent_daily_loss_blocks_new_entries_until_next_day(self):
        orch = self._orch()
        now = time.time()
        orch._update_churn_guards(_review(20000.0), now)
        orch._update_churn_guards(_review(19390.0), now + 60)  # -3.05% on the day
        self.assertTrue(orch._daily_loss_halted)
        orch._peak_equity_jpy = 19390.0  # isolate from the separate peak-drawdown breaker

        orch.position_reviewer.review = MagicMock(return_value=_review(19390.0))
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)

        # A new JST day re-bases the limit and lifts the halt
        orch._update_churn_guards(_review(19390.0), now + 86400.0 + 60)
        self.assertFalse(orch._daily_loss_halted)
        self.assertAlmostEqual(orch._day_start_equity_jpy, 19390.0)

    def test_daily_state_survives_restart(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "daily_risk_state.json")
        now = time.time()
        first = TradingOrchestrator(client=MagicMock(), baseline_budget_jpy=20000.0, mode="live",
                                    pairs=["eth_jpy"], daily_state_path=path)
        first.loss_learner = LossLearningEngine(state_path="")
        first._update_churn_guards(_review(20000.0), now)
        first._update_churn_guards(_review(19300.0), now + 60)
        self.assertTrue(first._daily_loss_halted)

        restarted = TradingOrchestrator(client=MagicMock(), baseline_budget_jpy=20000.0, mode="live",
                                        pairs=["eth_jpy"], daily_state_path=path)
        self.assertTrue(restarted._daily_loss_halted)
        self.assertAlmostEqual(restarted._day_start_equity_jpy, 20000.0)

    def test_small_loss_does_not_halt(self):
        orch = self._orch()
        now = time.time()
        orch._update_churn_guards(_review(20000.0), now)
        orch._update_churn_guards(_review(19700.0), now + 60)  # -1.5%
        self.assertFalse(orch._daily_loss_halted)


class TestTradeJournal(unittest.TestCase):
    def test_closed_trade_records_entry_context_and_exit_reason(self):
        orch = TradingOrchestrator(client=MagicMock(), baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"])
        orch.loss_learner = LossLearningEngine(state_path="")
        orch._pending_entry_signals["eth_jpy"] = DirectionalSignal(
            pair="eth_jpy", action="SHORT", position_type="margin", conviction=0.8,
            entry_price=290000.0, stop_loss_price=293480.0, take_profit_price=284780.0,
            trend_alignment="BEARISH", rsi=68.5, trend_1h="BULLISH", trend_15m="BULLISH",
        )
        now = time.time()
        open_review = _review(20000.0)
        open_review.open_positions = [{"pair": "eth_jpy", "position_side": "short", "avg_price": 290000.0}]
        orch._update_churn_guards(open_review, now)
        orch._update_churn_guards(_review(19700.0), now + 600)

        lesson = orch.loss_learner.lessons[-1]
        self.assertTrue(lesson.is_loss)
        self.assertAlmostEqual(lesson.entry_rsi, 68.5)
        self.assertEqual((lesson.trend_4h, lesson.trend_1h, lesson.trend_15m), ("BEARISH", "BULLISH", "BULLISH"))
        self.assertAlmostEqual(lesson.entry_price, 290000.0)
        self.assertEqual(lesson.exit_reason, "EXCHANGE_STOP_OR_MANUAL")


class TestStressRegressions(unittest.TestCase):
    """Bugs found by driving the loop against the mock exchange with gaps, API failures and restarts."""

    def _orch(self) -> TradingOrchestrator:
        client = MagicMock()
        client.order.return_value = {"order_id": 900, "status": "UNFILLED"}
        orch = TradingOrchestrator(client=client, baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"])
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=DirectionalSignal(
            pair="eth_jpy", action="NEUTRAL", position_type="none", conviction=0.1,
            entry_price=290000.0, stop_loss_price=0.0, take_profit_price=0.0,
        ))
        return orch

    def _naked_review(self, last_px: float) -> PositionReviewResult:
        pos = {"pair": "eth_jpy", "position_side": "short", "open_amount": "0.0900", "amount": 0.09,
               "avg_price": 290000.0, "last_price": last_px, "unrealized_pnl_jpy": 0.09 * (290000.0 - last_px),
               "notional_jpy": 0.09 * last_px}
        rev = _review(20000.0)
        rev.open_positions = [pos]
        rev.naked_positions = [dict(pos, unprotected_amount=0.09)]
        return rev

    def test_filled_entry_gets_stop_at_planned_distance_from_entry_not_from_last_price(self):
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=self._naked_review(last_px=292000.0))
        orch.tick()
        stop_calls = [c for c in orch.client.order.call_args_list if c.kwargs.get("type_") == "stop"]
        self.assertEqual(len(stop_calls), 1)
        self.assertEqual(stop_calls[0].kwargs["trigger_price"], "293480")  # 290000 * 1.012, not 292000 * 1.015

    def test_unprotected_position_already_past_its_stop_is_closed_at_market(self):
        orch = self._orch()
        orch.client.margin_positions.return_value = [
            {"pair": "eth_jpy", "position_side": "short", "open_amount": "0.0900", "average_price": "290000"}
        ]
        orch.position_reviewer.review = MagicMock(return_value=self._naked_review(last_px=295000.0))
        orch.tick()
        types = [c.kwargs.get("type_") for c in orch.client.order.call_args_list]
        self.assertIn("market", types)
        self.assertNotIn("stop", types)

    def test_orphan_stop_is_cancelled_after_two_flat_reviews(self):
        orch = self._orch()

        def flat_with_stop():
            rev = _review(20000.0)
            rev.active_stops = [{"order_id": 555, "pair": "eth_jpy", "side": "buy", "type": "stop",
                                 "position_side": "short", "trigger_price": "293480", "status": "INACTIVE",
                                 "remaining_amount": "0.0900"}]
            rev.active_orders = list(rev.active_stops)
            return rev

        orch.position_reviewer.review = MagicMock(side_effect=lambda **k: flat_with_stop())
        orch.tick()
        orch.client.cancel.assert_not_called()  # first sighting: could be a race with a brand-new position
        orch.tick()
        orch.client.cancel.assert_called_once_with("eth_jpy", 555)

    def _in_profit_review(self, with_resting_close: bool) -> PositionReviewResult:
        pos = {"pair": "eth_jpy", "position_side": "short", "open_amount": "0.0900", "amount": 0.09,
               "avg_price": 290000.0, "last_price": 284000.0, "unrealized_pnl_jpy": 540.0, "notional_jpy": 25560.0}
        rev = _review(20500.0)
        rev.open_positions = [pos]
        rev.active_stops = [{"order_id": 700, "pair": "eth_jpy", "side": "buy", "type": "stop", "position_side": "short",
                             "trigger_price": "293480", "status": "INACTIVE", "remaining_amount": "0.0900"}]
        rev.active_orders = list(rev.active_stops)
        if with_resting_close:
            rev.active_orders.append({"order_id": 800, "pair": "eth_jpy", "side": "buy", "type": "limit",
                                      "price": "284000", "remaining_amount": "0.0900", "status": "UNFILLED"})
        return rev

    def test_take_profit_never_stacks_a_second_close_order(self):
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=self._in_profit_review(with_resting_close=False))
        orch.tick()
        self.assertEqual(sum(1 for c in orch.client.order.call_args_list if c.kwargs.get("type_") == "limit"), 1)

        orch.client.order.reset_mock()
        orch.position_reviewer.review = MagicMock(return_value=self._in_profit_review(with_resting_close=True))
        orch.tick()
        orch.client.order.assert_not_called()   # the resting close order is left to work
        orch.client.cancel.assert_not_called()  # and is not treated as a stale entry order

    def test_resting_take_profit_falls_back_to_market_after_the_wait(self):
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=self._in_profit_review(with_resting_close=True))
        orch.tick()
        orch._tp_limit_since["eth_jpy"] -= orch.TP_MAKER_WAIT_SEC + 5
        orch.tick()
        self.assertIn("market", [c.kwargs.get("type_") for c in orch.client.order.call_args_list])
        orch.client.cancel.assert_any_call("eth_jpy", 800)
        orch.client.cancel.assert_any_call("eth_jpy", 700)

    def test_positions_are_not_managed_on_a_failed_review(self):
        orch = self._orch()
        orch.position_reviewer.review = MagicMock(return_value=self._in_profit_review(with_resting_close=False))
        orch.tick()
        orch.client.order.reset_mock()
        orch.position_reviewer.review = MagicMock(side_effect=RuntimeError("API timeout"))
        orch.tick()
        orch.client.order.assert_not_called()

class TestNewsOverride(unittest.TestCase):
    def _signal(self, news_bias, rsi=50.0, hourly_up=True):
        hourly = _trend("1hour", TrendAlignment.NEUTRAL.value)
        if hourly_up:
            hourly.ema20 = hourly.ema50 * 1.003
        mtf = {"4hour": _trend("4hour", TrendAlignment.BEARISH.value), "1hour": hourly,
               "15min": _trend("15min", TrendAlignment.NEUTRAL.value)}
        return DirectionalStrategist().evaluate_pair(
            pair="eth_jpy", mtf_trend=mtf, tech_result=_tech(rsi), btc_regime_bullish=False,
            ticker={"last": "290000", "buy": "289990", "sell": "290010"}, news_bias=news_bias,
        )

    def test_bearish_news_forces_a_short_with_the_wide_stop_past_the_technical_gates(self):
        self.assertEqual(self._signal(None).action, "NEUTRAL")  # gated without news (RSI 50, 1h up)
        sig = self._signal("BEARISH")
        self.assertEqual(sig.action, "SHORT")
        self.assertTrue(sig.news_driven)
        self.assertAlmostEqual(sig.stop_loss_price / sig.entry_price, 1.020, places=4)
        self.assertAlmostEqual(sig.take_profit_price / sig.entry_price, 0.970, places=4)

    def test_bullish_news_forces_a_long_and_blocks_shorts(self):
        sig = self._signal("BULLISH", rsi=70.0, hourly_up=False)  # would be a short without news
        self.assertEqual(sig.action, "LONG")
        self.assertAlmostEqual(sig.stop_loss_price / sig.entry_price, 0.980, places=4)

    def test_wide_news_stop_does_not_raise_the_yen_risk(self):
        rm = RiskManager(MagicMock())
        entry = 290000.0
        plan = rm.create_sizing_plan(equity_jpy=19000.0, pair="eth_jpy", side="sell", entry_price=entry,
                                     stop_loss_price=entry * 1.020, take_profit_price=entry * 0.970)
        self.assertLessEqual(plan.allocation_notional_jpy * (0.020 + rm.STOP_EXIT_COST_PCT), 19000.0 * 0.02 + 1.0)

    def test_override_is_ignored_when_expired_stale_used_or_malformed(self):
        import json
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "news_override.json")
        orch = TradingOrchestrator(client=MagicMock(), baseline_budget_jpy=20000.0, mode="live",
                                   pairs=["eth_jpy"], news_override_path=path)
        now = time.time()

        def write(**kw):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(kw, f)

        self.assertIsNone(orch._read_news_override(now))  # no file
        write(bias="BEARISH", set_at=now - 60, expires_at=now + 3600, headline="Shock")
        self.assertEqual(orch._read_news_override(now)["bias"], "BEARISH")
        write(bias="BEARISH", set_at=now - 7200, expires_at=now - 10, headline="Old")
        self.assertIsNone(orch._read_news_override(now))  # expired
        write(bias="BEARISH", set_at=now - 6 * 3600, expires_at=now + 3600, headline="Stale")
        self.assertIsNone(orch._read_news_override(now))  # older than the hard 4 h cap
        write(bias="SIDEWAYS", set_at=now - 60, expires_at=now + 3600)
        self.assertIsNone(orch._read_news_override(now))  # unknown bias
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(orch._read_news_override(now))  # malformed

        write(bias="BEARISH", set_at=now - 60, expires_at=now + 3600, headline="Shock")
        self.assertIsNotNone(orch._read_news_override(now))
        orch._mark_news_override_used()
        self.assertIsNone(orch._read_news_override(now))  # one trade per override


if __name__ == "__main__":
    unittest.main()
