"""Wick & Candlestick Anatomy Analyst (Role 4).

Decomposes candlestick geometry into body, upper rejection wick, and lower absorption wick.
Classifies candle microstructure (BEARISH_REJECTION, BULLISH_ABSORPTION, SPINNING_TOP, MOMENTUM)
and detects exhaustion patterns and rolling wick pressure ratios.
"""

from typing import List, Optional, Tuple
from tradingbot.models import Candle, WickAnalysisResult, WickType


def decompose_candle(candle: Candle) -> Tuple[float, float, float, float]:
    """Extract (body, upper_wick, lower_wick, total_range) from a candle."""
    body = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    total_range = candle.high - candle.low
    return body, upper_wick, lower_wick, total_range


def classify_candle(candle: Candle) -> str:
    """Classify candle structure based on exact geometric thresholds:
    - BEARISH_REJECTION: upper_wick > 1.8 * body AND upper_wick > 1.5 * lower_wick
    - BULLISH_ABSORPTION: lower_wick > 1.8 * body AND lower_wick > 1.5 * upper_wick
    - SPINNING_TOP: upper_wick > 1.0 * body AND lower_wick > 1.0 * body
    - MOMENTUM: body > 1.5 * (upper_wick + lower_wick)
    - Fallback: NEUTRAL
    """
    body, upper_wick, lower_wick, total_range = decompose_candle(candle)

    if total_range <= 0.0:
        return WickType.NEUTRAL.value

    # 1. Bearish Rejection Wick (Shooting star / supply grab)
    if upper_wick > 1.8 * body and upper_wick > 1.5 * lower_wick:
        return WickType.BEARISH_REJECTION.value

    # 2. Bullish Absorption Wick (Hammer / demand sweep)
    if lower_wick > 1.8 * body and lower_wick > 1.5 * upper_wick:
        return WickType.BULLISH_ABSORPTION.value

    # 3. Indecision / Spinning Top
    if upper_wick > 1.0 * body and lower_wick > 1.0 * body:
        return WickType.SPINNING_TOP.value

    # 4. Strong Momentum Body (Marubozu / expansion)
    if body > 1.5 * (upper_wick + lower_wick):
        return WickType.MOMENTUM.value

    return WickType.NEUTRAL.value


def calc_rolling_wick_ratio(candles: List[Candle], window: int = 15) -> float:
    """Compute rolling ratio of upper rejection wicks to lower absorption wicks:
    ratio = sum(upper_wicks) / (sum(lower_wicks) + 1e-6)
    - >= 1.4: Persistent overhead supply
    - <= 0.7: Persistent dip absorption
    """
    if not candles:
        return 1.0

    recent = candles[-window:] if len(candles) >= window else candles
    sum_upper = 0.0
    sum_lower = 0.0

    for c in recent:
        _, upper, lower, _ = decompose_candle(c)
        sum_upper += upper
        sum_lower += lower

    return sum_upper / (sum_lower + 1e-6)


