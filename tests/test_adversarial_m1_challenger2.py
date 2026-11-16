"""Adversarial stress-testing suite for Milestone 1: Market Analysis Engine (Challenger 2).

Verifies:
1. Divergence Oracle:
   - Known regular bullish divergence (Price Lower Low, RSI Higher Low in oversold)
   - Known regular bearish divergence (Price Higher High, RSI Lower High in overbought)
   - Rejection of Hidden Divergences (Hidden Bullish and Hidden Bearish)
   - Filtering of spurious neutral divergences
   - Stress-test: Intermediate noise peak masking failure mode
   - Stress-test: Temporal ordering precedence (older bearish div masks newer bullish div)
2. Wick Classification Boundary Edge Cases:
   - Exact boundary: upper_wick == 1.8 * body
   - Exact boundary: upper_wick == 1.5 * lower_wick
   - Zero-body Pure Doji varieties (gravestone, dragonfly, long-legged, flat 4-price)
   - Zero-wick Marubozu and Momentum boundary (body == 1.5 * (wicks))
3. Order Book Wall Detection:
   - Single mega-wall detection across all 20 book positions
   - Stochastic noise distributions (Uniform, Gaussian, Lognormal)
   - Competing multi-walls (maximum volume arbitration and spread proximity)
   - Pathological books (empty, zero volume)
4. Role Interface Integrity:
   - MarketTrendAnalyst.evaluate_btc_regime NameError check (btc_4h_candles)
   - Candle culling at exact boundary
   - Date format routing across all timeframes
"""

from datetime import datetime, timezone
import math
import random
import unittest

from tradingbot.models import (
    Candle,
    OrderBookDepth,
    RsiDivergence,
    TrendAlignment,
    WickType,
)
from tradingbot.analysis.market_trend import (
    MarketTrendAnalyst,
    calc_ema,
    calc_ema_series,
    cull_forming_candle,
    evaluate_btc_macro_regime,
    resolve_date_param,
    TF_SECONDS,
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
)


