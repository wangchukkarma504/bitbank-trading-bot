"""Adaptive setup learner: learns from every closed live trade which kinds of setup to keep taking.

Each trade belongs to a bucket (pair, side, 15m RSI band, 1h trend). The learner keeps a decayed running
result per bucket and blends it with a neutral prior, so a couple of trades cannot swing a decision:

- a bucket that keeps losing is traded at half size, then blocked;
- a blocked bucket gets one half-size probe trade after RETEST_AFTER_SEC, so it can earn its way back;
- a bucket that does well is left at full size (the learner never raises size above the configured one).

It cannot make any single trade better; it shifts the mix of trades towards what has been working.
"""

from dataclasses import asdict, dataclass
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AdaptiveLearner")


@dataclass
class BucketStats:
    n: float = 0.0            # decayed trade count
    total_pct: float = 0.0    # decayed sum of results, % of equity
    trades: int = 0           # lifetime trade count (not decayed)
    wins: int = 0
    last_ts: float = 0.0
    blocked_since: float = 0.0


class AdaptiveLearner:
    PRIOR_TRADES: float = 8.0          # weight of the neutral prior, in trades
    PRIOR_MEAN_PCT: float = 0.0
    DECAY: float = 0.97                # per-trade decay: older results fade (half-life ~23 trades)
    MIN_TRADES_TO_ACT: int = 6
    REDUCE_BELOW_PCT: float = -0.20    # blended mean result (% of equity per trade) -> half size
    BLOCK_BELOW_PCT: float = -0.50     # ... -> blocked
    REDUCED_SIZE: float = 0.5
    RETEST_AFTER_SEC: float = 24 * 3600.0

    def __init__(self, state_path: Optional[str] = None):
        self.state_path = state_path
        self.buckets: Dict[str, BucketStats] = {}
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                raw = json.load(f).get("buckets", {})
            self.buckets = {k: BucketStats(**v) for k, v in raw.items()}
        except Exception as e:
            logger.warning(f"Could not load learner state from {self.state_path}: {e}")

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"buckets": {k: asdict(v) for k, v in self.buckets.items()}}, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save learner state to {self.state_path}: {e}")

    # ------------------------------------------------------------------ model
    @staticmethod
    def bucket_key(pair: str, side: str, rsi: float, trend_1h: str) -> str:
        if rsi <= 0:
            band = "rsi?"
        elif rsi >= 70:
            band = "rsi70+"
        elif rsi >= 60:
            band = "rsi60-70"
        elif rsi > 40:
            band = "rsi40-60"
        elif rsi > 30:
            band = "rsi30-40"
        else:
            band = "rsi<30"
        return f"{pair}|{side}|{band}|1h:{(trend_1h or '?').upper()}"

    def blended_mean_pct(self, key: str) -> float:
        b = self.buckets.get(key)
        if b is None:
            return self.PRIOR_MEAN_PCT
        return (b.total_pct + self.PRIOR_MEAN_PCT * self.PRIOR_TRADES) / (b.n + self.PRIOR_TRADES)

    def decision(self, key: str, now_ts: Optional[float] = None) -> Tuple[bool, float, str]:
        """Return (allowed, size_multiplier, reason) for taking a trade in this bucket now."""
        now = now_ts if now_ts is not None else time.time()
        b = self.buckets.get(key)
        if b is None or b.trades < self.MIN_TRADES_TO_ACT:
            return True, 1.0, "learning (too few trades to judge)"
        mean = self.blended_mean_pct(key)
        if mean <= self.BLOCK_BELOW_PCT:
            if b.blocked_since <= 0:
                b.blocked_since = now
                self._save()
            if now - max(b.blocked_since, b.last_ts) >= self.RETEST_AFTER_SEC:
                return True, self.REDUCED_SIZE, f"probe trade: blocked bucket retest (avg {mean:+.2f}%/trade)"
            return False, 0.0, f"blocked by learner (avg {mean:+.2f}%/trade over {b.trades} trades)"
        if b.blocked_since > 0:
            b.blocked_since = 0.0
            self._save()
        if mean <= self.REDUCE_BELOW_PCT:
            return True, self.REDUCED_SIZE, f"half size (avg {mean:+.2f}%/trade over {b.trades} trades)"
        return True, 1.0, f"full size (avg {mean:+.2f}%/trade over {b.trades} trades)"

    def record(self, key: str, pnl_pct_of_equity: float, now_ts: Optional[float] = None) -> None:
        """Feed one closed trade's result (% of equity, net of fees) into its bucket."""
        b = self.buckets.setdefault(key, BucketStats())
        b.n = b.n * self.DECAY + 1.0
        b.total_pct = b.total_pct * self.DECAY + float(pnl_pct_of_equity)
        b.trades += 1
        b.wins += 1 if pnl_pct_of_equity > 0 else 0
        b.last_ts = now_ts if now_ts is not None else time.time()
        self._save()

    def summary(self) -> List[Dict[str, Any]]:
        out = []
        for key, b in sorted(self.buckets.items(), key=lambda kv: -kv[1].trades):
            allowed, mult, reason = self.decision(key)
            out.append({
                "bucket": key, "trades": b.trades, "wins": b.wins,
                "avg_pct": round(self.blended_mean_pct(key), 3),
                "status": "blocked" if not allowed else ("half" if mult < 1.0 else "full"),
                "reason": reason,
            })
        return out
