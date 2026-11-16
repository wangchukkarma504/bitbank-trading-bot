"""Technical & Order Book Analyst (Role 5).

Computes Wilder's smoothed RSI(14), detects regular Bullish & Bearish momentum divergences,
calculates top-20 order book depth ratios, and identifies Support and Resistance liquidity walls.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Union

from tradingbot.models import Candle, OrderBookDepth, RsiDivergence, TechnicalDepthResult
from tradingbot.analysis.market_trend import (
    parse_raw_ohlcv,
    cull_forming_candle,
    resolve_date_param,
    TF_SECONDS,
)


def calc_rsi_series(prices: List[float], period: int = 14) -> List[float]:
    """Compute Wilder's smoothed RSI series across a list of prices.

    Uses initial 14-period SMA of gains/losses as seed, followed by Wilder's
    exponential smoothing: avg = (prev_avg * 13 + current) / 14.
    """
    if not prices or len(prices) < 2:
        return [50.0] * len(prices) if prices else []

    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    rsi_series: List[float] = [50.0]  # First point has no change

    if len(changes) < period:
        # Fallback for short series: cumulative SMA
        for i in range(1, len(prices)):
            sub_g = gains[:i]
            sub_l = losses[:i]
            avg_g = sum(sub_g) / i
            avg_l = sum(sub_l) / i
            if avg_l == 0.0 and avg_g == 0.0:
                rsi_series.append(50.0)
            elif avg_l == 0.0:
                rsi_series.append(100.0)
            else:
                rs = avg_g / (avg_l + 1e-9)
                rsi_series.append(100.0 - (100.0 / (1.0 + rs)))
        return rsi_series

    # Initial SMA seed over first `period` changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Fill intermediate indices prior to first complete period
    for i in range(1, period):
        sub_g = gains[:i]
        sub_l = losses[:i]
        ag = sum(sub_g) / i
        al = sum(sub_l) / i
        if al == 0.0 and ag == 0.0:
            rsi_series.append(50.0)
        elif al == 0.0:
            rsi_series.append(100.0)
        else:
            rs = ag / (al + 1e-9)
            rsi_series.append(100.0 - (100.0 / (1.0 + rs)))

    # Compute period-th RSI
    if avg_loss == 0.0 and avg_gain == 0.0:
        first_rsi = 50.0
    elif avg_loss == 0.0:
        first_rsi = 100.0
    else:
        rs = avg_gain / (avg_loss + 1e-9)
        first_rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi_series.append(first_rsi)

    # Wilder's exponential smoothing for subsequent periods
    for i in range(period, len(changes)):
        g = gains[i]
        l = losses[i]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period

        if avg_loss == 0.0 and avg_gain == 0.0:
            val = 50.0
        elif avg_loss == 0.0:
            val = 100.0
        else:
            rs = avg_gain / (avg_loss + 1e-9)
            val = 100.0 - (100.0 / (1.0 + rs))
        rsi_series.append(val)

    return rsi_series


def calc_rsi(prices: List[float], period: int = 14) -> float:
    """Return latest Wilder's smoothed RSI value."""
    series = calc_rsi_series(prices, period)
    return series[-1] if series else 50.0


