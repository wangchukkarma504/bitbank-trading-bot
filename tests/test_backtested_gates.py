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


def _evaluate(rsi: float, align_4h: str = TrendAlignment.BEARISH.value) -> DirectionalSignal:
    mtf = {
        "4hour": _trend("4hour", align_4h),
        "1hour": _trend("1hour", TrendAlignment.BULLISH.value),
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

    def test_no_short_when_4h_trend_is_bullish(self):
        sig = _evaluate(rsi=75.0, align_4h=TrendAlignment.BULLISH.value)
        self.assertNotEqual(sig.action, "SHORT")

    def test_counter_trend_bounce_long_is_off_by_default(self):
        # 15m + 1h bullish inside a BTC bear regime used to qualify as a bounce long; it lost in backtest
        sig = _evaluate(rsi=50.0)
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
        orch.dashboard.render = MagicMock(return_value="OK")
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


if __name__ == "__main__":
    unittest.main()
