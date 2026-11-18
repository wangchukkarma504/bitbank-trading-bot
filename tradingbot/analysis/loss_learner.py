"""Auto-Detect Loss Analyzer & Self-Learning Engine.

Automatically detects closed losing trades, diagnoses the root cause
(e.g. FAST_WHIPSAW_STOP, ORDERBOOK_IMBALANCE_TRAP, COUNTER_MACRO_BIAS,
WEAK_CONVICTION_ENTRY, TREND_REVERSAL_EXHAUSTION), persists lessons to disk,
and applies bounded, safe parameter adaptations to prevent repeating the same mistake.
"""

from dataclasses import asdict, dataclass, field
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional


logger = logging.getLogger("LossLearner")


@dataclass
class TradeLesson:
    timestamp: float
    pair: str
    side: str
    entry_equity_jpy: float
    exit_equity_jpy: float
    pnl_jpy: float
    pnl_pct: float
    hold_duration_sec: float
    is_loss: bool
    root_cause: str
    fix_applied: str
    entry_conviction: float = 0.0
    depth_ratio: float = 1.0
    wick_classification: str = "NONE"
    macro_bias: str = "NEUTRAL"
    # Entry context and exit type, so each closed trade can be reviewed against the backtest
    entry_rsi: float = 0.0
    trend_4h: str = ""
    trend_1h: str = ""
    trend_15m: str = ""
    entry_price: float = 0.0
    exit_reason: str = ""


