"""Directional Strategist (Role 2).

Dynamically decides whether the market regime warrants Spot Long or Margin Short across
the 5 supported pairs (sol_jpy, doge_jpy, eth_jpy, btc_jpy, xrp_jpy).

Evaluates:
- Multi-timeframe trend alignment from Role 3 (15m, 1h, 4h).
- BTC macro trend filter: If BTC is below 4h EMA200, strictly suppress Spot Longs and
  prioritize high-conviction Margin Shorts into resistance clusters.
- Wick Anatomy from Role 4: Upper rejection shooting stars confirm short resistance;
  lower absorption hammers confirm long support.
- Technical Depth from Role 5: RSI divergences, order book depth ratios, liquidity walls.
Outputs actionable trading signals with conviction and target entry/stop levels.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Tuple

from tradingbot.models import (
    MARGIN_PAIRS,
    SPOT_ONLY_PAIRS,
    SUPPORTED_PAIRS,
    MarketTrendResult,
    WickAnalysisResult,
    TechnicalDepthResult,
    TrendAlignment,
    WickType,
    RsiDivergence,
    RegimeType,
)
from tradingbot.analysis.market_trend import MarketTrendAnalyst
from tradingbot.analysis.wick_anatomy import WickAnatomyAnalyst
from tradingbot.analysis.technical_depth import TechnicalDepthAnalyst


@dataclass
class DirectionalSignal:
    """Actionable signal emitted by Directional Strategist (Role 2)."""
    pair: str
    action: str  # "SHORT", "LONG", "HOLD", "NEUTRAL"
    conviction: float  # 0.0 to 1.0 (or 0% to 100%)
    position_type: str  # "margin" (for short), "spot" or "margin" (for long), or "none"
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    reasons: List[str] = field(default_factory=list)
    btc_regime_bullish: bool = False
    trend_alignment: str = TrendAlignment.NEUTRAL.value
    wick_classification: str = WickType.NEUTRAL.value
    rsi_divergence: str = RsiDivergence.NONE.value
    depth_ratio: float = 1.0
    resistance_wall: Optional[float] = None
    support_wall: Optional[float] = None
    timestamp: int = 0
    # Entry context kept for the per-trade journal
    rsi: float = 50.0
    trend_1h: str = TrendAlignment.NEUTRAL.value
    trend_15m: str = TrendAlignment.NEUTRAL.value


class DirectionalStrategist:
    """Role 2: Directional Strategist.

    Coordinates multi-role market intelligence to formulate high-conviction trading
    signals while strictly enforcing the BTC macro trend filter.
    """

    MIN_CONVICTION: float = 0.60

    # Exit geometry and short gate, from a 150-day replay of Bitbank 5m candles across the 5 margin pairs
    # (2026-06-22..2026-11-18, real fees). The previous 0.85% stop / 0.90% target lost ~0.12% per trade in
    # every quarter whatever the entry rule; only fading an overbought 15m rally inside a 4h downtrend with
    # a wider stop and target stayed at or above break-even.
    STOP_PCT: float = 0.012          # initial hard stop distance from entry
    SHORT_TP_PCT: float = 0.018      # short take-profit distance (1.5R)
    LONG_TP_PCT: float = 0.018       # margin-pair long take-profit distance (1.5R)
    SHORT_FADE_RSI_MIN: float = 65.0  # shorts only into an overbought 15m rally, never chasing a drop
    # Shorts also need the 1h trend down (1h EMA20 < 1h EMA50); see the gate in evaluate_pair.

    def __init__(self, bitbank_client=None, allow_counter_trend_longs: bool = False):
        self.client = bitbank_client
        self.allow_counter_trend_longs = allow_counter_trend_longs
        self.trend_analyst = MarketTrendAnalyst(bitbank_client)
        self.wick_analyst = WickAnatomyAnalyst(bitbank_client)
        self.tech_analyst = TechnicalDepthAnalyst(bitbank_client)

    def evaluate_pair(
        self,
        pair: str,
        mtf_trend: Optional[Dict[str, MarketTrendResult]] = None,
        wick_result: Optional[WickAnalysisResult] = None,
        tech_result: Optional[TechnicalDepthResult] = None,
        ticker: Optional[Dict[str, Any]] = None,
        btc_regime_bullish: Optional[bool] = None,
        macro_report: Optional[Any] = None,
        client=None,
    ) -> DirectionalSignal:
        """Evaluate directional edge and construct trade signal for a single pair."""
        active_client = client or self.client
        now_ms = int(time.time() * 1000)

        if pair not in MARGIN_PAIRS and pair not in SPOT_ONLY_PAIRS:
            raise ValueError(f"Pair {pair} is not in supported pairs whitelist")

        cfg = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS[pair]
        pd = cfg.price_digits

        # 1. Resolve Multi-timeframe Trend (Role 3)
        if mtf_trend is None and active_client is not None:
            mtf_trend = self.trend_analyst.analyze_multi_timeframe(pair, client=active_client)

        trend_4h = mtf_trend.get("4hour") if mtf_trend else None
        trend_1h = mtf_trend.get("1hour") if mtf_trend else None
        trend_15m = mtf_trend.get("15min") if mtf_trend else None

        # Resolve BTC Macro Regime
        if btc_regime_bullish is None:
            if trend_4h and trend_4h.btc_regime_bullish is not None:
                btc_regime_bullish = trend_4h.btc_regime_bullish
            elif active_client is not None:
                btc_regime_bullish = self.trend_analyst.evaluate_btc_regime(client=active_client)
            else:
                btc_regime_bullish = False

        # 2. Resolve Wick Anatomy (Role 4)
        if wick_result is None and active_client is not None:
            candles_15m = self.trend_analyst.fetch_candles(pair, "15min", days=3, client=active_client)
            wick_result = self.wick_analyst.analyze(pair, candles_15m)

        # 3. Resolve Technical Depth (Role 5)
        if tech_result is None and active_client is not None:
            tech_result = self.tech_analyst.analyze(pair, client=active_client)

        # 4. Resolve Live Ticker
        if ticker is None and active_client is not None:
            try:
                ticker = active_client.ticker(pair)
            except Exception:
                ticker = {}

        last_px = float(ticker.get("last", 0.0)) if ticker else (trend_15m.close if trend_15m else 0.0)
        best_bid = float(ticker.get("buy", last_px * 0.999)) if ticker else last_px * 0.999
        best_ask = float(ticker.get("sell", last_px * 1.001)) if ticker else last_px * 1.001

        # Fallback price if needed
        if last_px <= 0:
            last_px = 1.0

        # =====================================================================
        # Scoring & Edge Formulation
        # =====================================================================
        short_score = 0.0
        long_score = 0.0
        reasons: List[str] = []

        # --- A. Trend Alignment Evaluation ---
        align_4h = trend_4h.trend_alignment if trend_4h else TrendAlignment.NEUTRAL.value
        align_1h = trend_1h.trend_alignment if trend_1h else TrendAlignment.NEUTRAL.value
        align_15m = trend_15m.trend_alignment if trend_15m else TrendAlignment.NEUTRAL.value

        # Short trend scoring
        if align_4h == TrendAlignment.BEARISH.value:
            short_score += 0.25
            reasons.append("4h macro trend is BEARISH (below EMA200)")
        elif align_4h == TrendAlignment.BULLISH.value:
            long_score += 0.25

        if align_1h == TrendAlignment.BEARISH.value:
            short_score += 0.20
            reasons.append("1h intermediate trend is BEARISH")
        elif align_1h == TrendAlignment.BULLISH.value:
            long_score += 0.20

        if align_15m == TrendAlignment.BEARISH.value:
            short_score += 0.15
            reasons.append("15m intraday trend is BEARISH")
        elif align_15m == TrendAlignment.BULLISH.value:
            long_score += 0.15

        # --- B. BTC Macro Filter Enforcement ---
        alt_breakout_ok = (
            self.allow_counter_trend_longs
            and pair in SPOT_ONLY_PAIRS
            and align_15m == TrendAlignment.BULLISH.value
            and align_1h != TrendAlignment.BEARISH.value
            and (trend_1h is None or last_px > trend_1h.ema20)
            and (tech_result is None or tech_result.rsi < 68.0)
        )
        margin_bounce_ok = (
            self.allow_counter_trend_longs
            and pair in MARGIN_PAIRS
            and align_15m == TrendAlignment.BULLISH.value
            and align_1h == TrendAlignment.BULLISH.value
            and (trend_1h is None or last_px > trend_1h.ema20)
            and (tech_result is None or tech_result.rsi < 65.0)
        )
        long_eligible = btc_regime_bullish or alt_breakout_ok or margin_bounce_ok

        if not btc_regime_bullish:
            # Macro downtrend: award boost to Shorts; gate Longs unless breakout/bounce qualifies
            short_score += 0.15
            if alt_breakout_ok or margin_bounce_ok:
                long_score += 0.20
                reasons.append("BTC bear regime, but 15m/1h bullish bounce scalp qualified")
            else:
                reasons.append("BTC macro filter confirms BEAR REGIME (below 4h EMA200): Spot Longs gated")
                long_score = 0.0  # HARD GATE: Spot longs strictly suppressed
        else:
            reasons.append("BTC macro filter confirms BULL REGIME (above 4h EMA200)")

        # --- C. Wick Anatomy Evaluation ---
        wick_cls = wick_result.classification if wick_result else WickType.NEUTRAL.value
        if wick_result:
            if wick_cls == WickType.BEARISH_REJECTION.value:
                short_score += 0.20
                reasons.append(f"Upper rejection wick shooting star ({wick_result.upper_wick_pct}% wick)")
                if wick_result.is_exhaustion:
                    short_score += 0.10
                    reasons.append("Swing high exhaustion detected on upper wick")
                if wick_result.up_lo_ratio >= 1.4:
                    short_score += 0.05
                    reasons.append(f"Persistent overhead supply ratio ({wick_result.up_lo_ratio:.2f})")
            elif wick_cls == WickType.BULLISH_ABSORPTION.value:
                if long_eligible:
                    long_score += 0.20
                    reasons.append(f"Lower absorption hammer wick ({wick_result.lower_wick_pct}% wick)")
                    if wick_result.is_exhaustion:
                        long_score += 0.10
                        reasons.append("Swing low exhaustion detected on lower wick")
                    if wick_result.up_lo_ratio <= 0.7:
                        long_score += 0.05
                        reasons.append(f"Persistent dip absorption ratio ({wick_result.up_lo_ratio:.2f})")

        # --- D. Technical Depth & Order Book Evaluation ---
        rsi_div = tech_result.rsi_divergence if tech_result else RsiDivergence.NONE.value
        depth_ratio = tech_result.depth_ratio if tech_result else 1.0
        res_wall = tech_result.resistance_wall_px if tech_result else None
        sup_wall = tech_result.support_wall_px if tech_result else None

        if tech_result:
            # RSI Divergence
            if rsi_div == RsiDivergence.BEARISH_DIV.value:
                short_score += 0.20
                reasons.append("Regular Bearish RSI Divergence confirmed (Price HH vs RSI LH)")
            elif rsi_div == RsiDivergence.BULLISH_DIV.value and long_eligible:
                long_score += 0.20
                reasons.append("Regular Bullish RSI Divergence confirmed (Price LL vs RSI HL)")

            # RSI Levels & Exhaustion Guard (avoid chasing oversold shorts / overbought longs)
            if tech_result.rsi >= self.SHORT_FADE_RSI_MIN:
                # Overbought rally inside a 4h downtrend is the one short setup that held up in backtest
                short_score += 0.20 if align_4h == TrendAlignment.BEARISH.value else 0.05
                long_score -= 0.10
                reasons.append(f"RSI overbought ({tech_result.rsi:.1f})")
            elif tech_result.rsi <= 35.0:
                short_score -= 0.25
                reasons.append(f"RSI oversold ({tech_result.rsi:.1f}): short-chase penalty")
                if long_eligible:
                    long_score += 0.05

            if trend_15m and trend_15m.ema20 > 0 and last_px > 0:
                ema_dist = (last_px - trend_15m.ema20) / trend_15m.ema20
                if ema_dist < -0.012:
                    short_score -= 0.15
                    reasons.append(f"Stretched {ema_dist * 100:.1f}% below 15m EMA20: wait for bounce")
                elif ema_dist > 0.012 and long_eligible:
                    long_score -= 0.15
                    reasons.append(f"Stretched +{ema_dist * 100:.1f}% above 15m EMA20: wait for dip")

            if rsi_div == RsiDivergence.BULLISH_DIV.value:
                short_score -= 0.10
                reasons.append("Bullish RSI divergence caution on short")
            elif rsi_div == RsiDivergence.BEARISH_DIV.value:
                long_score -= 0.10

            # Order Book Depth & Opposing Wall Guard
            if depth_ratio < 0.80:
                short_score += 0.10
                reasons.append(f"Order book depth heavy on asks (ratio {depth_ratio:.2f})")
            elif depth_ratio >= 1.80:
                short_score -= 0.10
                reasons.append(f"Heavy bid support ({depth_ratio:.2f}): short-into-wall penalty")
            if depth_ratio > 1.25 and long_eligible:
                long_score += 0.10
                reasons.append(f"Order book depth heavy on bids (ratio {depth_ratio:.2f})")
            elif depth_ratio <= 0.55:
                long_score -= 0.10

            # Liquidity Walls
            if res_wall:
                short_score += 0.05
                reasons.append(f"Resistance wall identified at {res_wall}")
            if sup_wall and long_eligible:
                long_score += 0.05
                reasons.append(f"Support wall identified at {sup_wall}")

        # --- E. Live Macro & Catalyst Context (Probabilistic News & Fear/Greed) ---
        if macro_report is not None:
            bias = getattr(macro_report, "catalyst_bias", "NEUTRAL")
            summary = getattr(macro_report, "prediction_summary", "")
            if bias == "BEARISH":
                short_score += 0.05
                if summary:
                    reasons.append(f"Macro Catalyst: {summary}")
            elif bias == "BULLISH" and btc_regime_bullish:
                long_score += 0.05
                if summary:
                    reasons.append(f"Macro Catalyst: {summary}")

        short_conviction = min(1.0, max(0.0, round(short_score, 2)))
        long_conviction = min(1.0, max(0.0, round(long_score, 2))) if long_eligible else 0.0

        # Hard short gates (backtest): never short a 4h uptrend, and only sell an overbought rally
        short_allowed = True
        if align_4h == TrendAlignment.BULLISH.value:
            short_allowed = False
            reasons.append("Short gated: 4h trend is BULLISH")
        elif tech_result is not None and tech_result.rsi < self.SHORT_FADE_RSI_MIN:
            short_allowed = False
            reasons.append(
                f"Short gated: RSI {tech_result.rsi:.1f} < {self.SHORT_FADE_RSI_MIN:.0f}, waiting for an overbought rally to sell"
            )
        elif trend_1h is not None and trend_1h.ema20 > 0 and trend_1h.ema50 > 0 and (
            align_1h == TrendAlignment.BULLISH.value or trend_1h.ema20 >= trend_1h.ema50
        ):
            # 150-day replay: the same rally-fade made ~+0.23%/trade with the 1h EMA20 below the 1h EMA50
            # and ~0% with it above, so a rally is only sold while the 1h trend is still down.
            short_allowed = False
            reasons.append("Short gated: 1h trend is up (1h EMA20 >= 1h EMA50), not selling this rally")

        # =====================================================================
        # Signal Action & Target Pricing
        # =====================================================================
        if (
            pair in MARGIN_PAIRS
            and short_allowed
            and short_conviction >= self.MIN_CONVICTION
            and short_conviction >= long_conviction
        ):
            action = "SHORT"
            position_type = "margin"
            conviction = short_conviction

            # Entry targeting: Maker limit at rejection wick, meaningful resistance wall (>=+0.15%), 15m EMA20 pullback, or +0.20%
            if wick_result and wick_result.recommended_entry and wick_result.recommended_entry >= best_ask * 1.001:
                entry_px = wick_result.recommended_entry
            elif res_wall and res_wall >= best_ask * 1.0015:
                entry_px = res_wall
            elif trend_15m and trend_15m.ema20 > max(best_ask, last_px) and (trend_15m.ema20 - last_px) / max(1e-9, last_px) <= 0.008:
                entry_px = trend_15m.ema20
            else:
                entry_px = max(best_ask, last_px) * 1.0020  # Wait for +0.20% maker pullback instead of chasing bottom

            # Hard Stop Loss: fixed STOP_PCT above entry (the backtested distance)
            stop_px = entry_px * (1.0 + self.STOP_PCT)

            # Take Profit: fixed SHORT_TP_PCT below entry (matches the orchestrator's live exit)
            tp_px = entry_px * (1.0 - self.SHORT_TP_PCT)

        elif long_conviction >= self.MIN_CONVICTION and long_eligible:
            action = "LONG"
            position_type = "spot"
            conviction = long_conviction

            # Entry targeting: Maker limit at absorption wick, meaningful support wall (<=-0.15%), 15m EMA20 pullback, or -0.20%
            if wick_result and wick_result.recommended_entry and wick_result.recommended_entry <= best_bid * 0.999:
                entry_px = wick_result.recommended_entry
            elif sup_wall and sup_wall <= best_bid * 0.9985:
                entry_px = sup_wall
            elif trend_15m and 0 < trend_15m.ema20 < min(best_bid, last_px) and (last_px - trend_15m.ema20) / max(1e-9, last_px) <= 0.008:
                entry_px = trend_15m.ema20
            else:
                entry_px = min(best_bid, last_px) * 0.9980  # Wait for -0.20% maker dip instead of chasing top

            # Hard Stop Loss: fixed STOP_PCT below entry
            stop_px = entry_px * (1.0 - self.STOP_PCT)

            # Take Profit: fixed LONG_TP_PCT above entry (matches the orchestrator's live exit)
            tp_px = entry_px * (1.0 + self.LONG_TP_PCT)

        else:
            action = "NEUTRAL"
            position_type = "none"
            conviction = max(short_conviction, long_conviction)
            entry_px = last_px
            stop_px = 0.0
            tp_px = 0.0

        # Price formatting
        entry_fmt = round(entry_px, pd) if pd > 0 else round(entry_px)
        stop_fmt = round(stop_px, pd) if pd > 0 else round(stop_px)
        tp_fmt = round(tp_px, pd) if pd > 0 else round(tp_px)

        return DirectionalSignal(
            pair=pair,
            action=action,
            conviction=conviction,
            position_type=position_type,
            entry_price=entry_fmt,
            stop_loss_price=stop_fmt,
            take_profit_price=tp_fmt,
            reasons=reasons,
            btc_regime_bullish=bool(btc_regime_bullish),
            trend_alignment=align_4h,
            wick_classification=wick_cls,
            rsi_divergence=rsi_div,
            depth_ratio=depth_ratio,
            resistance_wall=res_wall,
            support_wall=sup_wall,
            timestamp=now_ms,
            rsi=float(tech_result.rsi) if tech_result else 50.0,
            trend_1h=align_1h,
            trend_15m=align_15m,
        )

    def scan_all_pairs(
        self,
        pairs: Optional[List[str]] = None,
        client=None,
    ) -> Dict[str, DirectionalSignal]:
        """Scan all whitelisted margin pairs and produce directional signals."""
        target_pairs = pairs or SUPPORTED_PAIRS
        active_client = client or self.client
        signals: Dict[str, DirectionalSignal] = {}

        # Pre-resolve BTC regime once for consistency
        btc_regime = None
        if active_client is not None:
            btc_regime = self.trend_analyst.evaluate_btc_regime(client=active_client)

        for pair in target_pairs:
            sig = self.evaluate_pair(pair, btc_regime_bullish=btc_regime, client=active_client)
            signals[pair] = sig

        return signals
