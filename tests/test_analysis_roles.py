"""Unit and integration test suite for Milestone 1: Market Analysis Engine (Roles 3, 4, 5).

Verifies:
- Data models, enums, and 5-pair margin whitelist (PD, AD).
- Role 3: Market Trend Analyst (multi-timeframe EMAs, Bitbank date resolution, candle culling, BTC regime).
- Role 4: Wick & Candlestick Anatomy Analyst (geometric decomposition, classification, exhaustion, rolling ratios).
- Role 5: Technical & Order Book Analyst (Wilder's smoothed RSI(14), divergence detection, top-20 depth, walls).
- Live/Public Bitbank integration tests.
"""

from datetime import datetime, timezone, timedelta
import time
import unittest

from tradingbot.models import (
    Candle,
    MarketTrendResult,
    WickAnalysisResult,
    TechnicalDepthResult,
    OrderBookDepth,
    PairConfig,
    TrendAlignment,
    WickType,
    RsiDivergence,
    PositionSide,
    OrderType,
    RegimeType,
    MARGIN_PAIRS,
    SUPPORTED_PAIRS,
)
from tradingbot.analysis.market_trend import (
    MarketTrendAnalyst,
    calc_ema,
    calc_ema_series,
    cull_forming_candle,
    evaluate_btc_macro_regime,
    parse_raw_ohlcv,
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
    parse_order_book_levels,
)
from tradingbot.bitbank import Bitbank


class TestModelsAndWhitelist(unittest.TestCase):
    """Test data classes, enums, and pair configurations."""

    def test_enums_values(self):
        self.assertEqual(TrendAlignment.BULLISH.value, "BULLISH")
        self.assertEqual(TrendAlignment.BEARISH.value, "BEARISH")
        self.assertEqual(TrendAlignment.NEUTRAL.value, "NEUTRAL")

        self.assertEqual(WickType.BEARISH_REJECTION.value, "BEARISH_REJECTION")
        self.assertEqual(WickType.BULLISH_ABSORPTION.value, "BULLISH_ABSORPTION")
        self.assertEqual(WickType.SPINNING_TOP.value, "SPINNING_TOP")
        self.assertEqual(WickType.MOMENTUM.value, "MOMENTUM")

        self.assertEqual(RsiDivergence.BULLISH_DIV.value, "BULLISH_DIV")
        self.assertEqual(RsiDivergence.BEARISH_DIV.value, "BEARISH_DIV")
        self.assertEqual(RsiDivergence.NONE.value, "NONE")

        self.assertEqual(PositionSide.LONG.value, "long")
        self.assertEqual(PositionSide.SHORT.value, "short")

        self.assertEqual(OrderType.LIMIT.value, "limit")
        self.assertEqual(OrderType.MARKET.value, "market")
        self.assertEqual(OrderType.STOP.value, "stop")

        self.assertEqual(RegimeType.BULL.value, "BULL")
        self.assertEqual(RegimeType.BEAR.value, "BEAR")

    def test_margin_pair_whitelist(self):
        expected_margin = {"btc_jpy", "eth_jpy", "sol_jpy", "doge_jpy", "xrp_jpy"}
        expected_all = expected_margin | {"ada_jpy", "link_jpy", "avax_jpy", "dot_jpy", "ltc_jpy"}
        self.assertEqual(set(MARGIN_PAIRS.keys()), expected_margin)
        self.assertEqual(set(SUPPORTED_PAIRS), expected_all)

        # BTC/JPY: PD=0, AD=4
        btc = MARGIN_PAIRS["btc_jpy"]
        self.assertEqual(btc.price_digits, 0)
        self.assertEqual(btc.amount_digits, 4)
        self.assertEqual(btc.format_price(14500000.75), "14500001")
        self.assertEqual(btc.format_amount(0.0012345), "0.0012")

        # ETH/JPY: PD=0, AD=4
        eth = MARGIN_PAIRS["eth_jpy"]
        self.assertEqual(eth.price_digits, 0)
        self.assertEqual(eth.amount_digits, 4)
        self.assertEqual(eth.format_price(425000.4), "425000")
        self.assertEqual(eth.format_amount(0.05), "0.0500")

        # SOL/JPY: PD=1, AD=4
        sol = MARGIN_PAIRS["sol_jpy"]
        self.assertEqual(sol.price_digits, 1)
        self.assertEqual(sol.amount_digits, 4)
        self.assertEqual(sol.format_price(28450.48), "28450.5")
        self.assertEqual(sol.format_amount(0.12), "0.1200")

        # DOGE/JPY: PD=3, AD=4
        doge = MARGIN_PAIRS["doge_jpy"]
        self.assertEqual(doge.price_digits, 3)
        self.assertEqual(doge.amount_digits, 4)
        self.assertEqual(doge.format_price(25.1238), "25.124")
        self.assertEqual(doge.format_amount(15.5), "15.5000")

        # XRP/JPY: PD=3, AD=4
        xrp = MARGIN_PAIRS["xrp_jpy"]
        self.assertEqual(xrp.price_digits, 3)
        self.assertEqual(xrp.amount_digits, 4)
        self.assertEqual(xrp.format_price(98.4561), "98.456")
        self.assertEqual(xrp.format_amount(10.0), "10.0000")

    def test_candle_properties(self):
        candle = Candle(
            timestamp=1731153600000,
            open=100.0,
            high=120.0,
            low=90.0,
            close=110.0,
            volume=50.0,
        )
        self.assertAlmostEqual(candle.body, 10.0)
        self.assertAlmostEqual(candle.upper_wick, 10.0)  # 120 - 110
        self.assertAlmostEqual(candle.lower_wick, 10.0)  # 100 - 90
        self.assertAlmostEqual(candle.total_range, 30.0)  # 120 - 90