def detect_exhaustion(candles: List[Candle], classification: Optional[str] = None) -> bool:
    """Detect whether the current candle signifies exhaustion at a swing boundary.

    Criteria for Bearish Exhaustion:
    - Current candle is BEARISH_REJECTION
    - At or near the highest high of the last 5-10 candles, OR preceded by >= 2 consecutive
      green candles, OR preceded by another rejection wick.

    Criteria for Bullish Exhaustion:
    - Current candle is BULLISH_ABSORPTION
    - At or near the lowest low of the last 5-10 candles, OR preceded by >= 2 consecutive
      red candles, OR preceded by another absorption wick.
    """
    if not candles or len(candles) < 2:
        return False

    latest = candles[-1]
    cls = classification or classify_candle(latest)

    if cls not in (WickType.BEARISH_REJECTION.value, WickType.BULLISH_ABSORPTION.value):
        return False

    lookback = min(len(candles) - 1, 6)
    prior_candles = candles[-lookback - 1 : -1]

    if cls == WickType.BEARISH_REJECTION.value:
        # Check swing high condition
        prior_highs = [c.high for c in prior_candles]
        is_swing_high = latest.high >= max(prior_highs)

        # Check consecutive green runs
        consecutive_greens = 0
        for c in reversed(prior_candles):
            if c.close > c.open:
                consecutive_greens += 1
            else:
                break

        # Check consecutive rejection wicks
        prior_was_rejection = classify_candle(prior_candles[-1]) == WickType.BEARISH_REJECTION.value

        return is_swing_high or (consecutive_greens >= 2) or prior_was_rejection

    elif cls == WickType.BULLISH_ABSORPTION.value:
        # Check swing low condition
        prior_lows = [c.low for c in prior_candles]
        is_swing_low = latest.low <= min(prior_lows)

        # Check consecutive red runs
        consecutive_reds = 0
        for c in reversed(prior_candles):
            if c.close < c.open:
                consecutive_reds += 1
            else:
                break

        # Check consecutive absorption wicks
        prior_was_absorption = classify_candle(prior_candles[-1]) == WickType.BULLISH_ABSORPTION.value

        return is_swing_low or (consecutive_reds >= 2) or prior_was_absorption

    return False


def calc_recommended_entry(candle: Candle, classification: str) -> Optional[float]:
    """Calculate tactical maker entry price based on wick geometry:
    - BEARISH_REJECTION: Midpoint of upper wick (H - 0.5 * W_upper)
    - BULLISH_ABSORPTION: Midpoint of lower wick (L + 0.5 * W_lower)
    """
    _, upper_wick, lower_wick, _ = decompose_candle(candle)

    if classification == WickType.BEARISH_REJECTION.value and upper_wick > 0:
        return candle.high - 0.5 * upper_wick
    elif classification == WickType.BULLISH_ABSORPTION.value and lower_wick > 0:
        return candle.low + 0.5 * lower_wick
    return None


class WickAnatomyAnalyst:
    """Role 4: Wick & Candlestick Anatomy Analyst.

    Evaluates candle bodies, rejection wicks, absorption wicks, and exhaustion setups.
    """

    def __init__(self, bitbank_client=None):
        self.client = bitbank_client

    def analyze(self, pair: str, candles: List[Candle]) -> WickAnalysisResult:
        """Analyze candlestick anatomy on the latest candle in the series."""
        if not candles:
            return WickAnalysisResult(
                pair=pair,
                body_pct=0.0,
                upper_wick_pct=0.0,
                lower_wick_pct=0.0,
                classification=WickType.NEUTRAL.value,
                is_exhaustion=False,
                body=0.0,
                upper_wick=0.0,
                lower_wick=0.0,
                up_lo_ratio=1.0,
                recommended_entry=None,
            )

        latest = candles[-1]
        body, upper_wick, lower_wick, total_range = decompose_candle(latest)

        if total_range > 0:
            body_pct = round((body / total_range) * 100.0, 2)
            upper_wick_pct = round((upper_wick / total_range) * 100.0, 2)
            lower_wick_pct = round((lower_wick / total_range) * 100.0, 2)
        else:
            body_pct = 0.0
            upper_wick_pct = 0.0
            lower_wick_pct = 0.0

        classification = classify_candle(latest)
        is_exhaustion = detect_exhaustion(candles, classification)
        up_lo_ratio = calc_rolling_wick_ratio(candles, window=15)
        entry_price = calc_recommended_entry(latest, classification)

        return WickAnalysisResult(
            pair=pair,
            body_pct=body_pct,
            upper_wick_pct=upper_wick_pct,
            lower_wick_pct=lower_wick_pct,
            classification=classification,
            is_exhaustion=is_exhaustion,
            body=round(body, 4),
            upper_wick=round(upper_wick, 4),
            lower_wick=round(lower_wick, 4),
            up_lo_ratio=round(up_lo_ratio, 4),
            recommended_entry=round(entry_price, 4) if entry_price is not None else None,
        )
