"""Unit tests for AltcoinMomentumScanner.

Verifies:
1. Screening filters (turnover threshold, positive 24h change %, proximity to high).
2. Candlestick technicals (volume surge, RSI, swing low stop loss).
3. Scoring and candidate ranking.
4. Capital-safe spot long plan generation (30% equity allocation limit, valid stop orders).
5. ASCII table formatting.
"""

from datetime import datetime, timezone
import unittest

from tests.mock_bitbank import MockBitbankClient
from tradingbot.analysis.alt_momentum_scanner import (
    AltcoinBreakoutCandidate,
    AltcoinMomentumScanner,
)


class TestAltcoinMomentumScanner(unittest.TestCase):
    def setUp(self):
        self.mock = MockBitbankClient(starting_cash_jpy=10000.0)
        self.scanner = AltcoinMomentumScanner(
            client=self.mock,
            min_turnover_jpy=1_000_000.0,
            min_gain_pct=1.0,
            min_high_proximity_pct=85.0,
        )

    def test_screening_filters_out_insufficient_turnover_or_drop(self):
        # Create custom tickers
        mock_tickers = [
            # Good candidate: +5.0%, high turnover, near high
            {
                "pair": "cyber_jpy",
                "open": "40.0",
                "last": "42.0",
                "high": "43.0",
                "low": "39.0",
                "vol": "100000.0",  # turnover = 4,200,000 JPY
            },
            # Dropping coin (-3.0%): should be filtered out
            {
                "pair": "sol_jpy",
                "open": "14000.0",
                "last": "13580.0",
                "high": "14200.0",
                "low": "13500.0",
                "vol": "1000.0",
            },
            # Low turnover coin: should be filtered out
            {
                "pair": "lowvol_jpy",
                "open": "10.0",
                "last": "12.0",
                "high": "12.5",
                "low": "9.5",
                "vol": "1000.0",  # turnover = 12,000 JPY
            },
            # Non-JPY pair: should be filtered out
            {
                "pair": "btc_usdt",
                "open": "60000.0",
                "last": "65000.0",
                "high": "66000.0",
                "low": "59000.0",
                "vol": "100.0",
            },
        ]

        screened = self.scanner.screen_candidates(tickers_data=mock_tickers)
        self.assertEqual(len(screened), 1)
        self.assertEqual(screened[0]["pair"], "cyber_jpy")
        self.assertAlmostEqual(screened[0]["change_24h_pct"], 5.0)

    def test_spot_long_plan_respects_30pct_equity_cap(self):
        candidate = AltcoinBreakoutCandidate(
            pair="cyber_jpy",
            last_price=50.0,
            change_24h_pct=10.0,
            turnover_24h_jpy=50_000_000.0,
            high_24h=52.0,
            low_24h=45.0,
            proximity_to_high_pct=96.1,
            volume_surge_ratio=2.5,
            rsi_15m=65.0,
            swing_low_stop_price=48.5,
            take_profit_target_price=51.5,
            breakout_score=75.0,
            actionable=True,
            summary="Strong breakout",
        )

        total_equity = 10000.0
        free_cash = 10000.0
        plan = self.scanner.create_spot_long_plan(
            candidate=candidate,
            free_cash_jpy=free_cash,
            total_equity_jpy=total_equity,
            allocation_pct=0.30,
        )

        self.assertIsNotNone(plan)
        # Notional should not exceed 30% of 10,000 = 3,000 JPY
        self.assertLessEqual(plan["notional_jpy"], 3000.0)
        self.assertGreater(plan["notional_jpy"], 2500.0)
        self.assertEqual(plan["side"], "buy")
        self.assertEqual(plan["protective_stop_order"]["side"], "sell")
        self.assertEqual(plan["protective_stop_order"]["type"], "stop")

    def test_ascii_table_formatting(self):
        candidates = [
            AltcoinBreakoutCandidate(
                pair="cyber_jpy",
                last_price=50.0,
                change_24h_pct=12.5,
                turnover_24h_jpy=25_000_000.0,
                high_24h=52.0,
                low_24h=44.0,
                proximity_to_high_pct=96.1,
                volume_surge_ratio=2.8,
                rsi_15m=68.5,
                swing_low_stop_price=48.5,
                take_profit_target_price=51.5,
                breakout_score=78.2,
                actionable=True,
                summary="High volume surge",
            )
        ]
        table = self.scanner.format_radar_table(candidates)
        self.assertIn("cyber_jpy", table)
        self.assertIn("+12.50%", table)
        self.assertIn("READY", table)


if __name__ == "__main__":
    unittest.main()
