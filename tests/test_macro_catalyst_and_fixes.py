"""Unit tests for Macro Catalyst Predictor, Candle TTL Caching, and Stop Sync Safety Fixes."""

import unittest

from tradingbot.bitbank import BitbankError
from tradingbot.analysis.macro_catalyst import score_headlines, MacroCatalystReport
from tradingbot.analysis.market_trend import MarketTrendAnalyst
from tradingbot.execution.risk_manager import RiskManager, StopSyncManager
from tests.mock_bitbank import MockBitbankClient


class TestMacroCatalystPredictor(unittest.TestCase):
    def test_bearish_shock_nvidia_ceo_resignation(self):
        headlines = [
            ("CNBC_Tech", "NVIDIA CEO resigns suddenly amid AI valuation concerns"),
            ("CoinDesk", "Crypto liquidations spike as tech stocks plunge"),
        ]
        score, events = score_headlines(headlines)
        self.assertLess(score, -0.5)
        self.assertEqual(len(events), 2)
        self.assertIn("resign", events[0].headline.lower())

    def test_bullish_catalyst_etf_inflows_and_rate_cut(self):
        headlines = [
            ("CoinDesk", "Spot Bitcoin ETF inflow hits record $1.2B as Fed signals rate cut"),
        ]
        score, events = score_headlines(headlines)
        self.assertGreater(score, 0.4)
        self.assertEqual(len(events), 1)


class TestStopSyncSafetyAndDeduplication(unittest.TestCase):
    def test_sync_stop_does_not_panic_cover_if_existing_stop_active(self):
        client = MockBitbankClient()
        mgr = StopSyncManager(client, "btc_jpy")
        mgr.current_stop_id = 123456
        mgr.current_stop_level = 10500000.0

        # Simulate Bitbank rejecting tighter stop (e.g., transient error)
        def failing_order(*args, **kwargs):
            raise BitbankError("10009 rate limit")

        client.order = failing_order
        res = mgr.sync_stop("0.0014", 10480000.0, position_side="short")

        self.assertIsNone(res)
        self.assertFalse(mgr.emergency_covered)
        self.assertEqual(mgr.current_stop_id, 123456)

    def test_sync_stop_panic_covers_when_no_existing_stop(self):
        client = MockBitbankClient()
        mgr = StopSyncManager(client, "btc_jpy")
        mgr.current_stop_id = None  # No active stop!

        def failing_order(*args, **kwargs):
            raise BitbankError("Stop rejected")

        client.order = failing_order
        res = mgr.sync_stop("0.0014", 10550000.0, position_side="short")

        self.assertIsNone(res)
        self.assertTrue(mgr.emergency_covered)

    def test_duplicate_stops_are_cancelled(self):
        client = MockBitbankClient()
        rm = RiskManager(client)

        # Seed two active stops on mock client
        o1 = client.order(pair="btc_jpy", side="buy", amount="0.0014", type_="stop", position_side="short", trigger_price="10550000")
        o2 = client.order(pair="btc_jpy", side="buy", amount="0.0014", type_="stop", position_side="short", trigger_price="10500000")

        pos = {
            "pair": "btc_jpy",
            "position_side": "short",
            "open_amount": "0.0014",
            "average_price": "10528969",
        }
        active_stops = [
            {"order_id": o1["order_id"], "pair": "btc_jpy", "side": "buy", "status": "INACTIVE", "trigger_price": "10550000", "amount": "0.0014"},
            {"order_id": o2["order_id"], "pair": "btc_jpy", "side": "buy", "status": "INACTIVE", "trigger_price": "10500000", "amount": "0.0014"},
        ]

        rm.evaluate_and_apply_ratchets(
            pair="btc_jpy",
            position=pos,
            current_price=10480000.0,
            client=client,
            active_stops=active_stops,
        )

        # Looser stop o1 should be cancelled, tighter o2 retained
        active = client._get("/user/spot/active_orders", {"pair": "btc_jpy"})["orders"]
        remaining_ids = [o["order_id"] for o in active]
        self.assertNotIn(o1["order_id"], remaining_ids)
        self.assertIn(o2["order_id"], remaining_ids)


class TestCandleCaching(unittest.TestCase):
    def test_fetch_candles_uses_ttl_cache(self):
        client = MockBitbankClient()
        call_count = {"n": 0}
        orig_candles = client.candles

        def counting_candles(pair, tf, date_str):
            call_count["n"] += 1
            return orig_candles(pair, tf, date_str)

        client.candles = counting_candles
        analyst = MarketTrendAnalyst(client)

        analyst.fetch_candles("btc_jpy", "15min", days=1, client=client)
        first_calls = call_count["n"]
        self.assertGreater(first_calls, 0)

        analyst.fetch_candles("btc_jpy", "15min", days=1, client=client)
        self.assertEqual(call_count["n"], first_calls)


if __name__ == "__main__":
    unittest.main()
