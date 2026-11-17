"""Tests for anti-churn cooldowns and capital-preservation circuit breakers."""

import time
import unittest
from unittest.mock import MagicMock

from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.orchestrator import TradingOrchestrator
from tradingbot.execution.position_reviewer import PositionReviewResult
from tradingbot.execution.directional_strategist import DirectionalSignal


def _make_review(equity: float, open_positions=None, active_orders=None) -> PositionReviewResult:
    return PositionReviewResult(
        baseline_budget_jpy=100000.0,
        total_equity_jpy=equity,
        free_cash_jpy=equity,
        locked_cash_jpy=0.0,
        buying_power_jpy=equity * 2.0,
        pnl_jpy=equity - 100000.0,
        pnl_pct=((equity - 100000.0) / 100000.0) * 100.0,
        open_positions=open_positions or [],
        active_stops=[],
        naked_positions=[],
        is_fully_protected=True,
        open_risk_jpy=0.0,
        active_orders=active_orders or [],
        has_query_error=False,
        timestamp=int(time.time() * 1000),
    )


def _make_short_signal(pair: str = "xrp_jpy") -> DirectionalSignal:
    return DirectionalSignal(
        pair=pair,
        action="SHORT",
        position_type="margin",
        conviction=0.80,
        entry_price=155.0,
        stop_loss_price=157.0,
        take_profit_price=147.0,
        reasons=["Test short setup"],
    )


