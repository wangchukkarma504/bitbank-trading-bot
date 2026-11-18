"""Trading Orchestrator for Bitbank Autonomous Trading System.

Coordinates 6 specialized roles in an autonomous 10-second tick cycle:
- Role 1 (Position Reviewer): Live equity, collateral, open positions, active exchange stop orders, naked position audit.
- Role 3 (Market Trend Analyst): 15m, 1h, 4h EMAs, trend alignment, BTC macro regime filter across 5 pairs.
- Role 4 (Wick Anatomy Analyst): Candlestick bodies, rejection wicks, absorption wicks, exhaustion patterns.
- Role 5 (Technical & Order Book Analyst): Wilder's RSI, momentum divergences, order book depth ratios, support/resistance walls.
- Role 2 (Directional Strategist): Synthesizes signals, enforces BTC macro regime filter, scores setups, outputs trade directives.
- Role 6 (Risk & Profit Execution Manager): Dynamic sizing (1.60x short, 50% long), maker limit orders (post_only: true, -0.02% rebate),
  immediate native exchange stops (type: "stop"), atomic place-before-cancel ratchets, emergency liquidations.
- ASCII Easy Dashboard: Terminal status display, capital milestones (2X, 5X, 10X), active trades, stop orders, market radar.

Resilience & Error Handling:
- Bitbank maintenance window (code 10007) retry loop with exponential backoff.
- Nonce collision (code 20001) randomized jitter retry.
- Rate-limiting inter-pair spacing (0.2s delay).
"""

import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from tradingbot.bitbank import Bitbank, BitbankError
from tradingbot.models import (
    MARGIN_PAIRS,
    SPOT_ONLY_PAIRS,
    SUPPORTED_PAIRS,
    Candle,
    MarketTrendResult,
    WickAnalysisResult,
    TechnicalDepthResult,
    TrendAlignment,
    WickType,
    RsiDivergence,
    RegimeType,
)
from tradingbot.analysis.market_trend import (
    MarketTrendAnalyst,
    evaluate_btc_macro_regime,
)
from tradingbot.analysis.wick_anatomy import WickAnatomyAnalyst
from tradingbot.analysis.technical_depth import TechnicalDepthAnalyst
from tradingbot.analysis.macro_catalyst import MacroCatalystAnalyst, MacroCatalystReport
from tradingbot.analysis.alt_momentum_scanner import AltcoinMomentumScanner, AltcoinBreakoutCandidate
from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.execution.position_reviewer import (
    PositionReviewer,
    PositionReviewResult,
)
from tradingbot.execution.directional_strategist import (
    DirectionalStrategist,
    DirectionalSignal,
)
from tradingbot.execution.risk_manager import (
    RiskManager,
    StopSyncManager,
    calculate_margin_short_size,
    calculate_spot_long_size,
)
from tradingbot.dashboard.ascii_dashboard import (
    AsciiDashboard,
    calc_milestone_progress,
    calc_target_ladder_progress,
    render_ascii_dashboard,
)


logger = logging.getLogger("TradingOrchestrator")