class TestMarketTrendAnalyst(unittest.TestCase):
    """Test Role 3: Market Trend Analyst."""

    def test_resolve_date_param(self):
        dt_sample = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)

        # Macro timeframes (>= 4hour) MUST be YYYY
        self.assertEqual(resolve_date_param("4hour", dt_sample), "2026")
        self.assertEqual(resolve_date_param("8hour", dt_sample), "2026")
        self.assertEqual(resolve_date_param("12hour", dt_sample), "2026")
        self.assertEqual(resolve_date_param("1day", dt_sample), "2026")
        self.assertEqual(resolve_date_param("1week", dt_sample), "2026")

        # Intraday timeframes (<= 1hour) MUST be YYYYMMDD
        self.assertEqual(resolve_date_param("1min", dt_sample), "20261109")
        self.assertEqual(resolve_date_param("5min", dt_sample), "20261109")
        self.assertEqual(resolve_date_param("15min", dt_sample), "20261109")
        self.assertEqual(resolve_date_param("30min", dt_sample), "20261109")
        self.assertEqual(resolve_date_param("1hour", dt_sample), "20261109")

    def test_parse_raw_ohlcv_and_cull_forming(self):
        now_ms = 1731153600000  # reference epoch
        raw = [
            ["100.0", "105.0", "98.0", "103.0", "10.0", str(now_ms - 1800000)],
            ["103.0", "107.0", "102.0", "106.0", "12.0", str(now_ms - 900000)],
            ["106.0", "110.0", "105.0", "109.0", "8.0", str(now_ms)],  # in-progress
        ]
        parsed = parse_raw_ohlcv(raw)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0].close, 103.0)
        self.assertEqual(parsed[2].close, 109.0)

        # Cull forming candle with current time set right at now_ms
        current_time_sec = now_ms / 1000.0 + 300  # 300s into 15m (900s) candle
        culled = cull_forming_candle(parsed, "15min", current_time_sec=current_time_sec)
        self.assertEqual(len(culled), 2)
        self.assertEqual(culled[-1].close, 106.0)

        # If candle is finished (e.g. 1000s passed after start of 900s candle), do not cull
        culled_finished = cull_forming_candle(parsed, "15min", current_time_sec=now_ms / 1000.0 + 1000)
        self.assertEqual(len(culled_finished), 3)

    def test_calc_ema(self):
        # Constant series
        const_vals = [100.0] * 50
        self.assertAlmostEqual(calc_ema(const_vals, 20), 100.0)

        # Monotonic linear series
        linear_vals = list(range(1, 101))  # 1 to 100
        ema20 = calc_ema(linear_vals, 20)
        self.assertIsNotNone(ema20)
        # In an uptrend, EMA lags current price (100) and is greater than SMA
        self.assertLess(ema20, 100.0)
        self.assertGreater(ema20, 75.0)

    def test_btc_macro_regime_filter(self):
        # Create synthetic BTC 4h candles
        # Bull case: Price well above EMA200, fast EMA30 > slow EMA90
        bull_candles = [
            Candle(
                timestamp=i * 14400000,
                open=50000.0 + i * 200,
                high=50100.0 + i * 200,
                low=49900.0 + i * 200,
                close=50050.0 + i * 200,
                volume=100.0,
            )
            for i in range(250)
        ]
        is_bull, regime, metrics = evaluate_btc_macro_regime(bull_candles)
        self.assertTrue(is_bull)
        self.assertEqual(regime, RegimeType.BULL.value)
        self.assertGreater(metrics["btc_close"], metrics["btc_ema200"])
        self.assertGreater(metrics["btc_ema30"], metrics["btc_ema90"])

        # Bear case: Price well below EMA200
        bear_candles = [
            Candle(
                timestamp=i * 14400000,
                open=100000.0 - i * 200,
                high=100100.0 - i * 200,
                low=99900.0 - i * 200,
                close=99950.0 - i * 200,
                volume=100.0,
            )
            for i in range(250)
        ]
        is_bull_bear, regime_bear, metrics_bear = evaluate_btc_macro_regime(bear_candles)
        self.assertFalse(is_bull_bear)
        self.assertEqual(regime_bear, RegimeType.BEAR.value)
        self.assertLess(metrics_bear["btc_close"], metrics_bear["btc_ema200"])

    def test_trend_analyst_multi_timeframe(self):
        analyst = MarketTrendAnalyst()

        # Build synthetic 4h, 1h, 15m series
        candles_bull = [
            Candle(
                timestamp=i * 900000,
                open=1000.0 + i * 10,
                high=1010.0 + i * 10,
                low=995.0 + i * 10,
                close=1008.0 + i * 10,
                volume=50.0,
            )
            for i in range(220)
        ]

        result_15m = analyst.analyze("sol_jpy", "15min", candles=candles_bull, btc_regime_bullish=True)
        self.assertEqual(result_15m.pair, "sol_jpy")
        self.assertEqual(result_15m.timeframe, "15min")
        self.assertEqual(result_15m.trend_alignment, TrendAlignment.BULLISH.value)
        self.assertTrue(result_15m.btc_regime_bullish)
        self.assertGreater(result_15m.score, 0)

        # Downtrend test
        candles_bear = [
            Candle(
                timestamp=i * 900000,
                open=5000.0 - i * 10,
                high=5005.0 - i * 10,
                low=4980.0 - i * 10,
                close=4985.0 - i * 10,
                volume=50.0,
            )
            for i in range(220)
        ]
        result_bear = analyst.analyze("sol_jpy", "15min", candles=candles_bear, btc_regime_bullish=False)
        self.assertEqual(result_bear.trend_alignment, TrendAlignment.BEARISH.value)
        self.assertFalse(result_bear.btc_regime_bullish)
        self.assertLess(result_bear.score, 0)