class TestDivergenceOracleAdversarial(unittest.TestCase):
    """Adversarial verification of detect_rsi_divergence."""

    def _make_candle(self, idx: int, open_: float, high: float, low: float, close_: float) -> Candle:
        return Candle(
            timestamp=idx * 60000,
            open=round(open_, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close_, 2),
            volume=10.0,
        )

    def test_regular_bullish_divergence_oracle_clear(self):
        """Synthetic series with verified Price Lower Low and RSI Higher Low in oversold."""
        candles = []
        px = 1000.0
        # Warm-up (15 bars)
        for i in range(15):
            candles.append(self._make_candle(i, px, px + 1, px - 1, px))

        # Steep drop to Trough 1 over 3 bars
        for i in range(15, 18):
            px -= 50.0
            candles.append(self._make_candle(i, px + 10, px + 12, px - 5, px))
        # Trough 1 at idx=17: Low = 845.0, RSI = 0.0

        # Bounce for 8 bars: rise 40 points total to 890
        for i in range(18, 26):
            px += 5.0
            candles.append(self._make_candle(i, px - 2, px + 3, px - 2, px))

        # Grinding drop for 8 bars to 826 (LOWER LOW than 845)
        for i in range(26, 34):
            px -= 8.0
            candles.append(self._make_candle(i, px + 2, px + 3, px - 2, px))
        # idx=33: Low = 824.0 (< 845.0!)

        # Bounce at 34 and 35 so idx=33 is a distinct swing low
        for i in range(34, 36):
            px += 10.0
            candles.append(self._make_candle(i, px - 2, px + 3, px - 2, px))

        closes = [c.close for c in candles]
        rsi_series = calc_rsi_series(closes, period=14)

        # Verify underlying mathematical conditions
        # 1. Price made lower low: low[33] (824.0) < low[17] (845.0)
        self.assertLess(candles[33].low, candles[17].low)
        # 2. RSI made higher low: rsi[33] (15.73) > rsi[17] (0.00)
        self.assertGreater(rsi_series[33], rsi_series[17])
        # 3. Troughs in oversold territory (<= 40)
        self.assertLessEqual(rsi_series[17], 40.0)

        div = detect_rsi_divergence(candles, rsi_series=rsi_series)
        self.assertEqual(div, RsiDivergence.BULLISH_DIV.value, "Oracle must detect clear regular bullish divergence")

    def test_regular_bearish_divergence_oracle_clear(self):
        """Synthetic series with verified Price Higher High and RSI Lower High in overbought."""
        candles = []
        px = 1000.0
        # Warmup
        for i in range(15):
            candles.append(self._make_candle(i, px, px + 1, px - 1, px))

        # Steep rally to Peak 1 over 3 bars
        for i in range(15, 18):
            px += 50.0
            candles.append(self._make_candle(i, px - 10, px + 5, px - 12, px))
        # Peak 1 at idx=17: High = 1155.0, RSI = 100.0

        # Pullback for 8 bars: drop 40 points total to 1110
        for i in range(18, 26):
            px -= 5.0
            candles.append(self._make_candle(i, px + 2, px + 2, px - 3, px))

        # Grinding rally for 8 bars to 1174 (HIGHER HIGH than 1155)
        for i in range(26, 34):
            px += 8.0
            candles.append(self._make_candle(i, px - 2, px + 2, px - 3, px))
        # idx=33: High = 1176.0 (> 1155.0!)

        # Pullback at 34 and 35 so idx=33 is a distinct swing high
        for i in range(34, 36):
            px -= 10.0
            candles.append(self._make_candle(i, px + 2, px + 2, px - 3, px))

        closes = [c.close for c in candles]
        rsi_series = calc_rsi_series(closes, period=14)

        # Verify underlying mathematical conditions
        self.assertGreater(candles[33].high, candles[17].high)
        self.assertLess(rsi_series[33], rsi_series[17])
        self.assertGreaterEqual(rsi_series[17], 60.0)

        div = detect_rsi_divergence(candles, rsi_series=rsi_series)
        self.assertEqual(div, RsiDivergence.BEARISH_DIV.value, "Oracle must detect clear regular bearish divergence")

    def test_hidden_divergences_rejected_as_none(self):
        """Hidden divergences (trend continuation) must NOT be reported as regular divergences."""
        # 1. Hidden Bullish Divergence: Price Higher Low ($L_2 > L_1$), but RSI Lower Low ($RSI_2 < RSI_1$)
        candles = []
        px = 500.0
        for i in range(20):
            candles.append(self._make_candle(i, px, px + 2, px - 2, px))

        for i in range(20, 35):
            px += 20.0
            candles.append(self._make_candle(i, px - 5, px + 5, px - 5, px))

        # Dip 1 (Low ~ 700)
        for i in range(35, 40):
            px -= 15.0
            candles.append(self._make_candle(i, px + 5, px + 5, px - 5, px))

        for i in range(40, 48):
            px += 15.0
            candles.append(self._make_candle(i, px - 5, px + 5, px - 5, px))

        # Dip 2 (Low ~ 740 > 700)
        for i in range(48, 51):
            px -= 25.0
            candles.append(self._make_candle(i, px + 5, px + 5, px - 5, px))

        div = detect_rsi_divergence(candles)
        self.assertNotEqual(div, RsiDivergence.BULLISH_DIV.value, "Hidden bullish divergence must not report BULLISH_DIV")

        # 2. Hidden Bearish Divergence: Price Lower High ($H_2 < H_1$), but RSI Higher High ($RSI_2 > RSI_1$)
        candles_bear = []
        px = 1000.0
        for i in range(20):
            candles_bear.append(self._make_candle(i, px, px + 2, px - 2, px))
        for i in range(20, 35):
            px -= 20.0
            candles_bear.append(self._make_candle(i, px + 5, px + 5, px - 5, px))
        for i in range(35, 40):
            px += 15.0
            candles_bear.append(self._make_candle(i, px - 5, px + 5, px - 5, px))
        for i in range(40, 48):
            px -= 15.0
            candles_bear.append(self._make_candle(i, px + 5, px + 5, px - 5, px))
        for i in range(48, 51):
            px += 25.0
            candles_bear.append(self._make_candle(i, px - 5, px + 5, px - 5, px))

        div_bear = detect_rsi_divergence(candles_bear)
        self.assertNotEqual(div_bear, RsiDivergence.BEARISH_DIV.value, "Hidden bearish divergence must not report BEARISH_DIV")

    def test_spurious_divergences_filtered(self):
        """Spurious divergences outside overbought/oversold bands must be rejected."""
        # Oscillate between 100 and 99 with RSI in 47-53 range, then a small higher high at 100.5
        p = [100.0, 99.0] * 15 + [100.0, 99.0, 100.5, 99.0]
        candles = [
            self._make_candle(i, p[i], p[i] + 1.0, p[i] - 1.0, p[i])
            for i in range(len(p))
        ]

        closes = [c.close for c in candles]
        rsi_series = calc_rsi_series(closes, period=14)

        # Confirm all RSI values remain strictly below overbought threshold (< 55.0)
        for r in rsi_series[-10:]:
            self.assertLess(r, 55.0)

        div = detect_rsi_divergence(candles, rsi_series=rsi_series)
        self.assertEqual(div, RsiDivergence.NONE.value, "Spurious neutral-zone divergence was not filtered out")

    def test_intermediate_noise_peak_masking_vulnerability(self):
        """Demonstrates vulnerability: An intermediate minor noise peak masks macro divergence."""
        candles = []
        px = 1000.0
        for i in range(15):
            candles.append(self._make_candle(i, px, px + 1, px - 1, px))

        # Peak 1 at idx=17: High = 1155.0, RSI = 100.0
        for i in range(15, 18):
            px += 50.0
            candles.append(self._make_candle(i, px - 10, px + 5, px - 12, px))

        # Pullback to 1100
        for i in range(18, 23):
            px -= 10.0
            candles.append(self._make_candle(i, px + 2, px + 2, px - 3, px))

        # Minor noise blip at idx=24 (Peak 2): High = 1115.0, RSI ~ 48
        px += 15.0
        candles.append(self._make_candle(23, px - 5, px + 5, px - 5, px))
        px -= 10.0
        candles.append(self._make_candle(24, px + 2, px + 2, px - 3, px))

        # Major Peak 3 at idx=30: High = 1175.0 (> 1155.0!), RSI = 72.0 (< 100.0!)
        for i in range(25, 31):
            px += 12.0
            candles.append(self._make_candle(i, px - 2, px + 3, px - 2, px))

        # Pullback at 31
        px -= 10.0
        candles.append(self._make_candle(31, px + 2, px + 2, px - 3, px))

        # With multi-candidate lookback, Peak 3 compares against Peak 1 and correctly detects BEARISH_DIV
        div = detect_rsi_divergence(candles)
        self.assertEqual(div, RsiDivergence.BEARISH_DIV.value)

    def test_temporal_ordering_precedence_vulnerability(self):
        """Verifies recency arbitration: Fresh bullish div takes precedence over older bearish div."""
        # 1. Old Bearish Div at bars 6-12 (Peak 1 at 8, Peak 2 at 12)
        # 2. Crash and New Bullish Div at bars 18-27 (Trough 1 at 18, Trough 2 at 27)
        candles = []
        for i in range(5):
            candles.append(self._make_candle(i, 1000, 1001, 999, 1000))

        # Rally to Peak 1 (bar 8)
        candles.append(self._make_candle(5, 1000, 1050, 995, 1040))
        candles.append(self._make_candle(6, 1040, 1080, 1030, 1070))
        candles.append(self._make_candle(7, 1070, 1120, 1060, 1110))
        candles.append(self._make_candle(8, 1110, 1150, 1100, 1145)) # Peak 1
        candles.append(self._make_candle(9, 1140, 1145, 1100, 1110))
        candles.append(self._make_candle(10, 1110, 1115, 1080, 1090))
        candles.append(self._make_candle(11, 1090, 1120, 1085, 1115))
        candles.append(self._make_candle(12, 1115, 1160, 1110, 1155)) # Peak 2 (H=1160 > 1150, lower RSI)
        candles.append(self._make_candle(13, 1150, 1155, 1120, 1130))

        # Crash to Trough 1 (bar 18)
        for i in range(14, 19):
            p = 1130.0 - (i - 13) * 60
            candles.append(self._make_candle(i, p + 20, p + 25, p - 5, p))

        # Bounce to bar 22
        for i in range(19, 23):
            p = 830.0 + (i - 18) * 15
            candles.append(self._make_candle(i, p - 5, p + 5, p - 5, p))

        # Drop to Trough 2 at bar 27 (lower low: 808 < 825)
        for i in range(23, 28):
            p = 890.0 - (i - 22) * 16
            candles.append(self._make_candle(i, p + 2, p + 3, p - 2, p))

        # Bounce at bar 28
        candles.append(self._make_candle(28, 810, 830, 808, 825))

        # Fresh bullish divergence at bar 27 takes precedence via recency arbitration
        div = detect_rsi_divergence(candles)
        self.assertEqual(div, RsiDivergence.BULLISH_DIV.value)


