"""Adversarial stress-test suite for Milestone 1: Market Analysis Engine.

Empirically challenges:
1. Zero/flat price series, single-candle inputs, extremely small price series (< period length).
2. Huge spikes, zero body candles (dojis), zero range candles (open=high=low=close), inverted candles, extreme wick ratios.
3. Rapid oscillating sequences, NaN / None / negative volume / empty order books (0 bids, 0 asks, crossed books).
4. Wilder's RSI numerical stability over 10,000 candles with identical prices or alternating prices.
5. Division by zero in depth ratio, wick ratios, and date parameter boundary years (leap years, year transitions).
6. Production execution paths: Altcoin trend analysis and BTC macro regime gating.
"""

from datetime import datetime, date, timezone
import math
import unittest
from typing import List

from tradingbot.models import (
    Candle,
    MarketTrendResult,
    WickAnalysisResult,
    TechnicalDepthResult,
    OrderBookDepth,
    TrendAlignment,
    WickType,
    RsiDivergence,
    RegimeType,
)
from tradingbot.analysis.market_trend import (
    MarketTrendAnalyst,
    calc_ema,
    calc_ema_series,
    cull_forming_candle,
    evaluate_btc_macro_regime,
    parse_raw_ohlcv,
    resolve_date_param,
)
from tradingbot.analysis.wick_anatomy import (
    WickAnatomyAnalyst,
    calc_recommended_entry,
    calc_rolling_wick_ratio,
    classify_candle,
    decompose_candle,
    detect_exhaustion,
)
from tradingbot.analysis.technical_depth import (
    TechnicalDepthAnalyst,
    analyze_order_book,
    calc_rsi,
    calc_rsi_series,
    detect_rsi_divergence,
    parse_order_book_levels,
)
from tests.mock_bitbank import MockBitbankClient