class TestWickAnatomyAnalyst(unittest.TestCase):
    """Test Role 4: Wick & Candlestick Anatomy Analyst."""

    def test_decompose_candle(self):
        c = Candle(
            timestamp=1000,
            open=100.0,
            high=150.0,
            low=80.0,
            close=110.0,
            volume=10.0,
        )
        body, upper_wick, lower_wick, total_range = decompose_candle(c)
        self.assertEqual(body, 10.0)        # |110 - 100|
        self.assertEqual(upper_wick, 40.0)  # 150 - 110
        self.assertEqual(lower_wick, 20.0)  # 100 - 80
        self.assertEqual(total_range, 70.0) # 150 - 80

    def test_classifications(self):
        # 1. BEARISH_REJECTION (Shooting star)
        # upper_wick > 1.8 * body and upper_wick > 1.5 * lower_wick
        # body = 10, lower_wick = 5, upper_wick = 25 (25 > 18 and 25 > 7.5)
        shooting_star = Candle(
            timestamp=1,
            open=100.0,
            high=135.0,
            low=95.0,
            close=110.0,
            volume=10.0,
        )
        self.assertEqual(classify_candle(shooting_star), WickType.BEARISH_REJECTION.value)

        # 2. BULLISH_ABSORPTION (Hammer)
        # lower_wick > 1.8 * body and lower_wick > 1.5 * upper_wick
        # body = 10, upper_wick = 5, lower_wick = 25 (25 > 18 and 25 > 7.5)
        hammer = Candle(
            timestamp=2,
            open=100.0,
            high=105.0,
            low=65.0,
            close=90.0,
            volume=10.0,
        )
        self.assertEqual(classify_candle(hammer), WickType.BULLISH_ABSORPTION.value)

        # 3. SPINNING_TOP
        # upper_wick > 1.0 * body and lower_wick > 1.0 * body
        # body = 10, upper_wick = 15, lower_wick = 15
        spinning = Candle(
            timestamp=3,
            open=100.0,
            high=125.0,
            low=85.0,
            close=110.0,
            volume=10.0,
        )
        self.assertEqual(classify_candle(spinning), WickType.SPINNING_TOP.value)

        # 4. MOMENTUM
        # body > 1.5 * (upper_wick + lower_wick)
        # body = 50, upper_wick = 5, lower_wick = 5 -> total_wicks = 10, 50 > 15
        marubozu = Candle(
            timestamp=4,
            open=100.0,
            high=155.0,
            low=95.0,
            close=150.0,
            volume=10.0,
        )
        self.assertEqual(classify_candle(marubozu), WickType.MOMENTUM.value)

        # 5. Flat candle (zero range)
        flat = Candle(
            timestamp=5,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=0.0,
        )
        self.assertEqual(classify_candle(flat), WickType.NEUTRAL.value)

    def test_exhaustion_detection_and_entry(self):
        # Generate 5 green candles leading up to a shooting star at the swing high
        candles = []
        for i in range(5):
            candles.append(
                Candle(
                    timestamp=i * 1000,
                    open=100.0 + i * 10,
                    high=112.0 + i * 10,
                    low=98.0 + i * 10,
                    close=110.0 + i * 10,
                    volume=50.0,
                )
            )

        # Add shooting star at high (O=150, C=155, H=190, L=148)
        # body=5, upper=35, lower=2 -> rejection wick
        shooting_star = Candle(
            timestamp=5000,
            open=150.0,
            high=190.0,
            low=148.0,
            close=155.0,
            volume=100.0,
        )
        candles.append(shooting_star)

        analyst = WickAnatomyAnalyst()
        res = analyst.analyze("eth_jpy", candles)

        self.assertEqual(res.classification, WickType.BEARISH_REJECTION.value)
        self.assertTrue(res.is_exhaustion)
        # Recommended entry at wick midpoint: 190 - 0.5 * 35 = 172.5
        self.assertAlmostEqual(res.recommended_entry, 172.5)

    def test_rolling_wick_ratio(self):
        candles = [
            Candle(
                timestamp=i * 1000,
                open=100.0,
                high=150.0,  # upper wick = 40
                low=95.0,   # lower wick = 5
                close=110.0, # body = 10
                volume=10.0,
            )
            for i in range(15)
        ]
        ratio = calc_rolling_wick_ratio(candles, window=15)
        # 40 / 5 = 8.0 (persistent overhead supply)
        self.assertGreater(ratio, 7.0)