class TestAntiChurnGuards(unittest.TestCase):
    def _build_orchestrator(self) -> TradingOrchestrator:
        mock_client = MagicMock()
        mock_client.order.return_value = {"order_id": "123", "status": "UNFILLED"}
        mock_client.cancel.return_value = {}
        orch = TradingOrchestrator(
            client=mock_client,
            baseline_budget_jpy=100000.0,
            mode="live",
            pairs=["xrp_jpy"],
        )
        orch.INTER_PAIR_SLEEP_SEC = 0.0
        orch.loss_learner = LossLearningEngine(state_path="")
        orch.trend_analyst.evaluate_btc_regime = MagicMock(return_value=False)
        orch.macro_analyst.analyze = MagicMock(return_value=None)
        orch.directional_strategist.evaluate_pair = MagicMock(return_value=_make_short_signal("xrp_jpy"))
        orch.dashboard.render = MagicMock(return_value="OK")
        return orch

    def test_post_close_global_cooldown_blocks_immediate_reentry(self):
        orch = self._build_orchestrator()
        # Tick 1: Position is open on xrp_jpy
        orch.position_reviewer.review = MagicMock(
            return_value=_make_review(100000.0, open_positions=[{"pair": "xrp_jpy", "position_side": "short", "avg_price": 155.0, "last_price": 155.0, "open_amount": "100.0"}])
        )
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)

        # Tick 2: Position just closed in profit -> global 180s cooldown starts, NO immediate re-entry
        orch.position_reviewer.review = MagicMock(return_value=_make_review(101000.0, open_positions=[]))
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)
        self.assertGreater(orch._global_cooldown_until, time.time() + 100.0)

    def test_consecutive_losses_trip_circuit_breaker(self):
        orch = self._build_orchestrator()
        now = time.time()

        # Loss 1
        orch._update_churn_guards(
            _make_review(100000.0, open_positions=[{"pair": "xrp_jpy"}]), now
        )
        orch._update_churn_guards(_make_review(98500.0, open_positions=[]), now + 10)
        self.assertEqual(orch._consecutive_losses, 1)
        self.assertGreater(orch._pair_cooldown_until["xrp_jpy"], now + 800.0)
        self.assertEqual(orch._circuit_breaker_until, 0.0)

        # Loss 2 -> trips 30-min circuit breaker
        orch._update_churn_guards(
            _make_review(98500.0, open_positions=[{"pair": "btc_jpy"}]), now + 20
        )
        orch._update_churn_guards(_make_review(97000.0, open_positions=[]), now + 30)
        self.assertEqual(orch._consecutive_losses, 2)
        self.assertGreater(orch._circuit_breaker_until, now + 1700.0)

    def test_rapid_drawdown_trips_circuit_breaker(self):
        orch = self._build_orchestrator()
        now = time.time()
        orch._update_churn_guards(_make_review(100000.0), now)
        # 9% equity drop from peak -> trips 30-min circuit breaker
        orch._update_churn_guards(_make_review(91000.0), now + 5)
        self.assertGreater(orch._circuit_breaker_until, now + 1700.0)

    def test_hourly_entry_cap_trips_circuit_breaker(self):
        orch = self._build_orchestrator()
        now = time.time()
        orch._recent_entry_timestamps = [now - 200, now - 150, now - 100, now - 50, now - 10]
        orch.position_reviewer.review = MagicMock(return_value=_make_review(100000.0))
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)
        self.assertGreater(orch._circuit_breaker_until, now + 1700.0)

    def test_review_query_error_blocks_new_entry(self):
        orch = self._build_orchestrator()
        orch.position_reviewer.review = MagicMock(side_effect=RuntimeError("API timeout"))
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)

    def test_cancelling_stale_limit_defers_reentry_to_next_tick(self):
        orch = self._build_orchestrator()
        old_ts_ms = int((time.time() - 700) * 1000)
        stale_limit = {
            "order_id": "999",
            "pair": "xrp_jpy",
            "type": "limit",
            "side": "sell",
            "price": "155.0",
            "ordered_at": old_ts_ms,
        }
        orch.position_reviewer.review = MagicMock(
            return_value=_make_review(100000.0, active_orders=[stale_limit])
        )
        orch.tick()
        orch.client.cancel.assert_called_once_with("xrp_jpy", "999")
        self.assertEqual(orch.client.order.call_count, 0)

    def test_has_query_error_skips_naked_position_panic_cover(self):
        orch = self._build_orchestrator()
        review = _make_review(
            100000.0,
            open_positions=[{"pair": "xrp_jpy", "position_side": "short", "avg_price": 155.0, "last_price": 155.0, "open_amount": "100.0"}],
        )
        review.has_query_error = True
        review.naked_positions = [{"pair": "xrp_jpy", "position_side": "short", "unprotected_amount": 100.0, "last_price": 155.0}]
        orch.position_reviewer.review = MagicMock(return_value=review)
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)

    def test_zero_quantized_qty_skips_order(self):
        orch = self._build_orchestrator()
        orch._peak_equity_jpy = 1.0
        orch.position_reviewer.review = MagicMock(return_value=_make_review(1.0))
        orch.directional_strategist.evaluate_pair = MagicMock(
            return_value=DirectionalSignal(
                pair="btc_jpy",
                action="SHORT",
                position_type="margin",
                conviction=0.80,
                entry_price=10000000.0,
                stop_loss_price=10120000.0,
                take_profit_price=9760000.0,
                reasons=["Test tiny equity"],
            )
        )
        orch.pairs = ["btc_jpy"]
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 0)

    def test_valid_entry_executes_place_maker_limit_order(self):
        orch = self._build_orchestrator()
        orch.position_reviewer.review = MagicMock(return_value=_make_review(100000.0))
        orch.tick()
        self.assertEqual(orch.client.order.call_count, 1)

    def test_audit_naked_positions_accepts_remaining_amount_or_amount(self):
        from tradingbot.execution.position_reviewer import PositionReviewer
        reviewer = PositionReviewer()
        open_pos = [{"pair": "xrp_jpy", "position_side": "short", "amount": 100.0, "avg_price": 155.0, "last_price": 155.0}]
        stops = [{"pair": "xrp_jpy", "position_side": "short", "side": "buy", "status": "INACTIVE", "remaining_amount": "100.0", "trigger_price": "157.0"}]
        naked, _ = reviewer._audit_naked_positions(open_pos, stops)
        self.assertEqual(len(naked), 0)

    def test_partial_stop_coverage_attaches_full_position_amount(self):
        orch = self._build_orchestrator()
        review = _make_review(
            100000.0,
            open_positions=[{"pair": "xrp_jpy", "position_side": "short", "open_amount": "1293.0972", "amount": 1293.0972, "last_price": 153.0}],
        )
        review.naked_positions = [
            {
                "pair": "xrp_jpy",
                "position_side": "short",
                "open_amount": "1293.0972",
                "amount": 1293.0972,
                "unprotected_amount": 11.8328,
                "covered_amount": 1281.2644,
                "last_price": 153.0,
            }
        ]
        review.is_fully_protected = False
        orch.position_reviewer.review = MagicMock(return_value=review)
        orch.risk_manager.attach_protective_stop = MagicMock(return_value={"order_id": "999"})
        orch.tick()
        orch.risk_manager.attach_protective_stop.assert_called_once()
        self.assertEqual(orch.risk_manager.attach_protective_stop.call_args.kwargs["amount"], "1293.0972")

    def test_spot_only_pairs_long_only_and_never_short(self):
        from tradingbot.execution.directional_strategist import DirectionalStrategist
        from tradingbot.models import MarketTrendResult, TrendAlignment

        strategist = DirectionalStrategist(bitbank_client=None)
        bear_trend = MarketTrendResult(
            pair="ada_jpy",
            timeframe="4hour",
            ema20=80.0,
            ema50=85.0,
            ema200=100.0,
            trend_alignment=TrendAlignment.BEARISH.value,
            btc_regime_bullish=False,
            ema30=82.0,
            ema90=90.0,
            close=78.0,
        )
        sig = strategist.evaluate_pair(
            pair="ada_jpy",
            btc_regime_bullish=False,
            mtf_trend={"4hour": bear_trend, "1hour": bear_trend, "15min": bear_trend},
            ticker={"last": "78.0", "buy": "77.9", "sell": "78.1"},
        )
        self.assertEqual(sig.action, "NEUTRAL")

        orch = self._build_orchestrator()
        # Margin short on spot-only pair must raise ValueError
        with self.assertRaises(ValueError):
            orch.risk_manager.create_sizing_plan(
                pair="ada_jpy",
                side="sell",
                entry_price=80.0,
                stop_loss_price=82.0,
                take_profit_price=75.0,
                equity_jpy=100000.0,
                free_cash_jpy=100000.0,
                position_type="margin",
            )
        # Spot long on spot-only pair succeeds and passes position_side=None
        plan = orch.risk_manager.create_sizing_plan(
            pair="ada_jpy",
            side="buy",
            entry_price=80.0,
            stop_loss_price=78.0,
            take_profit_price=86.0,
            equity_jpy=100000.0,
            free_cash_jpy=100000.0,
            position_type="spot",
        )
        self.assertGreater(plan.target_amount, 0.0)
        orch.risk_manager.place_maker_limit_order(
            pair="ada_jpy",
            side="buy",
            amount=plan.formatted_amount,
            price=80.0,
            position_side=None,
        )
        orch.client.order.assert_called_once()
        self.assertIsNone(orch.client.order.call_args.kwargs.get("position_side"))

    def test_ratchet_deduplication_keeps_full_stop_over_partial_stop(self):
        orch = self._build_orchestrator()
        pos = {
            "pair": "btc_jpy",
            "position_side": "short",
            "open_amount": "0.0191",
            "amount": 0.0191,
            "avg_price": 10338244.0,
        }
        active_stops = [
            {
                "order_id": 111,
                "pair": "btc_jpy",
                "side": "buy",
                "type": "stop",
                "status": "INACTIVE",
                "remaining_amount": "0.0074",
                "trigger_price": "10493318",
            },
            {
                "order_id": 222,
                "pair": "btc_jpy",
                "side": "buy",
                "type": "stop",
                "status": "INACTIVE",
                "remaining_amount": "0.0191",
                "trigger_price": "10505820",
            },
        ]
        orch.risk_manager.evaluate_and_apply_ratchets(
            pair="btc_jpy",
            position=pos,
            current_price=10346000.0,
            client=orch.client,
            active_stops=active_stops,
        )
        # Must cancel partial stop 111 and keep full stop 222
        orch.client.cancel.assert_called_once_with("btc_jpy", 111)
        mgr = orch.risk_manager.get_sync_manager("btc_jpy", orch.client)
        self.assertEqual(mgr.current_stop_id, 222)

    def test_spot_long_detection_dust_filter_and_inprocess_stop(self):
        orch = self._build_orchestrator()
        orch.mode = "live"
        orch.dry_run = False
        orch.pairs = []
        orch.position_reviewer.spot_entry_prices["boba_jpy"] = 2.400

        def fake_get(path, params=None):
            if path == "/user/assets":
                return {
                    "assets": [
                        {"asset": "jpy", "free_amount": "80000.0", "locked_amount": "0.0"},
                        {"asset": "boba", "free_amount": "5000.0", "locked_amount": "0.0"},
                        {"asset": "mana", "free_amount": "0.0001", "locked_amount": "0.0"},  # dust
                    ]
                }
            return {"orders": []}

        orch.client._get = fake_get
        orch.client.margin_positions.return_value = []
        # 2.350 is -2.08% below 2.400 -> triggers -1.5% in-process stop for spot-only boba_jpy
        orch.client.ticker.side_effect = lambda p: {"last": "2.350"} if p == "boba_jpy" else {"last": "1.0"}

        rev = orch.position_reviewer.review(client=orch.client)
        self.assertEqual(len(rev.open_positions), 1)
        pos0 = rev.open_positions[0]
        self.assertEqual(pos0["pair"], "boba_jpy")
        self.assertEqual(pos0["position_side"], "long")
        self.assertEqual(pos0["position_type"], "spot")
        self.assertTrue(rev.is_fully_protected)

        orch.tick()
        orch.client.order.assert_called_once_with("boba_jpy", side="sell", amount="5000.0000", type_="market")

    def test_sub_minimum_sizing_returns_zero_and_baseline_resets_peak(self):
        from tradingbot.execution.risk_manager import calculate_margin_short_size, calculate_spot_long_size

        qty_m, _, not_m = calculate_margin_short_size(equity_jpy=100.0, pair="btc_jpy", entry_price=10_500_000.0)
        self.assertEqual(qty_m, 0.0)
        self.assertEqual(not_m, 0.0)

        qty_s, _, not_s = calculate_spot_long_size(
            equity_jpy=100.0, free_cash_jpy=100.0, pair="btc_jpy", entry_price=10_500_000.0
        )
        self.assertEqual(qty_s, 0.0)
        self.assertEqual(not_s, 0.0)

        # Updating baseline after a withdrawal must reset _peak_equity_jpy
        from tradingbot.server import BotController
        orch = self._build_orchestrator()
        orch._peak_equity_jpy = 150000.0
        ctrl = BotController(orch, history_path="", config_path="", env_path="", auto_start=False)
        ctrl.update_config(baseline_jpy=90000.0)
        self.assertEqual(orch._peak_equity_jpy, 90000.0)

    def test_unfilled_limits_do_not_increment_hourly_entry_cap(self):
        orch = self._build_orchestrator()
        now = time.time()
        # Simulate placing an unfilled limit order without opening a position:
        # _recent_entry_timestamps must stay empty when no position actually opens.
        orch._update_churn_guards(_make_review(100000.0, open_positions=[]), now)
        self.assertEqual(len(orch._recent_entry_timestamps), 0)

        # Once a position actually opens on the exchange, it IS counted once.
        open_pos = [{"pair": "btc_jpy", "position_side": "short", "unrealized_pnl_jpy": 0.0}]
        orch._update_churn_guards(_make_review(100000.0, open_positions=open_pos), now + 10)
        self.assertEqual(len(orch._recent_entry_timestamps), 1)

        # Subsequent ticks with the same open position do not double-count it.
        orch._update_churn_guards(_make_review(100000.0, open_positions=open_pos), now + 20)
        self.assertEqual(len(orch._recent_entry_timestamps), 1)


if __name__ == "__main__":
    unittest.main()