def detect_rsi_divergence(
    candles: List[Candle],
    rsi_series: Optional[List[float]] = None,
    lookback: int = 30,
) -> str:
    """Detect regular Bullish or Bearish divergence between price and RSI.

    - Regular Bullish Divergence: Price Lower Low ($L_2 < L_1$) while RSI Higher Low ($RSI_2 > RSI_1$)
      with at least one trough in oversold territory (RSI <= 40.0 or RSI <= 45.0).
    - Regular Bearish Divergence: Price Higher High ($H_2 > H_1$) while RSI Lower High ($RSI_2 < RSI_1$)
      with at least one peak in overbought territory (RSI >= 60.0 or RSI >= 55.0).

    Handles intermediate noise pivots by comparing recent extrema against earlier candidate
    extrema in the lookback window while ensuring intervening price action did not exceed the second extreme.
    If both bullish and bearish divergences are found in the window, returns the one with the more recent extreme.
    """
    if not candles or len(candles) < 5:
        return RsiDivergence.NONE.value

    closes = [c.close for c in candles]
    if rsi_series is None or len(rsi_series) != len(candles):
        rsi_series = calc_rsi_series(closes, period=14)

    # Scan window for pivot extrema
    window_candles = candles[-lookback:] if len(candles) > lookback else candles
    window_rsi = rsi_series[-len(window_candles):]
    n = len(window_candles)

    troughs: List[Tuple[int, float, float]] = []  # (index, low_price, rsi)
    peaks: List[Tuple[int, float, float]] = []    # (index, high_price, rsi)

    for i in range(1, n - 1):
        # Trough (Swing Low): low <= neighbors
        if (
            window_candles[i].low <= window_candles[i - 1].low
            and window_candles[i].low <= window_candles[i + 1].low
        ):
            if troughs and i == troughs[-1][0] + 1 and window_candles[i].low == troughs[-1][1]:
                troughs[-1] = (i, window_candles[i].low, min(troughs[-1][2], window_rsi[i]))
            else:
                troughs.append((i, window_candles[i].low, window_rsi[i]))

        # Peak (Swing High): high >= neighbors
        if (
            window_candles[i].high >= window_candles[i - 1].high
            and window_candles[i].high >= window_candles[i + 1].high
        ):
            if peaks and i == peaks[-1][0] + 1 and window_candles[i].high == peaks[-1][1]:
                peaks[-1] = (i, window_candles[i].high, max(peaks[-1][2], window_rsi[i]))
            else:
                peaks.append((i, window_candles[i].high, window_rsi[i]))

    # Also consider the final candle if it forms a new extreme
    latest_idx = n - 1
    if troughs and window_candles[latest_idx].low < troughs[-1][1]:
        troughs.append((latest_idx, window_candles[latest_idx].low, window_rsi[latest_idx]))
    if peaks and window_candles[latest_idx].high > peaks[-1][1]:
        peaks.append((latest_idx, window_candles[latest_idx].high, window_rsi[latest_idx]))

    # Check Bearish Divergence (Higher High in price, Lower High in RSI)
    detected_bearish: Optional[Tuple[int, int]] = None  # (p1_idx, p2_idx)
    if len(peaks) >= 2:
        for j in range(len(peaks) - 1, max(-1, len(peaks) - 4), -1):
            p2_idx, p2_high, p2_rsi = peaks[j]
            for k in range(j - 1, -1, -1):
                p1_idx, p1_high, p1_rsi = peaks[k]
                if p2_idx - p1_idx < 2:
                    continue
                if p2_high > p1_high and p2_rsi < p1_rsi and (p1_rsi >= 60.0 or p2_rsi >= 55.0):
                    # Validate intermediate price structure: no intervening peak higher than p2_high
                    if not any(peaks[m][1] >= p2_high for m in range(k + 1, j)):
                        detected_bearish = (p1_idx, p2_idx)
                        break
            if detected_bearish:
                break

    # Check Bullish Divergence (Lower Low in price, Higher Low in RSI)
    detected_bullish: Optional[Tuple[int, int]] = None  # (t1_idx, t2_idx)
    if len(troughs) >= 2:
        for j in range(len(troughs) - 1, max(-1, len(troughs) - 4), -1):
            t2_idx, t2_low, t2_rsi = troughs[j]
            for k in range(j - 1, -1, -1):
                t1_idx, t1_low, t1_rsi = troughs[k]
                if t2_idx - t1_idx < 2:
                    continue
                if t2_low < t1_low and t2_rsi > t1_rsi and (t1_rsi <= 40.0 or t2_rsi <= 45.0):
                    # Validate intermediate price structure: no intervening trough lower than t2_low
                    if not any(troughs[m][1] <= t2_low for m in range(k + 1, j)):
                        detected_bullish = (t1_idx, t2_idx)
                        break
            if detected_bullish:
                break

    # Recency arbitration if both are detected in lookback window
    if detected_bearish and detected_bullish:
        if detected_bearish[1] >= detected_bullish[1]:
            return RsiDivergence.BEARISH_DIV.value
        else:
            return RsiDivergence.BULLISH_DIV.value
    elif detected_bearish:
        return RsiDivergence.BEARISH_DIV.value
    elif detected_bullish:
        return RsiDivergence.BULLISH_DIV.value

    return RsiDivergence.NONE.value