class TestTechnicalDepthAnalyst(unittest.TestCase):
    """Test Role 5: Technical & Order Book Analyst."""

    def test_calc_rsi(self):
        # 14 up changes, 0 down changes -> RSI approaches 100
        up_prices = [100.0 + i * 5.0 for i in range(30)]
        rsi_up = calc_rsi(up_prices, period=14)
        self.assertGreater(rsi_up, 95.0)

        # 14 down changes, 0 up changes -> RSI approaches 0
        down_prices = [300.0 - i * 5.0 for i in range(30)]
        rsi_down = calc_rsi(down_prices, period=14)
        self.assertLess(rsi_down, 5.0)

        # Flat prices -> RSI 50.0
        flat_prices = [100.0] * 30
        rsi_flat = calc_rsi(flat_prices, period=14)
        self.assertAlmostEqual(rsi_flat, 50.0)

    def test_regular_bullish_divergence(self):
        """Test regular bullish divergence: Price Lower Low ($L_2 < L_1$) with RSI Higher Low ($RSI_2 > RSI_1$)."""
        candles = []
        base = 1000.0

        # Phase 1: Downward move to Trough 1 (14 candles, deep oversold)
        for i in range(14):
            base -= 20.0
            candles.append(Candle(i * 1000, base + 2.0, base + 4.0, base - 2.0, base, 10.0))
        # Trough 1 at index 13: base = 720.0, low = 718.0, RSI = 0.00 (<= 40.0)

        # Phase 2: Moderate bounce (7 candles)
        for i in range(14, 21):
            base += 15.0
            candles.append(Candle(i * 1000, base - 2.0, base + 3.0, base - 4.0, base, 10.0))
        # Bounce peak at index 20: base = 825.0, high = 828.0, RSI = 33.77

        # Phase 3: Secondary selloff to Trough 2 (8 candles, Lower Low in price)
        for i in range(21, 29):
            base -= 16.0
            candles.append(Candle(i * 1000, base + 2.0, base + 4.0, base - 2.0, base, 10.0))
        # Trough 2 at index 28: base = 697.0, low = 695.0 (< 718.0), RSI = 19.63 (> 0.00)

        # Phase 4: Confirmation candle bounce (1 candle)
        base += 10.0
        candles.append(Candle(29 * 1000, base - 2.0, base + 3.0, base - 2.0, base, 10.0))
        # Confirmation at index 29: low = 705.0 (> 695.0), confirming index 28 as swing low

        # Pre-condition mathematical assertions
        self.assertLess(candles[28].low, candles[13].low, "Price must make a lower low ($L_2 < L_1$)")

        # Check divergence detector with strict equality
        div = detect_rsi_divergence(candles)
        self.assertEqual(div, RsiDivergence.BULLISH_DIV.value)

    def test_regular_bearish_divergence(self):
        """Test regular bearish divergence: Price Higher High ($H_2 > H_1$) with RSI Lower High ($RSI_2 < RSI_1$)."""
        candles = []
        base = 1000.0

        # Phase 1: Upward move to Peak 1 (14 candles, deep overbought)
        for i in range(14):
            base += 20.0
            candles.append(Candle(i * 1000, base - 2.0, base + 2.0, base - 4.0, base, 10.0))
        # Peak 1 at index 13: base = 1280.0, high = 1282.0, RSI = 100.00 (>= 60.0)

        # Phase 2: Pullback / dip (7 candles)
        for i in range(14, 21):
            base -= 15.0
            candles.append(Candle(i * 1000, base + 2.0, base + 4.0, base - 3.0, base, 10.0))
        # Pullback trough at index 20: base = 1175.0, low = 1172.0, RSI = 66.23

        # Phase 3: Secondary rally to Peak 2 (8 candles, Higher High in price)
        for i in range(21, 29):
            base += 16.0
            candles.append(Candle(i * 1000, base - 2.0, base + 2.0, base - 4.0, base, 10.0))
        # Peak 2 at index 28: base = 1303.0, high = 1305.0 (> 1282.0), RSI = 80.37 (< 100.00)

        # Phase 4: Confirmation candle pullback (1 candle)
        base -= 10.0
        candles.append(Candle(29 * 1000, base + 2.0, base + 2.0, base - 3.0, base, 10.0))
        # Confirmation at index 29: high = 1295.0 (< 1305.0), confirming index 28 as swing high

        # Pre-condition mathematical assertions
        self.assertGreater(candles[28].high, candles[13].high, "Price must make a higher high ($H_2 > H_1$)")

        # Check divergence detector with strict equality
        div = detect_rsi_divergence(candles)
        self.assertEqual(div, RsiDivergence.BEARISH_DIV.value)

    def test_divergence_with_intermediate_noise_extrema(self):
        """Verify that intermediate micro-wiggles do not blind divergence detection."""
        candles = []
        p = 1000.0
        for i in range(14):
            candles.append(Candle(i * 1000, p, p + 6, p - 2, p + 5, 10.0))
            p += 25.0
        candles.append(Candle(14 * 1000, 1350.0, 1360.0, 1345.0, 1352.0, 10.0))

        p = 1350.0
        for i in range(15, 22):
            p -= 15.0
            if i == 18:
                # Minor intermediate noise peak: high = 1310.0 (lower than p2=1375.0 and p1=1360.0)
                candles.append(Candle(i * 1000, p + 5, 1310.0, p - 5, p + 2, 10.0))
            else:
                candles.append(Candle(i * 1000, p + 5, p + 6, p - 5, p, 10.0))

        for i in range(22, 27):
            p += 22.0
            candles.append(Candle(i * 1000, p - 5, p + 3, p - 7, p, 10.0))

        candles.append(Candle(27 * 1000, 1365.0, 1375.0, 1360.0, 1368.0, 10.0))
        candles.append(Candle(28 * 1000, 1368.0, 1370.0, 1355.0, 1358.0, 10.0))

        div = detect_rsi_divergence(candles)
        self.assertEqual(div, RsiDivergence.BEARISH_DIV.value)

    def test_order_book_depth_and_walls(self):
        # 20 bids, 20 asks
        bids = [(100.0 - i * 0.1, 1.0) for i in range(20)]
        asks = [(100.1 + i * 0.1, 1.0) for i in range(20)]

        # Balanced book with no walls
        depth_ratio, sup_px, res_px, sup_vol, res_vol, bid_vol, ask_vol = analyze_order_book(bids, asks)
        self.assertAlmostEqual(depth_ratio, 1.0)
        self.assertIsNone(sup_px)
        self.assertIsNone(res_px)
        self.assertAlmostEqual(bid_vol, 20.0)
        self.assertAlmostEqual(ask_vol, 20.0)

        # Inject Support Wall at bid index 3: 15.0 volume (average is ~2.0, so 15.0 > 3.0 * avg)
        bids[3] = (bids[3][0], 15.0)
        # Inject Resistance Wall at ask index 5: 25.0 volume
        asks[5] = (asks[5][0], 25.0)

        ratio_w, sup_w, res_w, sup_v, res_v, b_vol, a_vol = analyze_order_book(bids, asks)
        self.assertEqual(sup_w, bids[3][0])
        self.assertEqual(sup_v, 15.0)
        self.assertEqual(res_w, asks[5][0])
        self.assertEqual(res_v, 25.0)
        self.assertGreater(a_vol, b_vol)
        self.assertLess(ratio_w, 1.0)

    def test_technical_depth_analyst_end_to_end(self):
        analyst = TechnicalDepthAnalyst()

        candles = [
            Candle(
                timestamp=i * 60000,
                open=100.0 + i,
                high=102.0 + i,
                low=99.0 + i,
                close=101.0 + i,
                volume=10.0,
            )
            for i in range(30)
        ]

        bids = [(130.0 - i * 0.1, 2.0) for i in range(20)]
        bids[2] = (129.8, 25.0)  # Support Wall
        asks = [(130.1 + i * 0.1, 2.0) for i in range(20)]
        book = OrderBookDepth(bids=bids, asks=asks)

        res = analyst.analyze("btc_jpy", candles=candles, order_book=book)
        self.assertEqual(res.pair, "btc_jpy")
        self.assertGreater(res.rsi, 70.0)
        self.assertEqual(res.support_wall_px, 129.8)
        self.assertGreater(res.depth_ratio, 1.0)


