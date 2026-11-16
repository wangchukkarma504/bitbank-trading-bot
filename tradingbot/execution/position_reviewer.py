"""Position Reviewer (Role 1).

Monitors baseline budget (¥10,001.00 JPY), live equity (~¥10,142.30 JPY), cash collateral,
2.0x buying power, open margin positions across the 5 supported pairs (sol_jpy, doge_jpy,
eth_jpy, btc_jpy, xrp_jpy), resting active exchange-side stop orders, and detects any
unprotected / naked positions.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Tuple

from tradingbot.models import MARGIN_PAIRS, SUPPORTED_PAIRS


@dataclass
class PositionReviewResult:
    """Consolidated state emitted by Position Reviewer (Role 1)."""
    baseline_budget_jpy: float
    total_equity_jpy: float
    free_cash_jpy: float
    locked_cash_jpy: float
    buying_power_jpy: float
    pnl_jpy: float
    pnl_pct: float
    open_positions: List[Dict[str, Any]] = field(default_factory=list)
    active_stops: List[Dict[str, Any]] = field(default_factory=list)
    active_orders: List[Dict[str, Any]] = field(default_factory=list)
    naked_positions: List[Dict[str, Any]] = field(default_factory=list)
    is_fully_protected: bool = True
    open_risk_jpy: float = 0.0
    has_query_error: bool = False
    timestamp: int = 0


class PositionReviewer:
    """Role 1: Position Reviewer.

    Audits live account equity, buying power, open margin positions,
    active exchange-side stop orders, and naked risk across all supported pairs.
    """

    BASELINE_BUDGET: float = 10001.0

    def __init__(self, bitbank_client=None, baseline_budget_jpy: float = 10001.0):
        self.client = bitbank_client
        self.baseline_budget_jpy = baseline_budget_jpy

    def review(self, client=None, allow_shorts: bool = True) -> PositionReviewResult:
        """Perform full position review and account equity audit."""
        active_client = client or self.client
        if active_client is None:
            raise ValueError("Bitbank client is required for position review")

        now_ms = int(time.time() * 1000)

        # 1. Query Cash Balances
        assets_res = active_client._get("/user/assets")
        assets_list = assets_res.get("assets", []) if isinstance(assets_res, dict) else []

        jpy_free = 0.0
        jpy_locked = 0.0
        crypto_holdings: Dict[str, Dict[str, float]] = {}

        for a in assets_list:
            asset = a.get("asset")
            free_amt = float(a.get("free_amount", 0.0))
            locked_amt = float(a.get("locked_amount", 0.0))
            if asset == "jpy":
                jpy_free = free_amt
                jpy_locked = locked_amt
            elif (free_amt + locked_amt) > 0.0001:
                crypto_holdings[asset] = {
                    "free": free_amt,
                    "locked": locked_amt,
                    "total": free_amt + locked_amt,
                }

        # 2. Query Open Margin Positions across the 5 Pairs (skipped in Spot Long-Only mode)
        positions_raw = active_client.margin_positions() if allow_shorts else []
        open_positions: List[Dict[str, Any]] = []
        margin_unrealized_pnl = 0.0

        for p in positions_raw:
            amt = float(p.get("open_amount", 0.0))
            if amt <= 0.0001:
                continue

            pair = p.get("pair")
            if pair not in SUPPORTED_PAIRS:
                continue

            side = p.get("position_side", "short")
            avg_px = float(p.get("average_price", 0.0))

            # Fetch ticker for valuation
            try:
                tk = active_client.ticker(pair)
                last_px = float(tk.get("last", 0.0))
            except Exception:
                last_px = avg_px

            pnl = amt * (avg_px - last_px) if side == "short" else amt * (last_px - avg_px)
            margin_unrealized_pnl += pnl

            pos_data = {
                "pair": pair,
                "position_side": side,
                "open_amount": f"{amt:.4f}",
                "amount": amt,
                "average_price": f"{avg_px:.4f}",
                "avg_price": avg_px,
                "last_price": last_px,
                "unrealized_pnl_jpy": pnl,
                "notional_jpy": amt * last_px,
            }
            open_positions.append(pos_data)

        # 3. Valuate Crypto Holdings (for spot)
        crypto_val_jpy = 0.0
        for coin, h in crypto_holdings.items():
            pair = f"{coin}_jpy"
            try:
                tk = active_client.ticker(pair)
                last_px = float(tk.get("last", 0.0))
                crypto_val_jpy += h["total"] * last_px
            except Exception:
                pass

        # 4. Compute Equity and Buying Power
        if hasattr(active_client, "calculate_total_equity") and callable(active_client.calculate_total_equity):
            total_equity = float(active_client.calculate_total_equity())
        else:
            total_equity = (jpy_free + jpy_locked) + crypto_val_jpy + margin_unrealized_pnl

        buying_power = total_equity * 2.0
        pnl_jpy = total_equity - self.baseline_budget_jpy
        pnl_pct = (pnl_jpy / self.baseline_budget_jpy) * 100.0 if self.baseline_budget_jpy > 0 else 0.0

        # 5. Query Resting Active Stop Orders across 5 Pairs
        active_stops: List[Dict[str, Any]] = []
        all_active_orders: List[Dict[str, Any]] = []
        active_orders_by_pair: Dict[str, List[Dict[str, Any]]] = {}
        has_query_error = False

        for pair in SUPPORTED_PAIRS:
            orders = None
            for attempt in range(2):
                try:
                    orders_res = active_client._get("/user/spot/active_orders", {"pair": pair})
                    orders = orders_res.get("orders", []) if isinstance(orders_res, dict) else []
                    break
                except Exception:
                    time.sleep(0.2)
            if orders is None:
                has_query_error = True
                active_orders_by_pair[pair] = []
            else:
                active_orders_by_pair[pair] = orders
                for o in orders:
                    all_active_orders.append(o)
                    if o.get("type") == "stop" and o.get("status") in ("UNFILLED", "INACTIVE"):
                        active_stops.append(o)

        # 6. Audit Naked Positions & Open Risk
        naked_positions, open_risk = self._audit_naked_positions(open_positions, active_stops)
        is_fully_protected = (len(naked_positions) == 0)

        return PositionReviewResult(
            baseline_budget_jpy=self.baseline_budget_jpy,
            total_equity_jpy=round(total_equity, 2),
            free_cash_jpy=round(jpy_free, 2),
            locked_cash_jpy=round(jpy_locked, 2),
            buying_power_jpy=round(buying_power, 2),
            pnl_jpy=round(pnl_jpy, 2),
            pnl_pct=round(pnl_pct, 4),
            open_positions=open_positions,
            active_stops=active_stops,
            active_orders=all_active_orders,
            naked_positions=naked_positions,
            is_fully_protected=is_fully_protected,
            open_risk_jpy=round(open_risk, 2),
            has_query_error=has_query_error,
            timestamp=now_ms,
        )

    def _audit_naked_positions(
        self,
        open_positions: List[Dict[str, Any]],
        active_stops: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Detect any open positions that lack matching exchange-side stop orders."""
        naked_positions: List[Dict[str, Any]] = []
        total_open_risk: float = 0.0

        for pos in open_positions:
            pair = pos["pair"]
            side = pos["position_side"]
            amt = float(pos["amount"])
            avg_px = float(pos["avg_price"])
            last_px = float(pos["last_price"])

            req_side = "buy" if side == "short" else "sell"

            # Filter active stops covering this exact position
            matching_stops = [
                s for s in active_stops
                if s.get("pair") == pair
                and s.get("position_side") == side
                and s.get("side") == req_side
                and s.get("status") in ("UNFILLED", "INACTIVE")
            ]

            covered_amount = sum(
                float(s.get("remaining_amount", s.get("start_amount", s.get("amount", 0.0))))
                for s in matching_stops
            )

            if covered_amount < amt * 0.999:
                # Flag as naked / unprotected position
                unprotected_amt = amt - covered_amount
                pos_copy = dict(pos)
                pos_copy["unprotected_amount"] = unprotected_amt
                pos_copy["covered_amount"] = covered_amount
                naked_positions.append(pos_copy)

                # Naked risk: entire unprotected notional
                total_open_risk += unprotected_amt * last_px
            else:
                # Protected position: calculate risk from average price to stop trigger
                if matching_stops:
                    primary_stop = matching_stops[0]
                    trigger_px = float(primary_stop.get("trigger_price", last_px))
                    if side == "short":
                        risk_per_unit = max(0.0, trigger_px - avg_px)
                    else:
                        risk_per_unit = max(0.0, avg_px - trigger_px)
                    total_open_risk += amt * risk_per_unit

        return naked_positions, total_open_risk