class TestWickClassificationBoundaries(unittest.TestCase):
    """Adversarial testing of wick anatomy boundary conditions."""

    def test_boundary_exactly_at_1_8x_body(self):
        """When upper_wick == 1.8 * body: Strict '>' means it is NOT BEARISH_REJECTION."""
        # body = 10.0, lower_wick = 5.0, upper_wick = 18.0 (exactly 1.8x body)
        candle_exact = Candle(1000, 100.0, 128.0, 95.0, 110.0, 10.0)
        body, upper, lower, total = decompose_candle(candle_exact)
        self.assertEqual(body, 10.0)
        self.assertEqual(upper, 18.0)
        self.assertEqual(lower, 5.0)

        # 18.0 > 1.8 * 10.0 is False
        cls_exact = classify_candle(candle_exact)
        self.assertNotEqual(cls_exact, WickType.BEARISH_REJECTION.value)
        self.assertEqual(cls_exact, WickType.NEUTRAL.value)

        # Just above 1.8x body: upper_wick = 18.01
        candle_above = Candle(1000, 100.0, 128.01, 95.0, 110.0, 10.0)
        cls_above = classify_candle(candle_above)
        self.assertEqual(cls_above, WickType.BEARISH_REJECTION.value)

    def test_boundary_exactly_at_1_5x_opposite_wick(self):
        """When upper_wick == 1.5 * lower_wick: Strict '>' means it is NOT BEARISH_REJECTION."""
        # body = 5.0, lower_wick = 10.0, upper_wick = 15.0
        candle_exact_opp = Candle(1000, 100.0, 120.0, 90.0, 105.0, 10.0)
        cls = classify_candle(candle_exact_opp)
        # Classifies as SPINNING_TOP because upper > 1.0*body and lower > 1.0*body
        self.assertEqual(cls, WickType.SPINNING_TOP.value)

        # Just above 1.5x lower_wick: upper_wick = 15.01
        candle_above_opp = Candle(1000, 100.0, 120.01, 90.0, 105.0, 10.0)
        cls_above = classify_candle(candle_above_opp)
        self.assertEqual(cls_above, WickType.BEARISH_REJECTION.value)

    def test_zero_body_pure_doji_varieties(self):
        """Test all 4 varieties of 0-body candles (open == close)."""
        # 1. Gravestone Doji: 0 body, long upper wick, 0 lower wick
        gravestone = Candle(1000, 100.0, 120.0, 100.0, 100.0, 10.0)
        self.assertEqual(classify_candle(gravestone), WickType.BEARISH_REJECTION.value)
        entry_grave = calc_recommended_entry(gravestone, WickType.BEARISH_REJECTION.value)
        self.assertEqual(entry_grave, 110.0)

        # 2. Dragonfly Doji: 0 body, 0 upper wick, long lower wick
        dragonfly = Candle(1000, 100.0, 100.0, 80.0, 100.0, 10.0)
        self.assertEqual(classify_candle(dragonfly), WickType.BULLISH_ABSORPTION.value)
        entry_dragon = calc_recommended_entry(dragonfly, WickType.BULLISH_ABSORPTION.value)
        self.assertEqual(entry_dragon, 90.0)

        # 3. Symmetric Long-Legged Doji: 0 body, equal upper and lower wicks
        long_legged = Candle(1000, 100.0, 120.0, 80.0, 100.0, 10.0)
        self.assertEqual(classify_candle(long_legged), WickType.SPINNING_TOP.value)

        # 4. Four-Price Doji (flat candle, zero range): open == high == low == close
        four_price = Candle(1000, 100.0, 100.0, 100.0, 100.0, 0.0)
        self.assertEqual(classify_candle(four_price), WickType.NEUTRAL.value)

    def test_zero_wick_marubozu_and_momentum_boundary(self):
        """Test pure 0-wick marubozu and momentum boundary (body == 1.5 * wicks)."""
        # Pure Bullish Marubozu
        marubozu = Candle(1000, 100.0, 150.0, 100.0, 150.0, 50.0)
        self.assertEqual(classify_candle(marubozu), WickType.MOMENTUM.value)
        self.assertIsNone(calc_recommended_entry(marubozu, WickType.MOMENTUM.value))

        # Exact boundary: body == 1.5 * (upper + lower)
        # upper = 10, lower = 10 (sum = 20), body = 30.0
        exact_momentum = Candle(1000, 110.0, 150.0, 100.0, 140.0, 20.0)
        self.assertEqual(classify_candle(exact_momentum), WickType.NEUTRAL.value)

        # Just above boundary: body = 30.1
        above_momentum = Candle(1000, 110.0, 150.0, 100.0, 140.1, 20.0)
        self.assertEqual(classify_candle(above_momentum), WickType.MOMENTUM.value)


