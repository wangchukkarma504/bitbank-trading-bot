"""Tests for frequent mode: looser entries, swing-based stops, profit-lock trailing and the equity floor."""

import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.execution.directional_strategist import DirectionalSignal, DirectionalStrategist
from tradingbot.execution.position_reviewer import PositionReviewResult
from tradingbot.execution.risk_manager import RiskManager
from tradingbot.models import Candle, MarketTrendResult, RsiDivergence, TechnicalDepthResult, TrendAlignment
from tradingbot.orchestrator import TradingOrchestrator

TICKER = {"last": "290000", "buy": "289990", "sell": "290010"}


def _trend(tf: str, alignment: str, hourly_up: bool = False) -> MarketTrendResult:
    close = 290000.0
    return MarketTrendResult(
        pair="eth_jpy", timeframe=tf, ema20=close * (1.003 if hourly_up else 0.998), ema50=close,
        ema200=close * 1.02, trend_alignment=alignment, btc_regime_bullish=False, close=close,
    )


def _signal(frequent: bool, rsi: float, align_4h: str) -> DirectionalSignal:
    mtf = {"4hour": _trend("4hour", align_4h), "1hour": _trend("1hour", TrendAlignment.NEUTRAL.value, hourly_up=True),
           "15min": _trend("15min", TrendAlignment.NEUTRAL.value)}
    tech = TechnicalDepthResult(pair="eth_jpy", rsi=rsi, rsi_divergence=RsiDivergence.NONE.value, depth_ratio=1.0,
                                support_wall_px=None, resistance_wall_px=None)
    return DirectionalStrategist(frequent_mode=frequent).evaluate_pair(
        pair="eth_jpy", mtf_trend=mtf, tech_result=tech, btc_regime_bullish=False, ticker=TICKER,
    )


def _review(equity: float) -> PositionReviewResult:
    return PositionReviewResult(
        baseline_budget_jpy=20000.0, total_equity_jpy=equity, free_cash_jpy=equity, locked_cash_jpy=0.0,
        buying_power_jpy=equity * 2.0, pnl_jpy=equity - 20000.0, pnl_pct=0.0, open_positions=[],
        active_stops=[], naked_positions=[], is_fully_protected=True, open_risk_jpy=0.0,
        active_orders=[], has_query_error=False, timestamp=int(time.time() * 1000),
    )


class TestFrequentEntries(unittest.TestCase):
    def test_short_at_rsi_60_without_the_1h_gate_only_in_frequent_mode(self):
        self.assertEqual(_signal(False, 61.0, TrendAlignment.BEARISH.value).action, "NEUTRAL")
        sig = _signal(True, 61.0, TrendAlignment.BEARISH.value)
        self.assertEqual(sig.action, "SHORT")
        self.assertGreaterEqual(sig.conviction, 0.95)
        # The entry rests right beside the market (ask 290,010), not at a distant pullback level
        self.assertAlmostEqual(sig.entry_price / 290010.0, 1.0008, places=4)

    def test_dip_long_in_a_4h_uptrend_only_in_frequent_mode(self):
        self.assertNotEqual(_signal(False, 38.0, TrendAlignment.BULLISH.value).action, "LONG")
        self.assertEqual(_signal(True, 38.0, TrendAlignment.BULLISH.value).action, "LONG")

    def test_no_frequent_trade_in_the_middle_of_the_range(self):
        self.assertEqual(_signal(True, 50.0, TrendAlignment.BEARISH.value).action, "NEUTRAL")
        self.assertEqual(_signal(True, 50.0, TrendAlignment.BULLISH.value).action, "NEUTRAL")


class TestSwingStop(unittest.TestCase):
    def _candles(self, high: float, low: float):
        return [Candle(timestamp=i, open=100.0, high=high if i == 5 else 100.2, low=low if i == 7 else 99.8,
                       close=100.0, volume=1.0) for i in range(12)]

    def test_short_stop_sits_a_bit_above_the_rebound_high(self):
        s = DirectionalStrategist(frequent_mode=True)
        stop = s._swing_stop(100.0, 100.0, "short", self._candles(high=100.6, low=99.8))
        self.assertAlmostEqual(stop, 100.6 * 1.0015, places=4)  # above the swing high, not on it

    def test_long_stop_sits_a_bit_below_the_rebound_low(self):
        s = DirectionalStrategist(frequent_mode=True)
        stop = s._swing_stop(100.0, 100.0, "long", self._candles(high=100.2, low=99.3))
        self.assertAlmostEqual(stop, 99.3 * 0.9985, places=4)

    def test_stop_distance_is_clamped(self):
        s = DirectionalStrategist(frequent_mode=True)
        self.assertAlmostEqual(s._swing_stop(100.0, 100.0, "short", self._candles(high=100.05, low=99.8)), 100.4)  # min 0.4%
        self.assertAlmostEqual(s._swing_stop(100.0, 100.0, "short", self._candles(high=105.0, low=99.8)), 101.2)   # max 1.2%
        self.assertAlmostEqual(s._swing_stop(100.0, 100.0, "short", None), 101.2)                                  # no data