class TradingOrchestrator:
    """Institutional-grade 6-Role Autonomous Trading Orchestrator for Bitbank."""

    DEFAULT_PAIRS: List[str] = list(SUPPORTED_PAIRS)
    BASELINE_BUDGET: float = 10001.0
    TICK_INTERVAL_SEC: float = 10.0
    INTER_PAIR_SLEEP_SEC: float = 0.20

    # Anti-churn & capital preservation circuit breakers
    POST_CLOSE_COOLDOWN_SEC: float = 120.0      # 2 min global cooldown after any position closes
    SAME_PAIR_POST_CLOSE_SEC: float = 300.0     # 5 min same-pair cooldown after a win (allows active multi-trade rotation)
    LOSS_PAIR_COOLDOWN_SEC: float = 900.0       # 15 min same-pair cooldown after a losing close
    MAX_ENTRIES_PER_HOUR: int = 5               # Max 5 new entries per rolling 60-min window
    MAX_CONSECUTIVE_LOSSES: int = 2             # 2 consecutive losses trigger circuit breaker
    RAPID_DRAWDOWN_PAUSE_PCT: float = 0.08      # 8% drop from peak equity pauses new entries
    CIRCUIT_BREAKER_PAUSE_SEC: float = 1800.0   # 30 min pause when circuit breaker trips
    CONSECUTIVE_LOSS_PAUSE_SEC: float = 7200.0  # 2 h pause after consecutive losses (stop-outs cluster in rallies)
    DAILY_LOSS_LIMIT_PCT: float = 0.03          # No new entries for the rest of the JST day once equity is down 3%
    # Frequent mode: profit-lock trailing stop (arm at +0.60%, lock +0.20%, then trail 0.50% behind price).
    # Arming earlier (+0.35%) raised the win rate but lost more per trade in the replay, so it arms later.
    FREQ_TRAIL_ARM_PCT: float = 0.0060
    FREQ_TRAIL_LOCK_PCT: float = 0.0020
    FREQ_TRAIL_DIST_PCT: float = 0.0050
    FREQ_MAX_RISK_PCT: float = 0.010            # 1% of equity per stop-out (half the selective rule's 2%)
    FREQ_MAX_CONSECUTIVE_LOSSES: int = 3
    FREQ_CONSECUTIVE_LOSS_PAUSE_SEC: float = 3600.0
    TP_MAKER_WAIT_SEC: float = 60.0             # How long a resting maker take-profit may wait before a market close

    def __init__(
        self,
        client: Optional[Any] = None,
        baseline_budget_jpy: float = 10001.0,
        mode: str = "dry-run",
        pairs: Optional[List[str]] = None,
        custom_logger: Optional[logging.Logger] = None,
        capital_limit_jpy: Optional[float] = None,
        allow_shorts: bool = True,
        force_profit_close_jpy: Optional[float] = None,
        allow_counter_trend_longs: bool = False,
        daily_state_path: Optional[str] = None,
        news_override_path: Optional[str] = None,
        frequent_mode: bool = False,
        equity_floor_jpy: Optional[float] = None,
    ):
        self.client = client if client is not None else Bitbank()
        self.baseline_budget_jpy = baseline_budget_jpy
        self.capital_limit_jpy: Optional[float] = capital_limit_jpy
        self.allow_shorts: bool = allow_shorts
        self.force_profit_close_jpy: Optional[float] = force_profit_close_jpy
        self.allow_counter_trend_longs: bool = allow_counter_trend_longs
        self.mode = mode.lower()
        self.dry_run = (self.mode == "dry-run")
        self.pairs = pairs or list(self.DEFAULT_PAIRS)
        self.logger = custom_logger or logger

        # Initialize the 6 specialized roles
        self.position_reviewer = PositionReviewer(self.client, baseline_budget_jpy=self.baseline_budget_jpy)
        self.trend_analyst = MarketTrendAnalyst(self.client)
        self.wick_analyst = WickAnatomyAnalyst(self.client)
        self.tech_analyst = TechnicalDepthAnalyst(self.client)
        self.macro_analyst = MacroCatalystAnalyst(cache_ttl_sec=300.0)
        self.alt_scanner = AltcoinMomentumScanner(self.client)
        self.directional_strategist = DirectionalStrategist(
            self.client, allow_counter_trend_longs=self.allow_counter_trend_longs
        )
        self.risk_manager = RiskManager(self.client)
        self.dashboard = AsciiDashboard(starting_budget=self.baseline_budget_jpy)

        # Runtime cycle state
        self.tick_count: int = 0
        self.last_tick_time: float = 0.0
        self.last_review: Optional[PositionReviewResult] = None
        self.last_signals: Dict[str, DirectionalSignal] = {}
        self.last_macro_report: Optional[MacroCatalystReport] = None
        self.last_alt_candidates: List[AltcoinBreakoutCandidate] = []
        self._last_alt_scan_ts: float = 0.0

        # Anti-churn / circuit-breaker tracking
        self._active_tracked_positions: Dict[str, float] = {}
        self._global_cooldown_until: float = 0.0
        self._pair_cooldown_until: Dict[str, float] = {}
        self._recent_entry_timestamps: List[float] = []
        self._consecutive_losses: int = 0
        self._peak_equity_jpy: float = baseline_budget_jpy
        self._circuit_breaker_until: float = 0.0
        self._day_key: Optional[str] = None
        self._day_start_equity_jpy: float = 0.0
        self._daily_loss_halted: bool = False
        # Optional file so the daily loss limit survives restarts (None keeps it in memory only)
        self.daily_state_path: Optional[str] = daily_state_path
        self._load_daily_state()
        self.loss_learner = LossLearningEngine(state_path="loss_lessons.json")
        self._active_position_meta: Dict[str, Dict[str, Any]] = {}
        # Signal that produced each resting entry order, so the journal records the real entry context
        self._pending_entry_signals: Dict[str, DirectionalSignal] = {}
        self._last_exit_reason: Dict[str, str] = {}
        self._orphan_stop_seen: set = set()
        self._tp_limit_since: Dict[str, float] = {}
        # Hard floor: at or below this equity the bot stops opening positions until the operator raises it
        self.equity_floor_jpy: Optional[float] = equity_floor_jpy
        self.equity_floor_hit: bool = False
        self.frequent_mode: bool = False
        self._leverage_override: Optional[float] = None
        self._max_risk_override: Optional[float] = None
        self._selective_limits = (
            self.risk_manager.MAX_RISK_PCT_PER_TRADE, self.MAX_CONSECUTIVE_LOSSES, self.CONSECUTIVE_LOSS_PAUSE_SEC
        )
        self.set_frequent_mode(frequent_mode)
        # Operator news override file: {"bias": "BEARISH"|"BULLISH", "set_at": epoch, "expires_at": epoch, "headline": str}
        self.news_override_path: Optional[str] = news_override_path
        self.news_override: Optional[Dict[str, Any]] = None

    def _load_daily_state(self) -> None:
        if not self.daily_state_path or not os.path.exists(self.daily_state_path):
            return
        try:
            with open(self.daily_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._day_key = str(data["day_key"])
            self._day_start_equity_jpy = float(data["day_start_equity_jpy"])
            self._daily_loss_halted = bool(data.get("halted", False))
        except Exception as e:
            self.logger.warning(f"Failed to load daily risk state from {self.daily_state_path}: {e}")

    NEWS_OVERRIDE_MAX_SEC: float = 4 * 3600.0  # an override older than this is ignored whatever it says

    def _read_news_override(self, now_ts: float) -> Optional[Dict[str, Any]]:
        """Return the active news override, or None when absent, malformed, expired or too old."""
        self.news_override = None
        if not self.news_override_path or not os.path.exists(self.news_override_path):
            return None
        try:
            with open(self.news_override_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            bias = str(data.get("bias", "")).upper()
            expires_at = float(data.get("expires_at", 0.0))
            set_at = float(data.get("set_at", 0.0))
        except Exception as e:
            self.logger.warning(f"Ignoring unreadable news override: {e}")
            return None
        if bias not in ("BEARISH", "BULLISH") or now_ts >= expires_at or data.get("used"):
            return None
        if set_at <= 0 or now_ts - set_at > self.NEWS_OVERRIDE_MAX_SEC or set_at > now_ts + 300:
            return None
        self.news_override = {"bias": bias, "expires_at": expires_at, "set_at": set_at,
                              "headline": str(data.get("headline", ""))[:200]}
        return self.news_override

    def _mark_news_override_used(self) -> None:
        """One trade per override: once a news-driven position opens, the override stops forcing entries."""
        self.news_override = None
        if not self.news_override_path or not os.path.exists(self.news_override_path):
            return
        try:
            with open(self.news_override_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["used"] = True
            with open(self.news_override_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to mark news override as used: {e}")

    def _save_daily_state(self) -> None:
        if not self.daily_state_path:
            return
        try:
            with open(self.daily_state_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "day_key": self._day_key,
                        "day_start_equity_jpy": round(self._day_start_equity_jpy, 2),
                        "halted": self._daily_loss_halted,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            self.logger.warning(f"Failed to save daily risk state to {self.daily_state_path}: {e}")

    def set_frequent_mode(self, enabled: bool) -> None:
        """Switch between the selective rule (default, profitable in replay) and frequent mode (~4 trades/day)."""
        self.frequent_mode = bool(enabled)
        self.directional_strategist.frequent_mode = self.frequent_mode
        risk, max_losses, pause = self._selective_limits
        if self.frequent_mode:
            risk, max_losses, pause = (
                self.FREQ_MAX_RISK_PCT, self.FREQ_MAX_CONSECUTIVE_LOSSES, self.FREQ_CONSECUTIVE_LOSS_PAUSE_SEC
            )
        self.risk_manager.MAX_RISK_PCT_PER_TRADE = risk
        self.MAX_CONSECUTIVE_LOSSES = max_losses
        self.CONSECUTIVE_LOSS_PAUSE_SEC = pause
        self._apply_sizing_overrides()

    def set_sizing_overrides(self, leverage: Optional[float] = None, max_risk_pct: Optional[float] = None) -> None:
        """Operator overrides for position size: leverage (capped at the exchange maximum) and the per-trade
        risk cap. None keeps the mode's default. A risk cap of 1.0 or more disables the cap (full leverage)."""
        self._leverage_override = leverage if leverage and leverage > 0 else None
        self._max_risk_override = max_risk_pct if max_risk_pct and max_risk_pct > 0 else None
        self.set_frequent_mode(self.frequent_mode)

    def _apply_sizing_overrides(self) -> None:
        rm = self.risk_manager
        rm.SHORT_LEVERAGE_FACTOR = min(rm.MAX_EXCHANGE_LEVERAGE, self._leverage_override or type(rm).SHORT_LEVERAGE_FACTOR)
        if self._max_risk_override:
            rm.MAX_RISK_PCT_PER_TRADE = self._max_risk_override

    @staticmethod
    def _plan_pct(sig: Optional[DirectionalSignal], field: str) -> Optional[float]:
        """Distance of the signal's stop/target from its entry, or None when the signal carries no plan."""
        if sig is None or sig.action not in ("SHORT", "LONG"):
            return None
        entry, level = float(sig.entry_price or 0.0), float(getattr(sig, field, 0.0) or 0.0)
        if entry <= 0 or level <= 0:
            return None
        pct = abs(level - entry) / entry
        return pct if 0.002 <= pct <= 0.05 else None

    def _update_churn_guards(self, review_res: PositionReviewResult, now_ts: float) -> None:
        """Track position opens/closes, enforce post-close cooldowns, and trip drawdown/loss circuit breakers."""
        if getattr(review_res, "has_query_error", False):
            return

        equity = float(getattr(review_res, "total_equity_jpy", 0.0))
        if equity > self._peak_equity_jpy:
            self._peak_equity_jpy = equity

        # Daily loss limit: measured from the first equity reading of each JST day (or of this process)
        day_key = time.strftime("%Y-%m-%d", time.gmtime(now_ts + 9 * 3600))
        if equity > 0 and day_key != self._day_key:
            self._day_key = day_key
            self._day_start_equity_jpy = equity
            self._daily_loss_halted = False
            self._save_daily_state()
        if (
            not self._daily_loss_halted
            and self._day_start_equity_jpy > 0
            and 0 < equity <= self._day_start_equity_jpy * (1.0 - self.DAILY_LOSS_LIMIT_PCT)
        ):
            self._daily_loss_halted = True
            self._save_daily_state()
            self.logger.error(
                f"DAILY LOSS LIMIT HIT: equity {equity:,.0f} JPY is down {self.DAILY_LOSS_LIMIT_PCT * 100:.0f}%+ from "
                f"today's start {self._day_start_equity_jpy:,.0f} JPY. No new entries until the next JST day."
            )

        current_open_pairs = {
            pos.get("pair") for pos in review_res.open_positions if pos.get("pair")
        }

        # Detect newly opened positions
        for pos in review_res.open_positions:
            pair = pos.get("pair")
            if pair and pair not in self._active_tracked_positions:
                upnl = float(pos.get("unrealized_pnl_jpy", 0.0) or 0.0)
                self._active_tracked_positions[pair] = equity - upnl
                self._recent_entry_timestamps.append(now_ts)
                sig = self._pending_entry_signals.pop(pair, None) or self.last_signals.get(pair)
                macro_bias = getattr(self.last_macro_report, "catalyst_bias", "NEUTRAL") if self.last_macro_report else "NEUTRAL"
                if sig is not None and getattr(sig, "news_driven", False):
                    self.logger.warning(f"News-driven {pair} position opened; the news override is now used up.")
                    self._mark_news_override_used()
                self._active_position_meta[pair] = {
                    "entry_time": now_ts,
                    "side": pos.get("position_side", "short"),
                    "entry_conviction": getattr(sig, "conviction", 0.0) if sig else 0.0,
                    "depth_ratio": getattr(sig, "depth_ratio", 1.0) if sig else 1.0,
                    "wick_classification": str(getattr(sig, "wick_classification", "NONE")) if sig else "NONE",
                    "macro_bias": macro_bias,
                    # Exit plan the position was sized for (news trades use a wider stop and target)
                    "stop_pct": self._plan_pct(sig, "stop_loss_price"),
                    "tp_pct": self._plan_pct(sig, "take_profit_price"),
                    "context": {
                        "entry_rsi": float(getattr(sig, "rsi", 0.0) or 0.0) if sig else 0.0,
                        "trend_4h": str(getattr(sig, "trend_alignment", "")) if sig else "",
                        "trend_1h": str(getattr(sig, "trend_1h", "")) if sig else "",
                        "trend_15m": str(getattr(sig, "trend_15m", "")) if sig else "",
                        "entry_price": float(pos.get("avg_price", pos.get("average_price", 0.0)) or 0.0),
                    },
                }

        # Detect closed positions (transitioned from open -> flat)
        closed_pairs = [
            p for p in list(self._active_tracked_positions.keys()) if p not in current_open_pairs
        ]
        for pair in closed_pairs:
            entry_eq = self._active_tracked_positions.pop(pair)
            meta = self._active_position_meta.pop(pair, {})
            hold_sec = max(0.0, now_ts - float(meta.get("entry_time", now_ts)))
            lesson = self.loss_learner.record_trade_close(
                pair=pair,
                side=str(meta.get("side", "short")),
                entry_equity_jpy=entry_eq,
                exit_equity_jpy=equity,
                hold_duration_sec=hold_sec,
                entry_conviction=float(meta.get("entry_conviction", 0.0)),
                depth_ratio=float(meta.get("depth_ratio", 1.0)),
                wick_classification=str(meta.get("wick_classification", "NONE")),
                macro_bias=str(meta.get("macro_bias", "NEUTRAL")),
                now_ts=now_ts,
                context={
                    **(meta.get("context") or {}),
                    "exit_reason": self._last_exit_reason.pop(pair, "EXCHANGE_STOP_OR_MANUAL"),
                },
            )
            self._global_cooldown_until = max(
                self._global_cooldown_until, now_ts + self.POST_CLOSE_COOLDOWN_SEC
            )
            if lesson.is_loss:
                self._consecutive_losses += 1
                pair_cd = self.LOSS_PAIR_COOLDOWN_SEC * self.loss_learner.get_pair_cooldown_multiplier(pair)
                self._pair_cooldown_until[pair] = max(
                    self._pair_cooldown_until.get(pair, 0.0),
                    now_ts + pair_cd,
                )
                self.logger.warning(
                    f"Position closed at loss on {pair} (eq {entry_eq:,.0f} -> {equity:,.0f} JPY). "
                    f"Cause={lesson.root_cause} | Fix={lesson.fix_applied} | "
                    f"Pair cooldown {pair_cd:.0f}s, consecutive losses={self._consecutive_losses}."
                )
                if self._consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                    self._circuit_breaker_until = max(
                        self._circuit_breaker_until, now_ts + self.CONSECUTIVE_LOSS_PAUSE_SEC
                    )
                    self.logger.error(
                        f"CIRCUIT BREAKER TRIPPED: {self._consecutive_losses} consecutive losses. "
                        f"Pausing new entries for {self.CONSECUTIVE_LOSS_PAUSE_SEC / 60:.0f} minutes."
                    )
            else:
                self._consecutive_losses = 0
                self._pair_cooldown_until[pair] = max(
                    self._pair_cooldown_until.get(pair, 0.0),
                    now_ts + self.SAME_PAIR_POST_CLOSE_SEC,
                )
                self.logger.info(
                    f"Position closed on {pair} (eq {entry_eq:,.0f} -> {equity:,.0f} JPY). "
                    f"Global cooldown {self.POST_CLOSE_COOLDOWN_SEC:.0f}s + {pair} cooldown {self.SAME_PAIR_POST_CLOSE_SEC:.0f}s active."
                )

        # Rapid session drawdown guard
        if (
            self._peak_equity_jpy > 0
            and equity > 0
            and (self._peak_equity_jpy - equity) / self._peak_equity_jpy >= self.RAPID_DRAWDOWN_PAUSE_PCT
            and now_ts >= self._circuit_breaker_until
        ):
            dd_pct = ((self._peak_equity_jpy - equity) / self._peak_equity_jpy) * 100.0
            self._circuit_breaker_until = now_ts + self.CIRCUIT_BREAKER_PAUSE_SEC
            self.logger.error(
                f"CIRCUIT BREAKER TRIPPED: Rapid drawdown -{dd_pct:.2f}% from peak {self._peak_equity_jpy:,.0f} JPY. "
                f"Pausing new entries for {self.CIRCUIT_BREAKER_PAUSE_SEC / 60:.0f} minutes."
            )

    def safe_api_call(
        self,
        func,
        *args,
        max_retries: int = 60,
        retry_delay: float = 10.0,
        **kwargs,
    ) -> Any:
        """Execute API call with automatic Bitbank maintenance (10007) and nonce collision (20001) handling."""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except BitbankError as e:
                err_msg = str(e)
                if "10007" in err_msg:
                    # Bitbank maintenance window
                    self.logger.warning(
                        f"Bitbank maintenance window active (code 10007). Retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(retry_delay)
                    continue
                elif "20001" in err_msg:
                    # Nonce collision: backoff with random jitter
                    jitter = 0.3 + 0.5 * random.random()
                    self.logger.info(f"Nonce collision (code 20001). Backing off {jitter:.2f}s...")
                    time.sleep(jitter)
                    continue
                else:
                    raise
        raise BitbankError(f"API call failed after {max_retries} retries")

    def tick(self) -> Dict[str, Any]:
        """Execute one complete 10-second tick cycle across all 6 roles."""
        self.tick_count += 1
        self.last_tick_time = time.time()

        # =====================================================================
        # STEP 1: Role 1 (Position Reviewer)
        # =====================================================================
        # Poll live equity, collateral, open positions, active exchange stop orders
        review_query_failed = False
        try:
            review_res = self.safe_api_call(
                self.position_reviewer.review, client=self.client, allow_shorts=self.allow_shorts
            )
        except Exception as e:
            self.logger.error(f"Position review query failed: {e}")
            review_query_failed = True
            if self.last_review:
                review_res = self.last_review
            else:
                review_res = PositionReviewResult(
                    baseline_budget_jpy=self.baseline_budget_jpy,
                    total_equity_jpy=self.baseline_budget_jpy,
                    free_cash_jpy=self.baseline_budget_jpy,
                    locked_cash_jpy=0.0,
                    buying_power_jpy=self.baseline_budget_jpy * 2.0,
                    pnl_jpy=0.0,
                    pnl_pct=0.0,
                    open_positions=[],
                    active_stops=[],
                    naked_positions=[],
                    is_fully_protected=True,
                    open_risk_jpy=0.0,
                    timestamp=int(time.time() * 1000),
                )
        self.last_review = review_res
        # Pairs that had a position on the previous clean review: if one is flat now, its stop is a leftover
        previously_open_pairs = set(self._active_tracked_positions)
        if not review_query_failed:
            self._update_churn_guards(review_res, now_ts=self.last_tick_time)

        # Capital Preservation Guardrail: Enforce Zero Naked Positions (only when active_orders query succeeded)
        if review_res.naked_positions and not review_query_failed and not getattr(review_res, "has_query_error", False):
            self.logger.warning(
                f"AUDIT WARNING: {len(review_res.naked_positions)} unprotected position(s) detected!"
            )
            for naked_pos in review_res.naked_positions:
                pair = naked_pos["pair"]
                full_amt = float(naked_pos.get("open_amount", naked_pos.get("amount", naked_pos.get("unprotected_amount", 0.0))))
                side = naked_pos.get("position_side", "short")
                pos_type = naked_pos.get("position_type", "margin")
                stop_pos_side = None if pos_type == "spot" else side
                last_px = float(naked_pos.get("last_price", naked_pos.get("avg_price", 0.0)))
                cfg = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS.get(pair)
                ad = cfg.amount_digits if cfg else 4
                amt_str = f"{full_amt:.{ad}f}"

                # A resting maker entry normally fills between ticks, so this is the usual way a new position
                # gets its stop. Use the planned distance from the ENTRY price (what the position was sized for),
                # not a distance from the current price, which silently widened the risk after any adverse move.
                avg_px = float(naked_pos.get("avg_price", naked_pos.get("average_price", 0.0)) or 0.0)
                ref_px = avg_px if avg_px > 0 else last_px
                stop_pct = (self._active_position_meta.get(pair) or {}).get("stop_pct") or self.directional_strategist.STOP_PCT
                planned = ref_px * (1.0 + stop_pct) if side == "short" else ref_px * (1.0 - stop_pct)
                stop_trig = self.loss_learner.adjust_stop_price(ref_px, planned, side)
                stop_breached = last_px > 0 and (
                    (side == "short" and last_px >= stop_trig) or (side != "short" and last_px <= stop_trig)
                )

                if stop_breached and not self.dry_run:
                    # Price is already through the planned stop: close now instead of parking a stop further away
                    self.logger.error(
                        f"Unprotected {pair} {side} is already past its planned stop ({last_px} vs {stop_trig:.4f}); closing at market."
                    )
                    self._last_exit_reason[pair] = "STOP_ALREADY_BREACHED"
                    self.risk_manager.emergency_market_cover(pair, client=self.client)
                    review_res.open_positions = [p for p in review_res.open_positions if p.get("pair") != pair]
                    continue

                if not self.dry_run:
                    self.logger.info(f"Attaching immediate protective stop on naked {pair} {side} at {stop_trig}...")
                    try:
                        self.risk_manager.attach_protective_stop(
                            pair=pair,
                            amount=amt_str,
                            trigger_price=stop_trig,
                            position_side=stop_pos_side,
                            client=self.client,
                        )
                    except Exception as e:
                        self.logger.error(f"Failed to place protective stop on {pair}: {e}. Triggering emergency cover.")
                        self.risk_manager.emergency_market_cover(pair, client=self.client)
                else:
                    self.logger.info(
                        f"[DRY-RUN AUDIT] Would attach native exchange stop on naked {pair} ({side}): qty={amt_str}, trigger={stop_trig:,.1f}"
                    )

        # Orphan stop cleanup: a stop left behind after its position closed (e.g. the maker take-profit filled
        # first) would later be counted as protection for a NEW position at a stale price. Cancel it once the
        # pair has been flat on two consecutive clean reviews.
        if (
            not self.dry_run
            and self.allow_shorts
            and not review_query_failed
            and not getattr(review_res, "has_query_error", False)
        ):
            open_pairs_now = {p.get("pair") for p in review_res.open_positions}
            orphan_ids = set()
            remaining_stops = []
            for s in review_res.active_stops:
                s_pair, s_oid = s.get("pair"), s.get("order_id")
                if s_pair in open_pairs_now or s_oid is None:
                    remaining_stops.append(s)
                    continue
                orphan_ids.add(s_oid)
                # A position that just closed (e.g. its maker take-profit filled) leaves a certain orphan: cancel
                # at once. Otherwise wait for a second sighting, in case a brand-new position is just appearing.
                if s_oid in self._orphan_stop_seen or s_pair in previously_open_pairs:
                    self.logger.warning(f"Cancelling orphan stop {s_oid} on {s_pair}: no open position on this pair.")
                    try:
                        self.client.cancel(s_pair, s_oid)
                    except Exception as e:
                        self.logger.warning(f"Failed to cancel orphan stop {s_oid} on {s_pair}: {e}")
                        remaining_stops.append(s)
                        continue
                    mgr = self.risk_manager.get_sync_manager(s_pair, self.client)
                    if mgr.current_stop_id == s_oid:
                        mgr.current_stop_id = None
                        mgr.current_stop_level = None
                        mgr.current_stop_qty = None
                else:
                    remaining_stops.append(s)
            self._orphan_stop_seen = orphan_ids
            review_res.active_stops = remaining_stops

        # =====================================================================
        # STEP 2: Role 3 (Market Trend Analyst) - BTC Macro Regime Filter
        # =====================================================================
        btc_regime_bullish = False
        try:
            btc_regime_bullish = self.safe_api_call(self.trend_analyst.evaluate_btc_regime, client=self.client)
        except Exception as e:
            self.logger.warning(f"Failed to evaluate BTC macro regime: {e}")

        # =====================================================================
        # STEP 2B: Live Macro & News Catalyst Predictor + 60+ Altcoin Radar (5-min cached)
        # =====================================================================
        macro_report: Optional[MacroCatalystReport] = self.last_macro_report
        try:
            macro_report = self.macro_analyst.analyze()
            self.last_macro_report = macro_report
        except Exception as e:
            self.logger.warning(f"Macro catalyst scan failed (using fallback): {e}")

        now_sec = time.time()
        if (now_sec - self._last_alt_scan_ts) >= 300.0 and hasattr(self.client, "tickers"):
            try:
                self.last_alt_candidates = self.alt_scanner.scan_all_pairs(max_detailed_candidates=5)
                self._last_alt_scan_ts = now_sec
            except Exception as e:
                self.logger.warning(f"Altcoin 60+ pair breakout scan failed: {e}")

        # =====================================================================
        # STEP 3 & 4: Roles 4 & 5 (Wick Anatomy & Technical Depth Analysts)
        # STEP 5: Role 2 (Directional Strategist) - Multi-pair Synthesis
        # =====================================================================
        news = self._read_news_override(self.last_tick_time)
        news_bias = news["bias"] if news else None
        signals: Dict[str, DirectionalSignal] = {}
        for pair in self.pairs:
            try:
                # Rate-limit compliant spacing between pair queries
                time.sleep(self.INTER_PAIR_SLEEP_SEC)

                eval_kwargs: Dict[str, Any] = {}
                if news_bias:
                    eval_kwargs["news_bias"] = news_bias
                sig = self.directional_strategist.evaluate_pair(
                    pair=pair,
                    btc_regime_bullish=btc_regime_bullish,
                    macro_report=macro_report,
                    client=self.client,
                    **eval_kwargs,
                )
                signals[pair] = sig
            except Exception as e:
                self.logger.warning(f"Market analysis failed for {pair}: {e}")

        self.last_signals = signals

        # =====================================================================
        # STEP 6: Role 6 (Risk & Profit Execution Manager)
        # =====================================================================
        # A. Position Management & Trailing Ratchets for Existing Positions
        # Never manage positions from stale or incomplete data: with a failed review the position list is the
        # previous tick's, and with a partial order query we cannot see which close orders already rest. The
        # exchange-side stop keeps protecting the position until the next clean review.
        review_incomplete = review_query_failed or bool(getattr(review_res, "has_query_error", False))
        managed_positions = [] if review_incomplete else review_res.open_positions
        open_pairs_for_tp = {p.get("pair") for p in review_res.open_positions}
        for stale_pair in [p for p in self._tp_limit_since if p not in open_pairs_for_tp]:
            self._tp_limit_since.pop(stale_pair, None)
        close_limit_ids = set()
        for pos in managed_positions:
            pair = pos.get("pair")
            last_px = float(pos.get("last_price", 0.0))
            side = pos.get("position_side", "short")
            avg_px = float(pos.get("avg_price", pos.get("average_price", 0.0)))
            amt_str = str(pos.get("open_amount", pos.get("amount", "0.0000")))

            upnl = float(pos.get("unrealized_pnl_jpy", 0.0) or 0.0)
            notional = float(pos.get("notional_jpy", 0.0) or 0.0)
            est_net_pnl = upnl - (notional * 0.0012)
            force_tp_hit = (
                self.force_profit_close_jpy is not None
                and self.force_profit_close_jpy > 0
                and est_net_pnl >= self.force_profit_close_jpy
            )

            # Check take-profit exit condition (targets come from the strategist's backtested exit geometry)
            tp_hit = force_tp_hit
            is_emergency_close = False
            if not tp_hit and side == "short" and avg_px > 0:
                plan_tp = (self._active_position_meta.get(pair) or {}).get("tp_pct")
                target_px = avg_px * (1.0 - (plan_tp or self.directional_strategist.SHORT_TP_PCT))
                if last_px <= target_px and last_px > 0:
                    tp_hit = True
            elif not tp_hit and side == "long" and avg_px > 0:
                plan_tp = (self._active_position_meta.get(pair) or {}).get("tp_pct")
                target_px = avg_px * (
                    1.012 if (pair in SPOT_ONLY_PAIRS and self.allow_counter_trend_longs)
                    else 1.0 + (plan_tp or self.directional_strategist.LONG_TP_PCT)
                )
                if last_px >= target_px and last_px > 0:
                    tp_hit = True
                elif pair in SPOT_ONLY_PAIRS and last_px > 0 and last_px <= avg_px * 0.985:
                    # In-process -1.5% hard stop for spot-only pairs that lack native Bitbank stop orders
                    self.logger.warning(f"[SPOT STOP] {pair} hit -1.5% stop ({last_px} <= {avg_px * 0.985:.4f}); closing.")
                    tp_hit = True
                    is_emergency_close = True

            # Automated early-cut if position is underwater >= -0.55% AND orderbook depth flipped heavily against it
            if not tp_hit and avg_px > 0 and last_px > 0:
                gain_pct = ((avg_px - last_px) / avg_px) if side == "short" else ((last_px - avg_px) / avg_px)
                sig = self.last_signals.get(pair)
                depth_ratio = float(getattr(sig, "depth_ratio", 1.0) or 1.0) if sig else 1.0
                if gain_pct <= -0.0055 and (
                    (side == "short" and depth_ratio >= 1.80) or (side == "long" and depth_ratio <= 0.55)
                ):
                    self.logger.warning(
                        f"[EARLY THESIS CUT] {pair} {side} at {gain_pct*100:.2f}% with opposing depth_ratio={depth_ratio:.2f}; closing early."
                    )
                    tp_hit = True
                    is_emergency_close = True

            if tp_hit:
                self._last_exit_reason[pair] = (
                    "FORCE_PROFIT_CLOSE" if force_tp_hit else ("EARLY_CUT_OR_SPOT_STOP" if is_emergency_close else "TAKE_PROFIT")
                )
                if force_tp_hit:
                    self.logger.info(
                        f"[FORCE PROFIT CLOSE] Target ¥{self.force_profit_close_jpy:,.0f} reached "
                        f"(est. net +¥{est_net_pnl:,.1f}) for {pair} {side} at {last_px:,.1f} JPY!"
                    )
                else:
                    self.logger.info(f"Target take-profit reached for {pair} {side} at {last_px:,.1f} JPY!")
                if not self.dry_run:
                    mgr = self.risk_manager.get_sync_manager(pair, self.client)
                    cover_side = "buy" if side == "short" else "sell"
                    pos_side_arg = side if (pair in MARGIN_PAIRS and side in ("short", "long") and pos.get("position_type", "margin") != "spot") else None
                    # Try post-only maker limit close on normal TPs to earn -0.02% rebate instead of paying 0.12% taker fee
                    maker_tp_filled = False
                    maker_tp_resting = False
                    # A close order already resting from an earlier tick: never stack a second one on top of it
                    # (two could fill in one fast move). Let it work for TP_MAKER_WAIT_SEC, then close at market.
                    existing_tp = [
                        o for o in review_res.active_orders
                        if o.get("pair") == pair and o.get("type") == "limit" and o.get("side") == cover_side
                    ]
                    close_limit_ids.update(o.get("order_id") for o in existing_tp)
                    if existing_tp and not is_emergency_close and not force_tp_hit:
                        first_seen = self._tp_limit_since.setdefault(pair, self.last_tick_time)
                        if self.last_tick_time - first_seen <= self.TP_MAKER_WAIT_SEC:
                            maker_tp_resting = True
                        else:
                            self.logger.info(f"Maker take-profit on {pair} did not fill in {self.TP_MAKER_WAIT_SEC:.0f}s; closing at market.")
                    elif not is_emergency_close and not force_tp_hit and last_px > 0:
                        cfg_p = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS.get(pair)
                        pd_p = cfg_p.price_digits if cfg_p else 1
                        tp_px_str = f"{last_px:.{pd_p}f}" if pd_p > 0 else str(int(round(last_px)))
                        try:
                            tp_kwargs = {"side": cover_side, "amount": amt_str, "price": tp_px_str, "type_": "limit", "post_only": True}
                            if pos_side_arg:
                                tp_kwargs["position_side"] = pos_side_arg
                            tp_res = self.client.order(pair, **tp_kwargs)
                            if tp_res.get("status") == "FULLY_FILLED":
                                maker_tp_filled = True
                            elif tp_res.get("order_id") is not None:
                                maker_tp_resting = True
                                self._tp_limit_since[pair] = self.last_tick_time
                        except Exception:
                            pass

                    if not maker_tp_resting:
                        # Cancel all existing active orders/stops on pair so nothing remains locked
                        cancelled_ids = set()
                        if mgr.current_stop_id:
                            try:
                                self.client.cancel(pair, mgr.current_stop_id)
                                cancelled_ids.add(mgr.current_stop_id)
                            except Exception:
                                pass
                        for o in (list(review_res.active_stops) + list(review_res.active_orders)):
                            oid = o.get("order_id")
                            if o.get("pair") == pair and oid is not None and oid not in cancelled_ids:
                                try:
                                    self.client.cancel(pair, oid)
                                    cancelled_ids.add(oid)
                                except Exception:
                                    pass
                        if not maker_tp_filled:
                            # Fallback to market close if post-only didn't fill/rest
                            try:
                                if pos_side_arg:
                                    self.client.order(pair, side=cover_side, amount=amt_str, type_="market", position_side=pos_side_arg)
                                else:
                                    self.client.order(pair, side=cover_side, amount=amt_str, type_="market")
                            except Exception as e:
                                self.logger.error(f"Take-profit close failed on {pair}: {e}")
                        # If a cancel above failed, the stop is now an orphan: mark it so the cleanup at the
                        # start of the next tick removes it at first sight instead of waiting a second tick.
                        if mgr.current_stop_id is not None:
                            self._orphan_stop_seen.add(mgr.current_stop_id)
                        self._orphan_stop_seen.update(
                            o.get("order_id") for o in review_res.active_stops if o.get("pair") == pair
                        )
                        mgr.current_stop_id = None
                        mgr.current_stop_level = None
                        mgr.current_stop_qty = None
                        self.position_reviewer.spot_entry_prices.pop(pair, None)
                        self._tp_limit_since.pop(pair, None)
                else:
                    self.logger.info(f"[DRY-RUN] Take-Profit execution simulated for {pair}")

            elif not self.dry_run:
                # Price left the take-profit zone: pull any resting close order and go back to the stop
                leave_side = "buy" if side == "short" else "sell"
                for o in review_res.active_orders:
                    if o.get("pair") == pair and o.get("type") == "limit" and o.get("side") == leave_side:
                        close_limit_ids.add(o.get("order_id"))
                        try:
                            self.client.cancel(pair, o.get("order_id"))
                        except Exception as e:
                            self.logger.warning(f"Failed to cancel resting take-profit {o.get('order_id')} on {pair}: {e}")
                self._tp_limit_since.pop(pair, None)
                # Apply trailing ratchets (only the >= +1.6% trailing lock is active by default)
                trail_kwargs: Dict[str, Any] = {}
                if self.frequent_mode:
                    trail_kwargs = {
                        "trail_arm_pct": self.FREQ_TRAIL_ARM_PCT,
                        "trail_lock_pct": self.FREQ_TRAIL_LOCK_PCT,
                        "trail_dist_pct": self.FREQ_TRAIL_DIST_PCT,
                    }
                try:
                    self.risk_manager.evaluate_and_apply_ratchets(
                        pair=pair,
                        position=pos,
                        current_price=last_px,
                        client=self.client,
                        active_stops=review_res.active_stops,
                        **trail_kwargs,
                    )
                except Exception as e:
                    self.logger.warning(f"Trailing ratchet check failed on {pair}: {e}")

        # B. Stale Resting Limit Order Management & Entry Evaluation
        # Close orders handled above are not entry orders: keep them out of the stale-entry logic
        active_limits = [
            o for o in review_res.active_orders
            if o.get("type") == "limit" and o.get("order_id") not in close_limit_ids
        ]
        cancelled_any_limit = False
        if active_limits and not self.dry_run:
            now_ms = int(time.time() * 1000)
            remaining_limits = []
            for lim in active_limits:
                l_pair = lim.get("pair")
                l_oid = lim.get("order_id")
                l_px = float(lim.get("price", 0.0))
                ordered_at = int(lim.get("ordered_at", now_ms))
                age_sec = (now_ms - ordered_at) / 1000.0
                sig = signals.get(l_pair)
                l_side = lim.get("side")

                # Cancel if older than 10 min, signal flipped/neutral, or price drifted > 1.0% away
                signal_invalid = (
                    sig is None
                    or sig.action == "NEUTRAL"
                    or (l_side == "sell" and sig.action != "SHORT")
                    or (l_side == "buy" and sig.action != "LONG")
                )
                price_drifted = (
                    sig is not None
                    and l_px > 0
                    and sig.entry_price > 0
                    and abs(sig.entry_price - l_px) / l_px > 0.010
                )
                if age_sec > 600.0 or signal_invalid or price_drifted:
                    self.logger.info(
                        f"Cancelling stale resting limit {l_pair} #{l_oid} "
                        f"(age={age_sec:.0f}s, invalid={signal_invalid}, drifted={price_drifted})"
                    )
                    try:
                        self.client.cancel(l_pair, l_oid)
                        cancelled_any_limit = True
                    except Exception as e:
                        self.logger.warning(f"Failed to cancel stale limit {l_oid}: {e}")
                        remaining_limits.append(lim)
                else:
                    remaining_limits.append(lim)
            active_limits = remaining_limits

        # Only enter new position when flat, NO active limit orders, no API errors, and anti-churn guards clear
        now_ts = self.last_tick_time
        self._recent_entry_timestamps = [t for t in self._recent_entry_timestamps if (now_ts - t) < 3600.0]
        churn_blocked = False
        floor = self.equity_floor_jpy
        floor_hit = bool(floor and floor > 0 and not review_query_failed and 0 < review_res.total_equity_jpy <= floor)
        if floor_hit and not self.equity_floor_hit:
            self.logger.error(
                f"EQUITY FLOOR HIT: equity {review_res.total_equity_jpy:,.0f} JPY <= floor {floor:,.0f} JPY. "
                f"No new entries until the floor is lowered or equity recovers."
            )
        if not review_query_failed:
            self.equity_floor_hit = floor_hit
        if self.equity_floor_hit:
            churn_blocked = True
        elif self._daily_loss_halted:
            churn_blocked = True
        elif now_ts < self._circuit_breaker_until:
            churn_blocked = True
        elif now_ts < self._global_cooldown_until:
            churn_blocked = True
        elif len(self._recent_entry_timestamps) >= self.MAX_ENTRIES_PER_HOUR:
            self._circuit_breaker_until = now_ts + self.CIRCUIT_BREAKER_PAUSE_SEC
            self.logger.error(
                f"CIRCUIT BREAKER TRIPPED: {len(self._recent_entry_timestamps)} entries in <1h "
                f"(cap={self.MAX_ENTRIES_PER_HOUR}). Pausing new entries for {self.CIRCUIT_BREAKER_PAUSE_SEC / 60:.0f} minutes."
            )
            churn_blocked = True

        if (
            len(review_res.open_positions) == 0
            and len(active_limits) == 0
            and not cancelled_any_limit
            and not review_query_failed
            and not getattr(review_res, "has_query_error", False)
            and not churn_blocked
        ):
            # Rank signals by learned-adjusted conviction (skipping pairs in loss cooldown)
            best_candidate: Optional[DirectionalSignal] = None
            best_eff_conv: float = 0.0
            for pair, sig in signals.items():
                if now_ts < self._pair_cooldown_until.get(pair, 0.0):
                    continue
                if sig.action not in ("SHORT", "LONG"):
                    continue
                if sig.action == "SHORT" and (not self.allow_shorts or pair not in MARGIN_PAIRS):
                    continue
                sig_side = "short" if sig.action == "SHORT" else "long"
                eff_conv = self.loss_learner.adjust_signal_conviction(
                    sig.conviction, side=sig_side, depth_ratio=getattr(sig, "depth_ratio", 1.0)
                )
                req_conv = self.loss_learner.get_effective_min_conviction(
                    pair, self.directional_strategist.MIN_CONVICTION
                )
                if eff_conv >= req_conv:
                    if best_candidate is None or eff_conv > best_eff_conv:
                        best_candidate = sig
                        best_eff_conv = eff_conv

            if best_candidate is not None and review_res.total_equity_jpy <= 0:
                self.logger.error("Equity is not positive; skipping new entries.")
                best_candidate = None

            if best_candidate is not None:
                equity = review_res.total_equity_jpy
                if self.capital_limit_jpy is not None and self.capital_limit_jpy > 0:
                    equity = min(equity, float(self.capital_limit_jpy))
                order_side = "sell" if best_candidate.action == "SHORT" else "buy"
                pos_side = "short" if best_candidate.action == "SHORT" else "long"
                pos_type = "margin" if best_candidate.action == "SHORT" else "spot"
                adj_stop_px = self.loss_learner.adjust_stop_price(
                    best_candidate.entry_price, best_candidate.stop_loss_price, pos_side
                )

                sizing_plan = self.risk_manager.create_sizing_plan(
                    equity_jpy=equity,
                    pair=best_candidate.pair,
                    side=order_side,
                    entry_price=best_candidate.entry_price,
                    stop_loss_price=adj_stop_px,
                    take_profit_price=best_candidate.take_profit_price,
                    position_type=pos_type,
                    free_cash_jpy=review_res.free_cash_jpy,
                )

                if sizing_plan.target_amount <= 0 or sizing_plan.allocation_notional_jpy <= 0:
                    self.logger.warning(
                        f"Skipping {best_candidate.pair} {best_candidate.action}: quantized qty={sizing_plan.formatted_amount} is zero."
                    )
                elif not self.dry_run:
                    self.logger.info(
                        f"Executing maker limit order for {best_candidate.pair} {best_candidate.action}: "
                        f"qty={sizing_plan.formatted_amount}, px={best_candidate.entry_price}"
                    )
                    try:
                        if pos_type == "spot":
                            self.position_reviewer.spot_entry_prices[best_candidate.pair] = best_candidate.entry_price
                        self._pending_entry_signals[best_candidate.pair] = best_candidate
                        order_res = self.risk_manager.place_maker_limit_order(
                            pair=best_candidate.pair,
                            side=order_side,
                            amount=sizing_plan.formatted_amount,
                            price=best_candidate.entry_price,
                            position_side="short" if best_candidate.action == "SHORT" else None,
                            client=self.client,
                        )
                        # If filled immediately, attach native exchange stop for margin-capable pairs
                        if order_res.get("status") == "FULLY_FILLED" and best_candidate.pair in MARGIN_PAIRS:
                            self.risk_manager.attach_protective_stop(
                                pair=best_candidate.pair,
                                amount=sizing_plan.formatted_amount,
                                trigger_price=adj_stop_px,
                                position_side="short" if best_candidate.action == "SHORT" else None,
                                client=self.client,
                            )
                    except Exception as e:
                        self.logger.error(f"Failed to place maker order on {best_candidate.pair}: {e}")
                else:
                    self.logger.info(
                        f"[DRY-RUN ENTRY] Sizing: {best_candidate.pair} {order_side.upper()} "
                        f"qty={sizing_plan.formatted_amount} (notional=¥{sizing_plan.allocation_notional_jpy:,.0f}, "
                        f"entry={best_candidate.entry_price:,.1f}, stop={best_candidate.stop_loss_price:,.1f})"
                    )

        # =====================================================================
        # STEP 7: Render ASCII Easy Dashboard
        # =====================================================================
        dashboard_output = self.dashboard.render(
            client=self.client,
            position_review=review_res,
            signals=signals,
            open_positions=review_res.open_positions,
            active_stops=review_res.active_stops,
            total_equity=review_res.total_equity_jpy,
            macro_report=macro_report,
            alt_candidates=self.last_alt_candidates,
        )

        return {
            "tick": self.tick_count,
            "review": review_res,
            "signals": signals,
            "macro_report": macro_report,
            "dashboard": dashboard_output,
        }

    def run_loop(
        self,
        interval: float = 10.0,
        once: bool = False,
        max_ticks: Optional[int] = None,
    ) -> None:
        """Run coordinated autonomous multi-role trading loop."""
        print(f"\nStarting Bitbank Autonomous Multi-Role Orchestrator [{self.mode.upper()} MODE]...")
        print(f"Monitoring pairs: {', '.join(self.pairs)}")
        print(f"Tick interval: {interval:.1f}s | Baseline budget: ¥{self.baseline_budget_jpy:,.0f} JPY\n")

        while True:
            try:
                res = self.tick()
                print(res["dashboard"])

                if once:
                    break

                if max_ticks is not None and self.tick_count >= max_ticks:
                    break

                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nReceived user interrupt. Shutting down Trading Orchestrator gracefully.")
                break
            except Exception as e:
                self.logger.error(f"Error during tick execution: {e}", exc_info=True)
                if once:
                    raise
                time.sleep(interval)