class LossLearningEngine:
    """Detects losses, diagnoses causes, persists lessons, and adapts safe entry/stop guardrails."""

    MAX_CONVICTION_BOOST: float = 0.25      # Never raise required conviction above base + 0.25 (capped at 0.92)
    MAX_STOP_WIDTH_MULT: float = 1.25       # Max +25% initial stop buffer after fast whipsaws
    MAX_COOLDOWN_MULT: float = 3.0          # Max 3x pair loss cooldown after repeated losses
    MAX_LESSONS_STORED: int = 200

    def __init__(self, state_path: str = "loss_lessons.json"):
        self.state_path = state_path
        self.lessons: List[TradeLesson] = []
        self.pair_loss_streaks: Dict[str, int] = {}
        self.pair_conviction_boost: Dict[str, float] = {}
        self.cause_counts: Dict[str, int] = {}
        self.stop_width_mult: float = 1.0
        self.orderbook_penalty_active: bool = False
        self._load()

    def _load(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.pair_loss_streaks = {k: int(v) for k, v in data.get("pair_loss_streaks", {}).items()}
            self.pair_conviction_boost = {k: float(v) for k, v in data.get("pair_conviction_boost", {}).items()}
            self.cause_counts = {k: int(v) for k, v in data.get("cause_counts", {}).items()}
            self.stop_width_mult = min(self.MAX_STOP_WIDTH_MULT, max(1.0, float(data.get("stop_width_mult", 1.0))))
            self.orderbook_penalty_active = bool(data.get("orderbook_penalty_active", False))
            raw_lessons = data.get("lessons", [])
            self.lessons = [TradeLesson(**item) for item in raw_lessons[-self.MAX_LESSONS_STORED:]]
        except Exception as e:
            logger.warning(f"Failed to load loss lessons from {self.state_path}: {e}")

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            payload = {
                "pair_loss_streaks": self.pair_loss_streaks,
                "pair_conviction_boost": self.pair_conviction_boost,
                "cause_counts": self.cause_counts,
                "stop_width_mult": round(self.stop_width_mult, 3),
                "orderbook_penalty_active": self.orderbook_penalty_active,
                "lessons": [asdict(l) for l in self.lessons[-self.MAX_LESSONS_STORED:]],
            }
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save loss lessons to {self.state_path}: {e}")

    def diagnose_loss(
        self,
        side: str,
        hold_duration_sec: float,
        entry_conviction: float,
        depth_ratio: float,
        macro_bias: str,
    ) -> str:
        """Classify the most likely root cause of a losing trade."""
        if hold_duration_sec < 180.0:
            return "FAST_WHIPSAW_STOP"
        if (side == "short" and macro_bias == "BULLISH") or (side == "long" and macro_bias == "BEARISH"):
            return "COUNTER_MACRO_BIAS"
        if (side == "short" and depth_ratio >= 1.8) or (side == "long" and depth_ratio <= 0.55):
            return "ORDERBOOK_IMBALANCE_TRAP"
        if entry_conviction > 0 and entry_conviction < 0.70:
            return "WEAK_CONVICTION_ENTRY"
        return "TREND_REVERSAL_EXHAUSTION"

    def record_trade_close(
        self,
        pair: str,
        side: str,
        entry_equity_jpy: float,
        exit_equity_jpy: float,
        hold_duration_sec: float,
        entry_conviction: float = 0.0,
        depth_ratio: float = 1.0,
        wick_classification: str = "NONE",
        macro_bias: str = "NEUTRAL",
        now_ts: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> TradeLesson:
        """Record a closed trade, diagnose any loss, and apply bounded self-fixes."""
        ts = now_ts if now_ts is not None else time.time()
        pnl_jpy = exit_equity_jpy - entry_equity_jpy
        pnl_pct = (pnl_jpy / entry_equity_jpy * 100.0) if entry_equity_jpy > 0 else 0.0
        is_loss = entry_equity_jpy > 0 and exit_equity_jpy < (entry_equity_jpy * 0.9995)
        ctx = {k: v for k, v in (context or {}).items() if k in TradeLesson.__dataclass_fields__}

        if not is_loss:
            # Winning / break-even trade: gradually relax temporary penalties
            self.pair_loss_streaks[pair] = 0
            if pair in self.pair_conviction_boost:
                self.pair_conviction_boost[pair] = max(0.0, round(self.pair_conviction_boost[pair] - 0.05, 3))
            if self.stop_width_mult > 1.0:
                self.stop_width_mult = max(1.0, round(self.stop_width_mult - 0.05, 3))
            lesson = TradeLesson(
                timestamp=ts,
                pair=pair,
                side=side,
                entry_equity_jpy=round(entry_equity_jpy, 2),
                exit_equity_jpy=round(exit_equity_jpy, 2),
                pnl_jpy=round(pnl_jpy, 2),
                pnl_pct=round(pnl_pct, 3),
                hold_duration_sec=round(hold_duration_sec, 1),
                is_loss=False,
                root_cause="WIN_OR_BREAKEVEN",
                fix_applied="Relaxed temporary pair penalties",
                entry_conviction=entry_conviction,
                depth_ratio=depth_ratio,
                wick_classification=wick_classification,
                macro_bias=macro_bias,
                **ctx,
            )
            self.lessons.append(lesson)
            self._save()
            return lesson

        # Diagnose loss & apply bounded auto-fix
        cause = self.diagnose_loss(
            side=side,
            hold_duration_sec=hold_duration_sec,
            entry_conviction=entry_conviction,
            depth_ratio=depth_ratio,
            macro_bias=macro_bias,
        )
        self.cause_counts[cause] = self.cause_counts.get(cause, 0) + 1
        streak = self.pair_loss_streaks.get(pair, 0) + 1
        self.pair_loss_streaks[pair] = streak

        fixes: List[str] = []
        # 1. Raise conviction bar for this pair so weak setups are filtered out
        new_boost = min(self.MAX_CONVICTION_BOOST, round(self.pair_conviction_boost.get(pair, 0.0) + 0.08, 3))
        self.pair_conviction_boost[pair] = new_boost
        fixes.append(f"{pair} min_conv+{new_boost:.2f}")

        # 2. Specific cause-targeted adaptations
        if cause == "FAST_WHIPSAW_STOP":
            self.stop_width_mult = min(self.MAX_STOP_WIDTH_MULT, round(self.stop_width_mult + 0.10, 3))
            fixes.append(f"stop_width_mult={self.stop_width_mult:.2f}x")
        elif cause == "ORDERBOOK_IMBALANCE_TRAP":
            self.orderbook_penalty_active = True
            fixes.append("orderbook_imbalance_filter=ON")

        if streak >= 2:
            fixes.append(f"cooldown_mult={self.get_pair_cooldown_multiplier(pair):.1f}x")

        fix_summary = ", ".join(fixes)
        lesson = TradeLesson(
            timestamp=ts,
            pair=pair,
            side=side,
            entry_equity_jpy=round(entry_equity_jpy, 2),
            exit_equity_jpy=round(exit_equity_jpy, 2),
            pnl_jpy=round(pnl_jpy, 2),
            pnl_pct=round(pnl_pct, 3),
            hold_duration_sec=round(hold_duration_sec, 1),
            is_loss=True,
            root_cause=cause,
            fix_applied=fix_summary,
            entry_conviction=entry_conviction,
            depth_ratio=depth_ratio,
            wick_classification=wick_classification,
            macro_bias=macro_bias,
            **ctx,
        )
        self.lessons.append(lesson)
        self._save()
        logger.warning(
            f"[AUTO-LEARN] Loss detected on {pair} ({pnl_jpy:+,.1f} JPY / {pnl_pct:+.2f}%, {hold_duration_sec:.0f}s) "
            f"| Cause={cause} | Fix={fix_summary}"
        )
        return lesson

    def get_effective_min_conviction(self, pair: str, base_min_conviction: float) -> float:
        """Return adapted minimum conviction for a pair (capped at 0.92)."""
        boost = self.pair_conviction_boost.get(pair, 0.0)
        return min(0.92, round(base_min_conviction + boost, 3))

    def get_pair_cooldown_multiplier(self, pair: str) -> float:
        """Scale post-loss cooldown up to 3.0x when a pair has consecutive losses."""
        streak = self.pair_loss_streaks.get(pair, 0)
        if streak <= 1:
            return 1.0
        return min(self.MAX_COOLDOWN_MULT, float(streak))

    def adjust_stop_price(self, entry_price: float, stop_price: float, side: str) -> float:
        """Apply learned stop-width multiplier while preserving direction and hard stop."""
        if self.stop_width_mult <= 1.0 or entry_price <= 0 or stop_price <= 0:
            return stop_price
        dist = abs(stop_price - entry_price)
        adj_dist = dist * self.stop_width_mult
        if side == "short":
            return entry_price + adj_dist
        return max(0.0, entry_price - adj_dist)

    def adjust_signal_conviction(self, sig_conviction: float, side: str, depth_ratio: float) -> float:
        """Penalize conviction if orderbook imbalance trap was previously learned and book opposes trade."""
        if not self.orderbook_penalty_active:
            return sig_conviction
        if (side == "short" and depth_ratio >= 1.8) or (side == "long" and depth_ratio <= 0.55):
            return max(0.0, round(sig_conviction - 0.10, 3))
        return sig_conviction

    def get_latest_lesson_summary(self) -> Optional[str]:
        if not self.lessons:
            return None
        last = self.lessons[-1]
        tag = "LOSS" if last.is_loss else "WIN"
        return f"[{tag}] {last.pair} {last.pnl_jpy:+,.0f} JPY ({last.root_cause}) -> {last.fix_applied}"