class TestAdversarialSmallAndFlatSeries(unittest.TestCase):
    """Category 1: Zero/flat price series, single-candle inputs, < period length series."""

    def test_empty_candle_inputs_across_all_analysts(self):
        """Verify behavior with completely empty candle lists."""
        trend_analyst = MarketTrendAnalyst()
        res_trend = trend_analyst.analyze("sol_jpy", "15min", candles=[])
        self.assertEqual(res_trend.ema20, 0.0)
        self.assertEqual(res_trend.ema50, 0.0)
        self.assertEqual(res_trend.ema200, 0.0)
        self.assertEqual(res_trend.trend_alignment, TrendAlignment.NEUTRAL.value)

        wick_analyst = WickAnatomyAnalyst()
        res_wick = wick_analyst.analyze("sol_jpy", candles=[])
        self.assertEqual(res_wick.classification, WickType.NEUTRAL.value)
        self.assertFalse(res_wick.is_exhaustion)
        self.assertEqual(res_wick.up_lo_ratio, 1.0)
        self.assertIsNone(res_wick.recommended_entry)

        tech_analyst = TechnicalDepthAnalyst()
        res_tech = tech_analyst.analyze("sol_jpy", candles=[])
        self.assertEqual(res_tech.rsi, 50.0)
        self.assertEqual(res_tech.rsi_divergence, RsiDivergence.NONE.value)

    def test_single_candle_input(self):
        """Verify behavior when exactly one candle is provided."""
        c = Candle(1731153600000, 100.0, 110.0, 95.0, 105.0, 10.0)
        candles = [c]

        trend_analyst = MarketTrendAnalyst()
        res_trend = trend_analyst.analyze("sol_jpy", "15min", candles=candles, btc_regime_bullish=False)
        self.assertEqual(res_trend.ema20, 105.0)
        self.assertEqual(res_trend.ema50, 105.0)
        self.assertEqual(res_trend.ema200, 105.0)

        wick_analyst = WickAnatomyAnalyst()
        res_wick = wick_analyst.analyze("sol_jpy", candles=candles)
        self.assertFalse(res_wick.is_exhaustion)
        self.assertEqual(res_wick.classification, WickType.NEUTRAL.value)

        tech_analyst = TechnicalDepthAnalyst()
        res_tech = tech_analyst.analyze("sol_jpy", candles=candles)
        self.assertEqual(res_tech.rsi, 50.0)
        self.assertEqual(res_tech.rsi_divergence, RsiDivergence.NONE.value)

    def test_series_smaller_than_period_lengths(self):
        """Verify series with 2, 5, 13 elements (less than 14, 20, 50, 200)."""
        prices_3 = [100.0, 102.0, 104.0]
        ema_20 = calc_ema(prices_3, period=20)
        self.assertIsNotNone(ema_20)
        self.assertAlmostEqual(ema_20, (100.0 + 102.0 + 104.0) / 3.0)

        rsi_series_3 = calc_rsi_series(prices_3, period=14)
        self.assertEqual(len(rsi_series_3), 3)
        self.assertGreater(rsi_series_3[-1], 50.0)

        # 5 candles for divergence
        candles_5 = [
            Candle(i * 1000, 100.0 + i, 105.0 + i, 95.0 + i, 102.0 + i, 10.0)
            for i in range(5)
        ]
        div = detect_rsi_divergence(candles_5)
        self.assertEqual(div, RsiDivergence.NONE.value)

    def test_all_zero_flat_price_series(self):
        """Stress test with all zero prices."""
        zero_prices = [0.0] * 50
        ema_zero = calc_ema(zero_prices, period=20)
        self.assertEqual(ema_zero, 0.0)

        rsi_zero = calc_rsi(zero_prices, period=14)
        self.assertEqual(rsi_zero, 50.0)

        zero_candles = [
            Candle(i * 1000, 0.0, 0.0, 0.0, 0.0, 0.0)
            for i in range(50)
        ]
        wick_res = WickAnatomyAnalyst().analyze("btc_jpy", zero_candles)
        self.assertEqual(wick_res.classification, WickType.NEUTRAL.value)
        self.assertEqual(wick_res.body_pct, 0.0)
        self.assertEqual(wick_res.up_lo_ratio, 0.0)  # 0.0 / 1e-6 = 0.0