def parse_order_book_levels(raw_levels: List[Union[List, Tuple]]) -> List[Tuple[float, float]]:
    """Parse raw order book level rows [[price, amount], ...] into float tuples."""
    parsed: List[Tuple[float, float]] = []
    for row in raw_levels:
        try:
            px = float(row[0])
            amt = float(row[1])
            parsed.append((px, amt))
        except (IndexError, ValueError, TypeError):
            continue
    return parsed


def analyze_order_book(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    top_n: int = 20,
) -> Tuple[float, Optional[float], Optional[float], Optional[float], Optional[float], float, float]:
    """Analyze top-20 order book depth and detect liquidity walls.

    Returns:
    (depth_ratio, support_wall_px, resistance_wall_px, support_wall_vol, resistance_wall_vol, total_bid_vol, total_ask_vol)
    """
    top_bids = bids[:top_n]
    top_asks = asks[:top_n]

    total_bid_vol = sum(amt for _, amt in top_bids)
    total_ask_vol = sum(amt for _, amt in top_asks)

    depth_ratio = total_bid_vol / (total_ask_vol + 1e-6)

    # Average level volume
    avg_bid_vol = (total_bid_vol / len(top_bids)) if top_bids else 0.0
    avg_ask_vol = (total_ask_vol / len(top_asks)) if top_asks else 0.0

    support_wall_px: Optional[float] = None
    support_wall_vol: Optional[float] = None
    resistance_wall_px: Optional[float] = None
    resistance_wall_vol: Optional[float] = None

    # Detect Support Wall: level volume >= 3.0 * average level volume OR >= 20% total visible bids
    for px, amt in top_bids:
        if (avg_bid_vol > 0 and amt >= 3.0 * avg_bid_vol) or (total_bid_vol > 0 and (amt / total_bid_vol) >= 0.20):
            if support_wall_vol is None or amt > support_wall_vol:
                support_wall_px = px
                support_wall_vol = amt

    # Detect Resistance Wall: level volume >= 3.0 * average level volume OR >= 20% total visible asks
    for px, amt in top_asks:
        if (avg_ask_vol > 0 and amt >= 3.0 * avg_ask_vol) or (total_ask_vol > 0 and (amt / total_ask_vol) >= 0.20):
            if resistance_wall_vol is None or amt > resistance_wall_vol:
                resistance_wall_px = px
                resistance_wall_vol = amt

    return (
        round(depth_ratio, 4),
        support_wall_px,
        resistance_wall_px,
        support_wall_vol,
        resistance_wall_vol,
        round(total_bid_vol, 4),
        round(total_ask_vol, 4),
    )