class TestOrderBookWallDetectionAdversarial(unittest.TestCase):
    """Adversarial stress-testing of analyze_order_book under randomized noise vs mega-walls."""

    def test_single_mega_wall_isolation_across_all_levels(self):
        """Mega-wall placed at any of the 20 levels must be correctly identified by price and volume."""
        for wall_idx in range(20):
            random.seed(42 + wall_idx)
            bids = [(1000.0 - i * 1.0, round(1.0 + random.uniform(-0.2, 0.2), 3)) for i in range(20)]
            asks = [(1001.0 + i * 1.0, round(1.0 + random.uniform(-0.2, 0.2), 3)) for i in range(20)]

            wall_px = bids[wall_idx][0]
            wall_vol = 50.0
            bids[wall_idx] = (wall_px, wall_vol)

            (
                depth_ratio,
                sup_px,
                res_px,
                sup_vol,
                res_vol,
                total_bid,
                total_ask,
            ) = analyze_order_book(bids, asks, top_n=20)

            self.assertEqual(sup_px, wall_px, f"Failed to identify support wall price at level {wall_idx}")
            self.assertEqual(sup_vol, wall_vol, f"Failed to identify support wall volume at level {wall_idx}")
            self.assertGreater(depth_ratio, 2.0)

    def test_stochastic_noise_distributions_false_positive_rate(self):
        """Monte Carlo: Test false positive wall detection rates under different noise distributions."""
        n_trials = 500

        # Uniform U(1.0, 5.0) -> Expected 0% FP rate
        uniform_fps = 0
        random.seed(12345)
        for _ in range(n_trials):
            bids = [(100.0 - i * 0.1, random.uniform(1.0, 5.0)) for i in range(20)]
            asks = [(100.1 + i * 0.1, random.uniform(1.0, 5.0)) for i in range(20)]
            _, sup_px, res_px, _, _, _, _ = analyze_order_book(bids, asks)
            if sup_px is not None or res_px is not None:
                uniform_fps += 1
        self.assertEqual(uniform_fps, 0)

        # Gaussian N(10.0, 2.0) -> Expected 0% FP rate
        gaussian_fps = 0
        for _ in range(n_trials):
            bids = [(100.0 - i * 0.1, max(0.1, random.gauss(10.0, 2.0))) for i in range(20)]
            asks = [(100.1 + i * 0.1, max(0.1, random.gauss(10.0, 2.0))) for i in range(20)]
            _, sup_px, res_px, _, _, _, _ = analyze_order_book(bids, asks)
            if sup_px is not None or res_px is not None:
                gaussian_fps += 1
        self.assertEqual(gaussian_fps, 0)

        # Heavy-tailed Lognormal(0, 0.8) -> High FP rate (~84%) due to natural skew
        lognormal_fps = 0
        for _ in range(n_trials):
            bids = [(100.0 - i * 0.1, random.lognormvariate(0.0, 0.8)) for i in range(20)]
            asks = [(100.1 + i * 0.1, random.lognormvariate(0.0, 0.8)) for i in range(20)]
            _, sup_px, res_px, _, _, _, _ = analyze_order_book(bids, asks)
            if sup_px is not None or res_px is not None:
                lognormal_fps += 1
        fp_rate = (lognormal_fps / n_trials) * 100.0
        self.assertGreater(fp_rate, 50.0, "Empirical proof: heavy-tailed noise produces high false wall triggers")

    def test_competing_mega_walls_arbitration(self):
        """When multiple walls exist, verify max volume arbitration and distance prioritization."""
        # Case A: Level 2 has 30 BTC, Level 8 has 60 BTC -> should pick Level 8
        bids = [(100.0 - i * 0.1, 1.0) for i in range(20)]
        asks = [(100.1 + i * 0.1, 1.0) for i in range(20)]
        bids[2] = (99.8, 30.0)
        bids[8] = (99.2, 60.0)

        _, sup_px, _, sup_vol, _, _, _ = analyze_order_book(bids, asks)
        self.assertEqual(sup_px, 99.2)
        self.assertEqual(sup_vol, 60.0)

        # Case B: Level 2 has 40 BTC, Level 8 has 40 BTC (tie) -> strict > keeps first (Level 2)
        bids[8] = (99.2, 40.0)
        bids[2] = (99.8, 40.0)
        _, sup_px_tie, _, sup_vol_tie, _, _, _ = analyze_order_book(bids, asks)
        self.assertEqual(sup_px_tie, 99.8)
        self.assertEqual(sup_vol_tie, 40.0)

    def test_pathological_empty_and_zero_order_books(self):
        """Verify resilience against empty, 1-level, and zero-volume order books."""
        ratio, sup_px, res_px, sup_vol, res_vol, bid_vol, ask_vol = analyze_order_book([], [])
        self.assertEqual(ratio, 0.0)
        self.assertIsNone(sup_px)
        self.assertIsNone(res_px)
        self.assertEqual(bid_vol, 0.0)
        self.assertEqual(ask_vol, 0.0)

        zero_bids = [(100.0, 0.0), (99.0, 0.0)]
        zero_asks = [(101.0, 0.0), (102.0, 0.0)]
        ratio_z, sup_z, res_z, _, _, _, _ = analyze_order_book(zero_bids, zero_asks)
        self.assertIsNone(sup_z)
        self.assertIsNone(res_z)