class TestAdversarialDegenerateCandles(unittest.TestCase):
    """Category 2: Huge spikes, zero body (dojis), zero range, inverted candles, extreme wicks."""

    def test_zero_body_dojis(self):
        """Stress test dojis where open == close."""
        # Long-legged doji: open=100, close=100, high=120, low=80
        doji_spinning = Candle(1, 100.0, 120.0, 80.0, 100.0, 10.0)
        cls_spinning = classify_candle(doji_spinning)
        self.assertEqual(cls_spinning, WickType.SPINNING_TOP.value)

        # Gravestone doji: open=100, close=100, high=130, low=100
        doji_grave = Candle(2, 100.0, 130.0, 100.0, 100.0, 10.0)
        cls_grave = classify_candle(doji_grave)
        self.assertEqual(cls_grave, WickType.BEARISH_REJECTION.value)

        # Dragonfly doji: open=100, close=100, high=100, low=70
        doji_dragon = Candle(3, 100.0, 100.0, 70.0, 100.0, 10.0)
        cls_dragon = classify_candle(doji_dragon)
        self.assertEqual(cls_dragon, WickType.BULLISH_ABSORPTION.value)

    def test_zero_range_candle(self):
        """open == high == low == close (completely flat candle)."""
        c = Candle(1, 100.0, 100.0, 100.0, 100.0, 0.0)
        body, upper, lower, total_range = decompose_candle(c)
        self.assertEqual(body, 0.0)
        self.assertEqual(upper, 0.0)
        self.assertEqual(lower, 0.0)
        self.assertEqual(total_range, 0.0)

        # classify_candle must not divide by zero and return NEUTRAL
        cls = classify_candle(c)
        self.assertEqual(cls, WickType.NEUTRAL.value)

        # analyze must not crash with ZeroDivisionError
        res = WickAnatomyAnalyst().analyze("btc_jpy", [c])
        self.assertEqual(res.classification, WickType.NEUTRAL.value)
        self.assertEqual(res.body_pct, 0.0)
        self.assertEqual(res.upper_wick_pct, 0.0)
        self.assertEqual(res.lower_wick_pct, 0.0)

    def test_inverted_candles_data_corruption(self):
        """Corrupt candle where high < low."""
        corrupt = Candle(1, open=100.0, high=80.0, low=120.0, close=100.0, volume=10.0)
        body, upper, lower, total_range = decompose_candle(corrupt)
        self.assertLess(total_range, 0.0)
        self.assertEqual(classify_candle(corrupt), WickType.NEUTRAL.value)

    def test_huge_spikes_and_numerical_extremes(self):
        """Huge spikes up to 1e12 and tiny decimals down to 1e-12."""
        spikes = [1.0, 1e12, 1.0, 1e-12, 100.0]
        ema = calc_ema(spikes, 3)
        self.assertFalse(math.isnan(ema))
        self.assertFalse(math.isinf(ema))

        rsi = calc_rsi(spikes, 3)
        self.assertFalse(math.isnan(rsi))
        self.assertFalse(math.isinf(rsi))

    def test_extreme_wick_ratios(self):
        """Upper wick massive, lower wick zero, body near zero."""
        c = Candle(1, open=100.0, high=1000000.0, low=100.0, close=100.0001, volume=1.0)
        res = WickAnatomyAnalyst().analyze("eth_jpy", [c])
        self.assertEqual(res.classification, WickType.BEARISH_REJECTION.value)
        self.assertAlmostEqual(res.upper_wick_pct, 100.0, places=1)