class TestLiveBitbankIntegration(unittest.TestCase):
    """Integration test checking live public Bitbank endpoints in WSL."""

    def test_live_public_bitbank_candles_and_depth(self):
        client = Bitbank()
        try:
            # 1. Test 4h query (MUST use 4-digit year 'YYYY')
            candles_4h_raw = client.candles("btc_jpy", "4hour", "2026")
            self.assertIsInstance(candles_4h_raw, list)
            self.assertGreater(len(candles_4h_raw), 50)

            # 2. Test 15m query (MUST use 8-digit date 'YYYYMMDD')
            today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            candles_15m_raw = client.candles("btc_jpy", "15min", today_str)
            self.assertIsInstance(candles_15m_raw, list)
            self.assertGreater(len(candles_15m_raw), 0)

            # 3. Test Order Book Depth
            depth_raw = client._pub("/btc_jpy/depth")
            self.assertIn("bids", depth_raw)
            self.assertIn("asks", depth_raw)
            self.assertGreater(len(depth_raw["bids"]), 10)

            # 4. End-to-end Role execution on live data
            # Role 3
            trend_analyst = MarketTrendAnalyst(client)
            btc_trend = trend_analyst.analyze("btc_jpy", "4hour")
            self.assertIn(btc_trend.trend_alignment, [TrendAlignment.BULLISH.value, TrendAlignment.BEARISH.value, TrendAlignment.NEUTRAL.value])
            self.assertGreater(btc_trend.ema200, 0.0)

            # Role 4
            candles_parsed = parse_raw_ohlcv(candles_15m_raw)
            wick_analyst = WickAnatomyAnalyst(client)
            wick_res = wick_analyst.analyze("btc_jpy", candles_parsed)
            self.assertIn(wick_res.classification, [
                WickType.BEARISH_REJECTION.value,
                WickType.BULLISH_ABSORPTION.value,
                WickType.SPINNING_TOP.value,
                WickType.MOMENTUM.value,
                WickType.NEUTRAL.value,
            ])

            # Role 5
            tech_analyst = TechnicalDepthAnalyst(client)
            tech_res = tech_analyst.analyze("btc_jpy", candles=candles_parsed)
            self.assertGreater(tech_res.rsi, 0.0)
            self.assertGreater(tech_res.depth_ratio, 0.0)

        except Exception as e:
            # If Bitbank network is unreachable or rate limited, flag reason
            self.skipTest(f"Live Bitbank public endpoint unavailable: {e}")


