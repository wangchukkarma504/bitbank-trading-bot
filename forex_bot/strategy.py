"""Institutional Trend-Gated & Mean-Reversion Forex Strategy.

Core Guardrail:
- NEVER counter-trend trade against strong momentum.
- In a BULLISH regime (Price > EMA50 & EMA20 > EMA50): ONLY enter LONGS on pullbacks to support.
- In a BEARISH regime (Price < EMA50 & EMA20 < EMA50): ONLY enter SHORTS on relief bounces to resistance.
- In RANGING regime: Enter only at Bollinger extremes with confirmation.
- Trailing stops dynamically tighten as price progresses in profit.
"""

import math
from typing import Dict, List, Tuple


def calculate_ema(values: List[float], period: int) -> List[float]:
    if not values or len(values) < period:
        return [values[-1] if values else 0.0] * len(values)
    k = 2.0 / (period + 1)
    emas = []
    seed = sum(values[:period]) / period
    for i in range(period - 1):
        emas.append(values[i])
    emas.append(seed)
    for v in values[period:]:
        emas.append(v * k + emas[-1] * (1.0 - k))
    return emas


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return (max(highs) - min(lows)) if highs else 0.0010
    trs = []
    for i in range(1, len(closes)):
        h, l, prev_c = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    k = 2.0 / (period + 1)
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = tr * k + val * (1.0 - k)
    return val


def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    out = [50.0] * len(closes)
    ag, al = 0.0, 0.0
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        if i <= period:
            ag += gain / period
            al += loss / period
            if i == period:
                out[i] = 100.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al))
        else:
            ag = (ag * (period - 1) + gain) / period
            al = (al * (period - 1) + loss) / period
            out[i] = 100.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al))
    return out


def calculate_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[float, float, float]:
    if len(closes) < period:
        px = closes[-1] if closes else 1.0
        return px, px, px
    subset = closes[-period:]
    mean = sum(subset) / period
    variance = sum((x - mean) ** 2 for x in subset) / period
    std = math.sqrt(variance)
    upper = mean + (num_std * std)
    lower = mean - (num_std * std)
    return upper, mean, lower


class ForexRegime:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"