class TestAdversarialOscillationsAndCorruptInputs(unittest.TestCase):
    """Category 3: Rapid oscillating sequences, NaN / None / negative volume / empty order books."""

    def test_rapid_oscillations_convergence(self):
        """Rapid square wave oscillation: [100, 200, 100, 200, ...]."""
        oscillating = [100.0 if i % 2 == 0 else 200.0 for i in range(1000)]
        ema20 = calc_ema(oscillating, 20)
        # Should converge near the midpoint 150.0
        self.assertAlmostEqual(ema20, 150.0, delta=20.0)

        rsi = calc_rsi(oscillating, 14)
        # Symmetrical square wave RSI should hover near 50.0
        self.assertAlmostEqual(rsi, 50.0, delta=5.0)

    def test_parse_raw_ohlcv_corrupt_rows(self):
        """Verify parse_raw_ohlcv handling of None, string non-numbers, missing columns, NaNs."""
        rows = [
            ["100.0", "110.0", "90.0", "105.0", "10.0", 1000],  # valid
            ["invalid", "110.0", "90.0", "105.0", "10.0", 2000],  # bad float
            [None, "110.0", "90.0", "105.0", "10.0", 3000],  # None
            ["100.0", "110.0", "90.0"],  # short row
            [],  # empty row
            ["100.0", "110.0", "90.0", "105.0", "10.0", "bad_ts"],  # bad timestamp
            ["105.0", "115.0", "95.0", "110.0", "12.0", 4000],  # valid
        ]
        parsed = parse_raw_ohlcv(rows)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].timestamp, 1000)
        self.assertEqual(parsed[1].timestamp, 4000)

    def test_nan_propagation_in_raw_ohlcv(self):
        """Python float('NaN') is parsed by float() without ValueError! Check behavior."""
        row_with_nan = [["NaN", "110.0", "90.0", "105.0", "10.0", 5000]]
        parsed = parse_raw_ohlcv(row_with_nan)
        self.assertEqual(len(parsed), 1)
        self.assertTrue(math.isnan(parsed[0].open))

    def test_negative_volume_and_negative_prices_order_book(self):
        """Order book parser with negative amounts and prices."""
        raw_bids = [["-100.0", "-5.0"], ["invalid", "10"], ["95.0", "2.5"]]
        parsed = parse_order_book_levels(raw_bids)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0], (-100.0, -5.0))
        self.assertEqual(parsed[1], (95.0, 2.5))

    def test_empty_and_single_sided_order_books(self):
        """0 bids and 0 asks, single-sided books."""
        # 0 bids, 0 asks
        ratio, sup_px, res_px, sup_v, res_v, b_v, a_v = analyze_order_book([], [])
        self.assertEqual(ratio, 0.0)
        self.assertIsNone(sup_px)
        self.assertIsNone(res_px)
        self.assertEqual(b_v, 0.0)
        self.assertEqual(a_v, 0.0)

        # 1 bid, 0 asks (Zero asks)
        ratio_1b, sup_1b, _, _, _, b_v1, a_v1 = analyze_order_book([(100.0, 5.0)], [])
        self.assertAlmostEqual(ratio_1b, 5.0 / 1e-6)  # 5,000,000
        self.assertEqual(sup_1b, 100.0)
        self.assertEqual(b_v1, 5.0)
        self.assertEqual(a_v1, 0.0)

        # 0 bids, 1 ask (Zero bids)
        ratio_1a, _, res_1a, _, _, b_v2, a_v2 = analyze_order_book([], [(105.0, 5.0)])
        self.assertEqual(ratio_1a, 0.0)
        self.assertEqual(res_1a, 105.0)
        self.assertEqual(b_v2, 0.0)
        self.assertEqual(a_v2, 5.0)

    def test_crossed_order_book(self):
        """Crossed order book: bids > asks."""
        bids = [(110.0, 10.0), (109.0, 5.0)]
        asks = [(100.0, 10.0), (101.0, 5.0)]
        ratio, sup_px, res_px, _, _, b_v, a_v = analyze_order_book(bids, asks)
        self.assertEqual(ratio, 1.0)
        self.assertEqual(b_v, 15.0)
        self.assertEqual(a_v, 15.0)


class TestAdversarialWilderRsiNumericalStability(unittest.TestCase):
    """Category 4: Wilder's RSI numerical stability over 10,000 candles."""

    def test_rsi_10000_identical_prices_drift(self):
        """10,000 candles with identical constant price. Tests floating point drift."""
        const_prices = [12345.67] * 10000
        rsi_series = calc_rsi_series(const_prices, period=14)
        self.assertEqual(len(rsi_series), 10000)

        # Every point must be exactly 50.0
        self.assertEqual(rsi_series[0], 50.0)
        self.assertEqual(rsi_series[100], 50.0)
        self.assertEqual(rsi_series[5000], 50.0)
        self.assertEqual(rsi_series[-1], 50.0)

    def test_rsi_10000_alternating_prices(self):
        """10,000 alternating prices: [100.0, 101.0] * 5000."""
        alt_prices = [100.0 if i % 2 == 0 else 101.0 for i in range(10000)]
        rsi_series = calc_rsi_series(alt_prices, period=14)
        self.assertEqual(len(rsi_series), 10000)

        # In alternating +/-1 steps, Wilder's smoothing avg_gain and avg_loss converge
        # to equal values (~0.5), so RSI should oscillate stably near 50.0
        last_rsi = rsi_series[-1]
        self.assertAlmostEqual(last_rsi, 50.0, delta=2.5)

        # Test no NaNs or Infs anywhere in the 10,000 series
        for val in rsi_series:
            self.assertFalse(math.isnan(val))
            self.assertFalse(math.isinf(val))

    def test_rsi_10000_monotonic_increasing_and_decreasing(self):
        """10,000 monotonic increasing prices."""
        inc_prices = [float(i) for i in range(10000)]
        rsi_inc = calc_rsi(inc_prices, period=14)
        self.assertAlmostEqual(rsi_inc, 100.0, places=4)

        dec_prices = [float(10000 - i) for i in range(10000)]
        rsi_dec = calc_rsi(dec_prices, period=14)
        self.assertAlmostEqual(rsi_dec, 0.0, places=4)


