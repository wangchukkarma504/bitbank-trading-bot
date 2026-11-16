"""Altcoin Spot Momentum Breakout Scanner.

Scans all 60+ cryptocurrency pairs on Bitbank via public endpoints to detect
high-velocity breakout opportunities, volume surges, and RSI momentum.
Generates fully compliant Spot Long trade setups with mandatory exchange-side
stop losses, strictly respecting capital preservation rules (max 30% allocation).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from tradingbot.bitbank import Bitbank, BitbankError
from tradingbot.models import Candle
from tradingbot.analysis.market_trend import (
    parse_raw_ohlcv,
    cull_forming_candle,
    resolve_date_param,
)
from tradingbot.analysis.technical_depth import calc_rsi_series


logger = logging.getLogger("AltcoinMomentumScanner")


@dataclass
class AltcoinBreakoutCandidate:
    """Represents an altcoin spot breakout opportunity."""

    pair: str
    last_price: float
    change_24h_pct: float
    turnover_24h_jpy: float
    high_24h: float
    low_24h: float
    proximity_to_high_pct: float
    volume_surge_ratio: float
    rsi_15m: float
    swing_low_stop_price: float
    take_profit_target_price: float
    breakout_score: float
    actionable: bool
    summary: str


class AltcoinMomentumScanner:
    """High-Velocity Altcoin Spot Momentum Breakout Scanner across all Bitbank pairs."""

    def __init__(
        self,
        client: Optional[Any] = None,
        min_turnover_jpy: float = 3_000_000.0,
        min_gain_pct: float = 1.0,
        min_high_proximity_pct: float = 85.0,
    ):
        self.client = client if client is not None else Bitbank()
        self.min_turnover_jpy = min_turnover_jpy
        self.min_gain_pct = min_gain_pct
        self.min_high_proximity_pct = min_high_proximity_pct
        self.logger = logger

    def fetch_all_tickers(self) -> List[Dict[str, Any]]:
        """Fetch all tickers from Bitbank public tickers endpoint."""
        try:
            return self.client.tickers()
        except Exception as e:
            self.logger.warning(f"Failed to query public tickers: {e}")
            return []

    def screen_candidates(
        self, tickers_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Perform initial screening on all JPY pairs using 24h market metrics."""
        raw_tickers = tickers_data if tickers_data is not None else self.fetch_all_tickers()
        candidates: List[Dict[str, Any]] = []

        for d in raw_tickers:
            pair = d.get("pair", "")
            if not pair.endswith("_jpy"):
                continue

            try:
                last_px = float(d.get("last") or 0.0)
                open_px = float(d.get("open") or 0.0)
                high_px = float(d.get("high") or 0.0)
                low_px = float(d.get("low") or 0.0)
                vol = float(d.get("vol") or 0.0)

                turnover = last_px * vol
                chg_pct = ((last_px - open_px) / open_px * 100.0) if open_px > 0.0 else 0.0
                near_high_pct = (last_px / high_px * 100.0) if high_px > 0.0 else 0.0

                if turnover < self.min_turnover_jpy:
                    continue
                if chg_pct < self.min_gain_pct:
                    continue
                if near_high_pct < self.min_high_proximity_pct:
                    continue

                candidates.append({
                    "pair": pair,
                    "last_price": last_px,
                    "change_24h_pct": chg_pct,
                    "turnover_24h_jpy": turnover,
                    "high_24h": high_px,
                    "low_24h": low_px,
                    "proximity_to_high_pct": near_high_pct,
                })
            except (ValueError, TypeError, ZeroDivisionError):
                continue

        # Sort initial screened candidates by 24h gain descending
        candidates.sort(key=lambda x: x["change_24h_pct"], reverse=True)
        return candidates

    def analyze_candidate_technicals(
        self,
        candidate_meta: Dict[str, Any],
        now_dt: Optional[datetime] = None,
    ) -> AltcoinBreakoutCandidate:
        """Fetch recent 15m candles and compute volume surge, RSI, and stop/target prices."""
        pair = candidate_meta["pair"]
        last_px = candidate_meta["last_price"]
        chg_pct = candidate_meta["change_24h_pct"]
        turnover = candidate_meta["turnover_24h_jpy"]
        high_px = candidate_meta["high_24h"]
        low_px = candidate_meta["low_24h"]
        near_high = candidate_meta["proximity_to_high_pct"]

        vol_surge_ratio = 1.0
        rsi = 50.0
        swing_low = last_px * 0.98

        try:
            date_str = resolve_date_param("15min", now_dt)
            raw_candles = self.client.candles(pair, "15min", date_str)
            candles = parse_raw_ohlcv(raw_candles)
            culled_candles = cull_forming_candle(candles, "15min", now_dt)

            if len(culled_candles) >= 5:
                # 1. Volume surge ratio: recent 15m candle volume vs 20-candle average
                recent_vols = [c.volume for c in culled_candles[-20:]]
                avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1.0
                curr_vol = culled_candles[-1].volume
                vol_surge_ratio = (curr_vol / avg_vol) if avg_vol > 0.0 else 1.0

                # 2. 15m Wilder's RSI
                closes = [c.close for c in culled_candles]
                rsi_series = calc_rsi_series(closes, period=14)
                rsi = rsi_series[-1] if rsi_series else 50.0

                # 3. 15m Swing Low Support
                recent_lows = [c.low for c in culled_candles[-4:]]
                if recent_lows:
                    swing_low = min(recent_lows)
        except Exception as e:
            self.logger.debug(f"Candlestick fetch skipped for {pair}: {e}")

        # Compute Stop Loss: Swing low with 0.5% buffer, capped between 1.5% and 3.5% risk
        raw_stop = swing_low * 0.995
        min_allowed_stop = last_px * 0.965  # Max 3.5% stop distance
        max_allowed_stop = last_px * 0.985  # Min 1.5% stop distance
        stop_px = max(min_allowed_stop, min(raw_stop, max_allowed_stop))

        # Take Profit Target: +3.0% standard scalp target
        tp_px = last_px * 1.030

        # Calculate Breakout Score (0 - 100)
        # Components:
        # - 24h Gain (up to 40 pts): 1 pt per 0.5% gain, max 40
        # - Volume Surge (up to 25 pts): 10 pts per 1.0x surge, max 25
        # - RSI Momentum (up to 20 pts): bonus if 55 <= RSI <= 75
        # - Proximity to High (up to 15 pts): (near_high - 85) / 15 * 15
        score_gain = min(40.0, chg_pct * 2.0)
        score_vol = min(25.0, (vol_surge_ratio - 1.0) * 10.0) if vol_surge_ratio > 1.0 else 0.0
        score_rsi = 20.0 if (55.0 <= rsi <= 78.0) else (10.0 if rsi > 50.0 else 0.0)
        score_prox = min(15.0, max(0.0, (near_high - 85.0)))
        total_score = round(max(0.0, min(100.0, score_gain + score_vol + score_rsi + score_prox)), 1)

        actionable = (total_score >= 45.0 and rsi >= 50.0 and vol_surge_ratio >= 1.2)
        summary = (
            f"24h: {chg_pct:+.2f}% | VolSurge: {vol_surge_ratio:.2f}x | "
            f"RSI15m: {rsi:.1f} | ProxHigh: {near_high:.1f}%"
        )

        return AltcoinBreakoutCandidate(
            pair=pair,
            last_price=last_px,
            change_24h_pct=chg_pct,
            turnover_24h_jpy=turnover,
            high_24h=high_px,
            low_24h=low_px,
            proximity_to_high_pct=near_high,
            volume_surge_ratio=vol_surge_ratio,
            rsi_15m=rsi,
            swing_low_stop_price=stop_px,
            take_profit_target_price=tp_px,
            breakout_score=total_score,
            actionable=actionable,
            summary=summary,
        )

    def scan_all_pairs(
        self,
        max_detailed_candidates: int = 5,
        now_dt: Optional[datetime] = None,
    ) -> List[AltcoinBreakoutCandidate]:
        """Perform end-to-end scan across all Bitbank pairs and return ranked candidates."""
        screened = self.screen_candidates()
        top_screened = screened[:max_detailed_candidates]

        detailed_results: List[AltcoinBreakoutCandidate] = []
        for cand in top_screened:
            res = self.analyze_candidate_technicals(cand, now_dt=now_dt)
            detailed_results.append(res)

        detailed_results.sort(key=lambda x: x.breakout_score, reverse=True)
        return detailed_results

    def create_spot_long_plan(
        self,
        candidate: AltcoinBreakoutCandidate,
        free_cash_jpy: float,
        total_equity_jpy: float,
        allocation_pct: float = 0.30,
    ) -> Optional[Dict[str, Any]]:
        """Generate a risk-managed Spot Long trade plan strictly obeying capital limits."""
        # Spot Longs strictly capped at 30% of total equity (PAIR_ALLOC = 0.30)
        max_alloc_jpy = total_equity_jpy * allocation_pct
        budget_jpy = min(max_alloc_jpy, free_cash_jpy)

        if budget_jpy < 1000.0 or candidate.last_price <= 0.0:
            return None

        coin_amount = budget_jpy / candidate.last_price

        # Fetch pair metadata for precision
        pair_info = {}
        try:
            pair_info = self.client.pair_info(candidate.pair)
        except Exception:
            pair_info = {"amount_digits": 4, "price_digits": 2, "min_amount": "0.0001"}

        amount_digits = int(pair_info.get("amount_digits", 4))
        price_digits = int(pair_info.get("price_digits", 2))
        min_amount = float(pair_info.get("min_amount", "0.0001"))

        rounded_amount = round(coin_amount, amount_digits)
        if rounded_amount < min_amount:
            return None

        amt_str = f"{rounded_amount:.{amount_digits}f}"
        stop_str = (
            f"{candidate.swing_low_stop_price:.{price_digits}f}"
            if price_digits > 0
            else str(int(round(candidate.swing_low_stop_price)))
        )
        entry_str = (
            f"{candidate.last_price:.{price_digits}f}"
            if price_digits > 0
            else str(int(round(candidate.last_price)))
        )
        tp_str = (
            f"{candidate.take_profit_target_price:.{price_digits}f}"
            if price_digits > 0
            else str(int(round(candidate.take_profit_target_price)))
        )

        return {
            "pair": candidate.pair,
            "side": "buy",
            "type": "market",  # Or maker limit depending on strategy
            "amount": amt_str,
            "entry_price": entry_str,
            "notional_jpy": rounded_amount * candidate.last_price,
            "protective_stop_order": {
                "pair": candidate.pair,
                "side": "sell",
                "type": "stop",
                "trigger_price": stop_str,
                "amount": amt_str,
            },
            "take_profit_target": tp_str,
            "projected_profit_jpy": (candidate.take_profit_target_price - candidate.last_price) * rounded_amount,
        }

    def format_radar_table(self, candidates: List[AltcoinBreakoutCandidate]) -> str:
        """Render a formatted ASCII table of altcoin breakout opportunities."""
        if not candidates:
            return " No active altcoin breakout candidates detected meeting liquidity threshold."

        lines = [
            " PAIR       24H CHG   TURNOVER        VOL SURGE  RSI(15m)  PROX HIGH  SCORE  ACTION",
            " ───────────────────────────────────────────────────────────────────────────────────",
        ]
        for c in candidates:
            pair_fmt = f"{c.pair:<10}"
            chg_fmt = f"{c.change_24h_pct:+6.2f}%"
            turn_fmt = f"¥{c.turnover_24h_jpy/1e6:5.1f}M"
            vol_fmt = f"{c.volume_surge_ratio:5.2f}x"
            rsi_fmt = f"{c.rsi_15m:5.1f}"
            prox_fmt = f"{c.proximity_to_high_pct:5.1f}%"
            score_fmt = f"{c.breakout_score:5.1f}"
            act_fmt = "READY" if c.actionable else "WATCH"
            lines.append(
                f" {pair_fmt} {chg_fmt}   {turn_fmt}        {vol_fmt}      {rsi_fmt}    {prox_fmt}     {score_fmt}  {act_fmt}"
            )
        return "\n".join(lines)