class TestProfitLockTrail(unittest.TestCase):
    KW = {"trail_arm_pct": 0.006, "trail_lock_pct": 0.002, "trail_dist_pct": 0.005}

    def _rm(self):
        client = MagicMock()
        client.order.side_effect = lambda **k: {"order_id": int(time.time() * 1e6) % 10**9, "status": "INACTIVE"}
        return RiskManager(client), client

    def test_short_stop_moves_to_profit_then_only_further_into_profit(self):
        rm, client = self._rm()
        pos = {"pair": "sol_jpy", "position_side": "short", "open_amount": "1.0", "amount": 1.0, "avg_price": 10000.0}
        mgr = rm.get_sync_manager("sol_jpy", client)

        self.assertIsNone(rm.evaluate_and_apply_ratchets("sol_jpy", pos, 9950.0, client=client, **self.KW))  # +0.5%: not armed
        self.assertIsNotNone(rm.evaluate_and_apply_ratchets("sol_jpy", pos, 9930.0, client=client, **self.KW))  # +0.7%
        self.assertAlmostEqual(mgr.current_stop_level, 9980.0, places=1)  # locks +0.20%: below entry = profit side
        self.assertIsNotNone(rm.evaluate_and_apply_ratchets("sol_jpy", pos, 9850.0, client=client, **self.KW))  # +1.5%
        self.assertAlmostEqual(mgr.current_stop_level, 9900.0, places=1)  # trails 0.5% behind: locks +1.0%
        self.assertIsNone(rm.evaluate_and_apply_ratchets("sol_jpy", pos, 9890.0, client=client, **self.KW))  # pullback
        self.assertAlmostEqual(mgr.current_stop_level, 9900.0, places=1)  # never loosens

    def test_long_stop_mirrors(self):
        rm, client = self._rm()
        pos = {"pair": "sol_jpy", "position_side": "long", "open_amount": "1.0", "amount": 1.0, "avg_price": 10000.0}
        mgr = rm.get_sync_manager("sol_jpy", client)
        rm.evaluate_and_apply_ratchets("sol_jpy", pos, 10070.0, client=client, **self.KW)
        self.assertAlmostEqual(mgr.current_stop_level, 10020.0, places=1)
        rm.evaluate_and_apply_ratchets("sol_jpy", pos, 10150.0, client=client, **self.KW)
        self.assertAlmostEqual(mgr.current_stop_level, 10100.0, places=1)

    def test_tiny_improvements_do_not_churn_orders(self):
        rm, client = self._rm()
        pos = {"pair": "sol_jpy", "position_side": "short", "open_amount": "1.0", "amount": 1.0, "avg_price": 10000.0}
        rm.evaluate_and_apply_ratchets("sol_jpy", pos, 9850.0, client=client, **self.KW)
        self.assertIsNone(rm.evaluate_and_apply_ratchets("sol_jpy", pos, 9848.0, client=client, **self.KW))  # 0.02% better


class TestModeSwitchAndFloor(unittest.TestCase):
    def _orch(self, **kw) -> TradingOrchestrator:
        client = MagicMock()
        client.order.return_value = {"order_id": 1, "status": "UNFILLED"}
        orch = TradingOrchestrator(client=client, baseline_budget_jpy=20000.0, mode="live", pairs=["eth_jpy"], **kw)
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.dashboard.render = MagicMock(return_value="OK")
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=DirectionalSignal(
            pair="eth_jpy", action="SHORT", position_type="margin", conviction=0.95,
            entry_price=290000.0, stop_loss_price=292000.0, take_profit_price=281300.0,
        ))
        return orch

    def test_frequent_mode_halves_risk_and_can_be_switched_back(self):
        orch = self._orch(frequent_mode=True)
        self.assertTrue(orch.directional_strategist.frequent_mode)
        self.assertAlmostEqual(orch.risk_manager.MAX_RISK_PCT_PER_TRADE, 0.010)
        self.assertEqual(orch.MAX_CONSECUTIVE_LOSSES, 3)
        orch.set_frequent_mode(False)
        self.assertFalse(orch.directional_strategist.frequent_mode)
        self.assertAlmostEqual(orch.risk_manager.MAX_RISK_PCT_PER_TRADE, 0.020)
        self.assertEqual(orch.MAX_CONSECUTIVE_LOSSES, 2)

    def test_operator_leverage_override_uses_the_full_exchange_limit(self):
        orch = self._orch(frequent_mode=True)
        orch.set_sizing_overrides(leverage=2.0, max_risk_pct=1.0)
        rm = orch.risk_manager
        self.assertAlmostEqual(rm.SHORT_LEVERAGE_FACTOR, 1.95)  # 2.0x requested, capped at what the exchange fits
        plan = rm.create_sizing_plan(equity_jpy=19000.0, pair="eth_jpy", side="sell", entry_price=290000.0,
                                     stop_loss_price=290000.0 * 1.012, take_profit_price=281300.0)
        self.assertGreater(plan.allocation_notional_jpy, 19000.0 * 1.90)
        self.assertLessEqual(plan.allocation_notional_jpy, 19000.0 * 1.95)
        orch.set_frequent_mode(False)  # the override survives a mode switch
        self.assertAlmostEqual(rm.SHORT_LEVERAGE_FACTOR, 1.95)
        orch.set_sizing_overrides()    # and can be cleared
        self.assertAlmostEqual(rm.SHORT_LEVERAGE_FACTOR, 1.60)
        self.assertAlmostEqual(rm.MAX_RISK_PCT_PER_TRADE, 0.020)

    def test_equity_floor_blocks_new_entries(self):
        orch = self._orch(frequent_mode=True, equity_floor_jpy=15000.0)
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