class TestAdversarialDivisionByZeroAndDateBoundaries(unittest.TestCase):
    """Category 5: Division by zero in ratios and date parameter boundary years."""

    def test_rolling_wick_ratio_all_zero_lower_wicks(self):
        """sum_lower == 0.0 should not divide by zero due to 1e-6 epsilon."""
        candles = [
            Candle(i * 1000, open=100.0, high=120.0, low=100.0, close=100.0, volume=1.0)
            for i in range(20)
        ]
        ratio = calc_rolling_wick_ratio(candles, window=15)
        # Upper wicks = 20 * 15 = 300, lower wicks = 0.
        # ratio = 300 / 1e-6 = 300,000,000.0
        self.assertGreater(ratio, 1e7)
        self.assertFalse(math.isinf(ratio))

    def test_depth_ratio_zero_volume_asks(self):
        """Total asks volume == 0.0 should not raise ZeroDivisionError."""
        bids = [(100.0, 10.0)]
        asks = [(101.0, 0.0)]
        ratio, _, _, _, _, _, _ = analyze_order_book(bids, asks)
        self.assertAlmostEqual(ratio, 10.0 / 1e-6)

    def test_date_param_leap_year(self):
        """Test February 29 on leap years (2028, 2024)."""
        dt_leap = datetime(2028, 2, 29, 12, 34, 56, tzinfo=timezone.utc)
        self.assertEqual(resolve_date_param("4hour", dt_leap), "2028")
        self.assertEqual(resolve_date_param("15min", dt_leap), "20280229")
        self.assertEqual(resolve_date_param("1day", dt_leap), "2028")

    def test_date_param_year_transition_boundary(self):
        """Test Dec 31 23:59:59 to Jan 1 00:00:00 boundary."""
        dt_ny_eve = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(resolve_date_param("4hour", dt_ny_eve), "2026")
        self.assertEqual(resolve_date_param("15min", dt_ny_eve), "20261231")

        dt_ny_day = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(resolve_date_param("4hour", dt_ny_day), "2027")
        self.assertEqual(resolve_date_param("15min", dt_ny_day), "20270101")

    def test_date_param_with_date_object(self):
        """Pass datetime.date instead of datetime.datetime."""
        d = date(2026, 11, 9)
        self.assertEqual(resolve_date_param("4hour", d), "2026")
        self.assertEqual(resolve_date_param("15min", d), "20261109")


class TestAdversarialProductionExecutionDefects(unittest.TestCase):
    """Category 6: Production execution validation across multi-pair analysis."""

    def test_evaluate_btc_regime_name_error_defect(self):
        """Verify evaluate_btc_regime executes without NameError and returns valid boolean."""
        analyst = MarketTrendAnalyst()
        sample_candles = [
            Candle(i * 14400000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0)
            for i in range(10)
        ]
        res = analyst.evaluate_btc_regime(btc_candles_4h=sample_candles)
        self.assertIsInstance(res, bool)

    def test_altcoin_analyze_crashes_due_to_btc_regime_defect(self):
        """Verify that analyzing altcoins succeeds cleanly across pairs without NameError."""
        mock_client = MockBitbankClient()
        analyst = MarketTrendAnalyst(mock_client)

        res = analyst.analyze("sol_jpy", "15min")
        self.assertEqual(res.pair, "sol_jpy")
        self.assertEqual(res.timeframe, "15min")
        self.assertIsInstance(res.btc_regime_bullish, bool)


if __name__ == "__main__":
    unittest.main()