class TechnicalDepthAnalyst:
    """Role 5: Technical & Order Book Analyst.

    Evaluates Wilder's RSI(14), RSI momentum divergences, top-20 order book depth ratio,
    and institutional Support / Resistance liquidity walls.
    """

    def __init__(self, bitbank_client=None):
        self.client = bitbank_client

    def fetch_order_book(self, pair: str, client=None) -> OrderBookDepth:
        """Fetch live L2 order book from Bitbank."""
        active_client = client or self.client
        if active_client is None:
            raise ValueError("Bitbank client is required to fetch order book")

        # Bitbank client._pub(f"/{pair}/depth") returns dict with 'bids' and 'asks'
        raw = active_client._pub(f"/{pair}/depth")
        bids = parse_order_book_levels(raw.get("bids", []))
        asks = parse_order_book_levels(raw.get("asks", []))
        ts = raw.get("timestamp")
        return OrderBookDepth(bids=bids, asks=asks, timestamp=ts)

    def fetch_candles(
        self,
        pair: str,
        tf: str = "15min",
        limit: int = 3,
        client=None,
        cull_forming: bool = True,
        timeframe: Optional[str] = None,
        days: Optional[int] = None,
    ) -> List[Candle]:
        """Fetch historical candles from Bitbank for technical analysis."""
        actual_tf = timeframe or tf
        actual_days = days if days is not None else limit
        active_client = client or self.client
        if active_client is None:
            raise ValueError("Bitbank client is required to fetch remote candles")

        now = datetime.now(timezone.utc)
        raw_rows: List[Union[list, tuple]] = []

        if TF_SECONDS.get(actual_tf, 0) >= 14400 or actual_tf in ("4hour", "8hour", "12hour", "1day"):
            years = [now.year - 1, now.year]
            for y in years:
                try:
                    rows = active_client.candles(pair, actual_tf, str(y))
                    raw_rows.extend(rows)
                except Exception:
                    continue
        else:
            fetch_days = max(1, actual_days)
            for d in range(fetch_days, -1, -1):
                day_dt = now - timedelta(days=d)
                day_str = resolve_date_param(actual_tf, day_dt)
                try:
                    rows = active_client.candles(pair, actual_tf, day_str)
                    raw_rows.extend(rows)
                except Exception:
                    continue

        candles = parse_raw_ohlcv(raw_rows)
        if cull_forming:
            candles = cull_forming_candle(candles, actual_tf)
        return candles

    def analyze(
        self,
        pair: str,
        candles: Optional[List[Candle]] = None,
        order_book: Optional[OrderBookDepth] = None,
        client=None,
        timeframe: str = "15min",
    ) -> TechnicalDepthResult:
        """Analyze technical indicators and order book depth."""
        active_client = client or self.client

        # If candles not provided, fetch via active client if available
        if candles is None and active_client is not None:
            try:
                days = 20 if timeframe == "1hour" else (3 if timeframe == "15min" else 30)
                candles = self.fetch_candles(pair, tf=timeframe, limit=days, cull_forming=True, client=active_client)
            except Exception:
                candles = None

        # Compute RSI & Divergences
        if candles and len(candles) >= 2:
            closes = [c.close for c in candles]
            rsi_series = calc_rsi_series(closes, period=14)
            rsi = rsi_series[-1]
            divergence = detect_rsi_divergence(candles, rsi_series=rsi_series)
        else:
            rsi = 50.0
            divergence = RsiDivergence.NONE.value

        # Compute Order Book Depth & Walls
        if order_book is None and active_client is not None:
            try:
                order_book = self.fetch_order_book(pair, client=active_client)
            except Exception:
                order_book = None

        if order_book and (order_book.bids or order_book.asks):
            (
                depth_ratio,
                sup_px,
                res_px,
                sup_vol,
                res_vol,
                bid_vol,
                ask_vol,
            ) = analyze_order_book(order_book.bids, order_book.asks, top_n=20)
        else:
            depth_ratio = 1.0
            sup_px = None
            res_px = None
            sup_vol = None
            res_vol = None
            bid_vol = 0.0
            ask_vol = 0.0

        return TechnicalDepthResult(
            pair=pair,
            rsi=round(rsi, 2),
            rsi_divergence=divergence,
            depth_ratio=depth_ratio,
            support_wall_px=sup_px,
            resistance_wall_px=res_px,
            support_wall_vol=sup_vol,
            resistance_wall_vol=res_vol,
            total_bid_vol=bid_vol,
            total_ask_vol=ask_vol,
        )