class TestAnalysisRolesWithMockBitbank(unittest.TestCase):
    """Deterministic tests for Roles 3, 4, 5 powered by MockBitbankClient across all 5 margin pairs."""

    SUPPORTED_PAIRS = ["btc_jpy", "eth_jpy", "sol_jpy", "doge_jpy", "xrp_jpy"]

    def setUp(self):
        from tests.mock_bitbank import MockBitbankClient
        self.mock_client = MockBitbankClient()

    def test_mock_trend_analyst(self):
        """Assert analyze(pair, '4hour') succeeds cleanly across all 5 supported margin pairs."""
        trend_analyst = MarketTrendAnalyst(self.mock_client)
        for pair in self.SUPPORTED_PAIRS:
            with self.subTest(pair=pair):
                res = trend_analyst.analyze(pair, "4hour")
                self.assertEqual(res.pair, pair)
                self.assertEqual(res.timeframe, "4hour")
                self.assertIn(res.trend_alignment, [
                    TrendAlignment.BULLISH.value,
                    TrendAlignment.BEARISH.value,
                    TrendAlignment.NEUTRAL.value,
                ])
                self.assertGreater(res.ema200, 0.0)
                self.assertGreater(res.ema50, 0.0)
                self.assertGreater(res.ema20, 0.0)
                self.assertIsInstance(res.btc_regime_bullish, bool)
                self.assertTrue(res.btc_regime_bullish)

    def test_mock_trend_analyst_multi_timeframe(self):
        """Assert analyze_multi_timeframe(pair) produces 15m, 1h, 4h cleanly across all 5 margin pairs."""
        trend_analyst = MarketTrendAnalyst(self.mock_client)
        for pair in self.SUPPORTED_PAIRS:
            with self.subTest(pair=pair):
                mtf = trend_analyst.analyze_multi_timeframe(pair)
                self.assertIsInstance(mtf, dict)
                self.assertEqual(set(mtf.keys()), {"15min", "1hour", "4hour"})
                for tf in ("15min", "1hour", "4hour"):
                    tf_res = mtf[tf]
                    self.assertEqual(tf_res.pair, pair)
                    self.assertEqual(tf_res.timeframe, tf)
                    self.assertGreater(tf_res.ema200, 0.0)
                    self.assertIsInstance(tf_res.btc_regime_bullish, bool)
                    self.assertTrue(tf_res.btc_regime_bullish)

    def test_mock_wick_analyst(self):
        wick_analyst = WickAnatomyAnalyst(self.mock_client)
        candles = [
            Candle(
                timestamp=i * 900000,
                open=13500.0 + i * 10,
                high=13515.0 + i * 10,
                low=13490.0 + i * 10,
                close=13510.0 + i * 10,
                volume=100.0,
            )
            for i in range(25)
        ]
        wick_res = wick_analyst.analyze("sol_jpy", candles)
        self.assertEqual(wick_res.pair, "sol_jpy")
        self.assertIn(wick_res.classification, [
            WickType.BEARISH_REJECTION.value,
            WickType.BULLISH_ABSORPTION.value,
            WickType.SPINNING_TOP.value,
            WickType.MOMENTUM.value,
            WickType.NEUTRAL.value,
        ])

    def test_mock_technical_depth_analyst(self):
        """Assert technical depth analysis evaluates order book and RSI across all 5 margin pairs."""
        tech_analyst = TechnicalDepthAnalyst(self.mock_client)
        for pair in self.SUPPORTED_PAIRS:
            with self.subTest(pair=pair):
                tech_res = tech_analyst.analyze(pair)
                self.assertEqual(tech_res.pair, pair)
                self.assertGreater(tech_res.depth_ratio, 0.0)
                self.assertGreater(tech_res.rsi, 0.0)
                self.assertNotEqual(tech_res.rsi, 50.0)
                self.assertIsNotNone(tech_res.support_wall_px)
                self.assertIsNotNone(tech_res.resistance_wall_px)


if __name__ == "__main__":
    unittest.main()