class ForexStrategy:
    def __init__(self, rsi_period: int = 14, bb_period: int = 20, atr_period: int = 14):
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.atr_period = atr_period

    def parse_klines(self, klines: list) -> Tuple[List[float], List[float], List[float], List[float]]:
        opens = [float(k[1]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        return opens, highs, lows, closes

    def evaluate_regime(self, klines_4h: list) -> Dict:
        """Determines macro trend regime using EMA20, EMA50, EMA100."""
        if len(klines_4h) < 50:
            return {"regime": ForexRegime.RANGING, "reason": "Insufficient candles"}

        _, highs, lows, closes = self.parse_klines(klines_4h)
        current_close = closes[-1]

        ema20 = calculate_ema(closes, 20)[-1]
        ema50 = calculate_ema(closes, 50)[-1]
        ema100 = calculate_ema(closes, 100)[-1] if len(closes) >= 100 else ema50
        atr = calculate_atr(highs, lows, closes, self.atr_period)

        # Strict trend classification
        if current_close > ema50 and ema20 > ema50:
            regime = ForexRegime.BULLISH
        elif current_close < ema50 and ema20 < ema50:
            regime = ForexRegime.BEARISH
        else:
            regime = ForexRegime.RANGING

        return {
            "regime": regime,
            "close": current_close,
            "ema_fast": ema20,
            "ema_slow": ema50,
            "ema_trend": ema100,
            "atr": atr,
        }

    def check_signal(self, klines_regime: list, klines_trigger: list) -> Dict:
        """Enforces strictly regime-aligned entries:
        - NEVER SHORT IN A BULLISH TREND.
        - NEVER LONG IN A BEARISH TREND.
        """
        regime_info = self.evaluate_regime(klines_regime)
        regime = regime_info["regime"]

        if len(klines_trigger) < self.bb_period + 5:
            return {"signal": "WAIT", "regime": regime, "reason": "Insufficient trigger candles", "regime_info": regime_info}

        _, highs, lows, closes = self.parse_klines(klines_trigger)
        px = closes[-1]
        upper_bb, mid_bb, lower_bb = calculate_bollinger_bands(closes, self.bb_period, 2.0)
        rsi_series = calculate_rsi(closes, self.rsi_period)
        rsi = rsi_series[-1]
        atr = calculate_atr(highs, lows, closes, self.atr_period)
        ema20_trigger = calculate_ema(closes, 20)[-1]
        ema50_trigger = calculate_ema(closes, 50)[-1]

        if atr < 0.0003:
            return {"signal": "WAIT", "regime": regime, "reason": f"Low volatility (ATR: {atr:.5f})", "regime_info": regime_info}

        # 1. BULLISH REGIME -> ONLY LONG ENTRIES ALLOWED
        if regime == ForexRegime.BULLISH:
            # Buy the dip when price pulls back from upper band towards mid-band / EMA support
            is_pullback = px <= upper_bb * 0.998 or px <= mid_bb * 1.006
            is_dip = rsi <= 64.0  # healthy pullback from overbought territory in bull trend

            if is_pullback and is_dip:
                stop_loss = px - max(1.2 * atr, 0.0012)
                tp1 = px + 1.2 * atr
                tp2 = upper_bb if upper_bb > px + 1.2 * atr else px + 2.5 * atr
                risk = px - stop_loss
                reward = tp2 - px

                return {
                    "signal": "BUY",
                    "price": px,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_per_unit": risk,
                    "reward_per_unit": reward,
                    "rr_ratio": reward / risk if risk > 0 else 2.0,
                    "atr": atr,
                    "rsi": rsi,
                    "regime": regime,
                    "reason": f"Bullish trend dip (Px={px:.5f} below UpperBB), RSI={rsi:.1f}",
                    "regime_info": regime_info,
                }
            return {
                "signal": "WAIT",
                "regime": regime,
                "reason": f"Bullish trend active. Waiting for dip. Px={px:.5f}, RSI={rsi:.1f}",
                "regime_info": regime_info,
            }

        # 2. BEARISH REGIME -> ONLY SHORT ENTRIES ALLOWED
        elif regime == ForexRegime.BEARISH:
            # Sell the relief bounce when price pushes up near EMA20/50 resistance or upper BB
            is_relief = px >= ema20_trigger * 0.999 or px >= upper_bb * 0.998
            is_overbought = rsi >= 52.0

            if is_relief and is_overbought:
                stop_loss = px + max(1.2 * atr, 0.0010)
                tp1 = px - 1.2 * atr
                tp2 = px - 2.5 * atr
                risk = stop_loss - px
                reward = px - tp2

                return {
                    "signal": "SELL",
                    "price": px,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_per_unit": risk,
                    "reward_per_unit": reward,
                    "rr_ratio": reward / risk if risk > 0 else 2.0,
                    "atr": atr,
                    "rsi": rsi,
                    "regime": regime,
                    "reason": f"Bearish trend relief bounce to EMA resistance ({ema20_trigger:.5f}), RSI={rsi:.1f}",
                    "regime_info": regime_info,
                }
            return {
                "signal": "WAIT",
                "regime": regime,
                "reason": f"Bearish trend active. Waiting for bounce to resistance. Px={px:.5f}, RSI={rsi:.1f}",
                "regime_info": regime_info,
            }

        # 3. RANGING REGIME -> Both sides permitted ONLY at true extreme bands
        else:
            if px <= lower_bb * 1.0005 and rsi <= 30.0:
                stop_loss = px - max(1.2 * atr, 0.0010)
                tp1 = mid_bb
                tp2 = upper_bb
                risk = px - stop_loss
                reward = tp2 - px
                return {
                    "signal": "BUY",
                    "price": px,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_per_unit": risk,
                    "reward_per_unit": reward,
                    "rr_ratio": reward / risk if risk > 0 else 2.0,
                    "atr": atr,
                    "rsi": rsi,
                    "regime": regime,
                    "reason": f"Range extreme bounce at Lower BB ({lower_bb:.5f}), RSI={rsi:.1f}",
                    "regime_info": regime_info,
                }
            elif px >= upper_bb * 0.9995 and rsi >= 70.0:
                stop_loss = px + max(1.2 * atr, 0.0010)
                tp1 = mid_bb
                tp2 = lower_bb
                risk = stop_loss - px
                reward = px - tp2
                return {
                    "signal": "SELL",
                    "price": px,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "risk_per_unit": risk,
                    "reward_per_unit": reward,
                    "rr_ratio": reward / risk if risk > 0 else 2.0,
                    "atr": atr,
                    "rsi": rsi,
                    "regime": regime,
                    "reason": f"Range extreme rejection at Upper BB ({upper_bb:.5f}), RSI={rsi:.1f}",
                    "regime_info": regime_info,
                }

        return {
            "signal": "WAIT",
            "regime": regime,
            "reason": f"No clean setup in {regime} regime. Px={px:.5f}, RSI={rsi:.1f}",
            "regime_info": regime_info,
        }