class TestRoleInterfaceIntegrityAndBugs(unittest.TestCase):
    """Tests checking for execution bugs and interface edge cases."""

    def test_market_trend_evaluate_btc_regime_name_error(self):
        """Verify MarketTrendAnalyst.evaluate_btc_regime succeeds without NameError."""
        analyst = MarketTrendAnalyst()
        sample_candles = [
            Candle(i * 14400000, 100.0 + i, 105.0 + i, 95.0 + i, 102.0 + i, 10.0)
            for i in range(250)
        ]
        res = analyst.evaluate_btc_regime(btc_candles_4h=sample_candles)
        self.assertIsInstance(res, bool)

    def test_candle_culling_at_exact_boundary(self):
        """Test candle culling when current_time is exactly at the candle close boundary."""
        now_ms = 1731153600000
        candles = [
            Candle(now_ms - 900000, 100.0, 105.0, 95.0, 102.0, 10.0),
            Candle(now_ms, 102.0, 106.0, 101.0, 105.0, 5.0),
        ]

        # 899 seconds after candle open (candle still open by 1s) -> MUST CULL
        culled = cull_forming_candle(candles, "15min", current_time_sec=now_ms / 1000.0 + 899.0)
        self.assertEqual(len(culled), 1)

        # Exactly 900 seconds after candle open (candle is closed) -> DO NOT CULL
        culled_closed = cull_forming_candle(candles, "15min", current_time_sec=now_ms / 1000.0 + 900.0)
        self.assertEqual(len(culled_closed), 2)

    def test_date_formatting_resolutions(self):
        """Verify strict routing of all standard Bitbank candlestick timeframes."""
        dt = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        for tf in ("4hour", "8hour", "12hour", "1day", "1week"):
            self.assertEqual(resolve_date_param(tf, dt), "2026", f"Failed for {tf}")

        for tf in ("1min", "5min", "15min", "30min", "1hour"):
            self.assertEqual(resolve_date_param(tf, dt), "20261109", f"Failed for {tf}")


if __name__ == "__main__":
    unittest.main()
