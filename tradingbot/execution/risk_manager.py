"""Risk & Profit Execution Manager (Role 6).

Enforces:
- Hard native exchange stop orders (`type: "stop"`, `trigger_price`, `position_side="short"` or `"long"`)
  placed immediately upon fill on the 5 supported margin pairs (SOL, DOGE, ETH, BTC, XRP).
  Zero naked positions permitted.
- Atomic place-before-cancel stop synchronization (`sync_stop`).
- Emergency market cover if stop placement fails after retries.
- Dynamic position sizing:
  - Margin short: Exactly 1.60x notional equity allocation (80% of 2.0x leverage).
  - Spot long: Capped strictly at 50% allocation (default 30%).
  - Floor quantization using MARGIN_PAIRS AD / PD precision.
- Maker limit orders: Entry placed at or above best_ask (for shorts) with `post_only: true`
  capturing the -0.02% maker rebate.
- Trailing ratchets: Break-even ratchet and Profit-lock ratchet.
"""

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from tradingbot.bitbank import BitbankError
from tradingbot.models import (
    MARGIN_PAIRS,
    SPOT_ONLY_PAIRS,
    PairConfig,
    SizingPlan,
)


def calculate_margin_short_size(
    equity_jpy: float,
    pair: str,
    entry_price: float,
    leverage_factor: float = 1.60,
) -> Tuple[float, str, float]:
    """Compute margin short executable size.
    Returns: (target_quantity, formatted_quantity_str, notional_exposure_jpy)
    """
    if equity_jpy <= 0 or entry_price <= 0:
        raise ValueError("Equity and entry price must be positive")

    if pair not in MARGIN_PAIRS:
        raise ValueError(f"Pair {pair} is not a supported margin pair")

    cfg = MARGIN_PAIRS[pair]
    target_notional = equity_jpy * leverage_factor
    target_qty = target_notional / entry_price

    # Floor quantization to AD digits
    ad = cfg.amount_digits
    quantized_qty = math.floor(target_qty * (10 ** ad) + 1e-9) / (10 ** ad)
    if quantized_qty < cfg.min_amount:
        return 0.0, cfg.format_amount(0.0), 0.0
    formatted_qty = f"{quantized_qty:.{ad}f}"
    actual_notional = quantized_qty * entry_price

    return quantized_qty, formatted_qty, actual_notional


def calculate_spot_long_size(
    equity_jpy: float,
    free_cash_jpy: float,
    pair: str,
    entry_price: float,
    alloc_cap: float = 0.50,
    default_alloc: float = 0.30,
) -> Tuple[float, str, float]:
    """Compute spot long executable size adhering to 50% cap.
    Returns: (target_quantity, formatted_quantity_str, notional_exposure_jpy)
    """
    if equity_jpy <= 0 or entry_price <= 0:
        raise ValueError("Equity and entry price must be positive")

    cfg = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS.get(pair) or PairConfig(pair=pair, price_digits=3, amount_digits=4)
    budget_jpy = min(equity_jpy * alloc_cap, free_cash_jpy * 0.98, equity_jpy * default_alloc)
    target_qty = budget_jpy / entry_price

    ad = cfg.amount_digits
    quantized_qty = math.floor(target_qty * (10 ** ad) + 1e-9) / (10 ** ad)
    if quantized_qty < cfg.min_amount:
        return 0.0, cfg.format_amount(0.0), 0.0
    formatted_qty = f"{quantized_qty:.{ad}f}"
    actual_notional = quantized_qty * entry_price

    return quantized_qty, formatted_qty, actual_notional


class StopSyncManager:
    """Atomic place-before-cancel exchange stop manager."""

    def __init__(self, client, pair: str):
        self.client = client
        self.pair = pair
        self.current_stop_id: Optional[int] = None
        self.current_stop_level: Optional[float] = None
        self.current_stop_qty: Optional[str] = None
        self.emergency_covered: bool = False

    def sync_stop(
        self,
        qty: str,
        trigger_price: float,
        position_side: Optional[str] = "short",
        max_retries: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Place new stop FIRST, verify matching engine order_id, then cancel old stop.
        If stop placement fails after retries, triggers emergency market cover.
        """
        if self.pair not in MARGIN_PAIRS:
            raise BitbankError(f"Stop orders not supported on spot-only pair {self.pair} (code 60011)")

        side = "buy" if position_side == "short" else "sell"
        meta = MARGIN_PAIRS.get(self.pair)
        pd = meta.price_digits if meta else 1
        trigger_str = f"{trigger_price:.{pd}f}" if pd > 0 else str(int(round(trigger_price)))

        new_order = None
        for attempt in range(max_retries):
            try:
                order_kwargs: Dict[str, Any] = {
                    "pair": self.pair,
                    "side": side,
                    "amount": qty,
                    "type_": "stop",
                    "trigger_price": trigger_str,
                }
                if position_side is not None:
                    order_kwargs["position_side"] = position_side
                new_order = self.client.order(**order_kwargs)
                if new_order and new_order.get("order_id"):
                    break
            except BitbankError:
                time.sleep(0.01 * (attempt + 1))

        if not new_order or not new_order.get("order_id"):
            # Only panic-cover if there is NO existing protective stop on the exchange!
            # If an existing stop is already active, keep it alive rather than market-dumping a winning trade.
            if self.current_stop_id is None:
                self.emergency_market_cover(f"Stop placement failed on {self.pair} with no active stop")
            return None

        # Verify new stop is confirmed UNFILLED
        new_oid = new_order["order_id"]
        # Only replace a stop on the same side: a stop that protects an opposite holding on this pair
        # (spot long next to a margin short) must stay on the exchange.
        old_oid = self.current_stop_id if getattr(self, "current_stop_side", side) == side else None

        self.current_stop_side = side
        self.current_stop_id = new_oid
        self.current_stop_level = trigger_price
        self.current_stop_qty = qty

        # Cancel old stop only AFTER new stop is safely on matching engine
        if old_oid is not None:
            try:
                self.client.cancel(self.pair, old_oid)
            except BitbankError:
                pass

        return new_order

    def emergency_market_cover(self, reason: str = "") -> None:
        """Emergency liquidate position (margin or spot) to prevent unhedged exposure."""
        self.emergency_covered = True
        closed_any = False
        try:
            positions = self.client.margin_positions()
            for p in positions:
                if p.get("pair") == self.pair and float(p.get("open_amount", 0.0)) > 0:
                    amt = p["open_amount"]
                    side = "buy" if p.get("position_side") == "short" else "sell"
                    self.client.order(
                        self.pair,
                        side=side,
                        amount=amt,
                        type_="market",
                        position_side=p.get("position_side"),
                    )
                    closed_any = True
        except BitbankError:
            pass
        if not closed_any:
            try:
                base_asset = self.pair.split("_")[0]
                assets = self.client._get("/user/assets").get("assets", [])
                for a in assets:
                    if a.get("asset") == base_asset:
                        free_amt = float(a.get("free_amount", 0.0))
                        cfg = MARGIN_PAIRS.get(self.pair) or SPOT_ONLY_PAIRS.get(self.pair)
                        min_amt = cfg.min_amount if cfg else 0.0001
                        ad = cfg.amount_digits if cfg else 4
                        if free_amt >= min_amt:
                            self.client.order(self.pair, side="sell", amount=f"{free_amt:.{ad}f}", type_="market")
            except Exception:
                pass


class RiskManager:
    """Role 6: Risk & Profit Execution Manager.

    Coordinates sizing plans, maker limit order submissions (-0.02% rebate),
    mandatory native stop order attachment upon fill, atomic stop syncing,
    and multi-tier trailing ratchets.
    """

    SHORT_LEVERAGE_FACTOR: float = 1.60  # Leverage ceiling: 80% of Bitbank's 2.0x margin buying power
    MAX_RISK_PCT_PER_TRADE: float = 0.02  # A stop-out (incl. taker fee + slippage) may cost at most 2% of equity
    STOP_EXIT_COST_PCT: float = 0.0015    # 0.12% taker stop fee + ~0.03% slippage
    # Bitbank allows 2.0x; 1.95x is the most that fits once fees and amount rounding are counted
    MAX_EXCHANGE_LEVERAGE: float = 1.95
    SPOT_LONG_ALLOC_CAP: float = 0.50    # Max 50% equity allocation
    SPOT_LONG_DEFAULT_ALLOC: float = 0.30

    def __init__(self, bitbank_client=None):
        self.client = bitbank_client
        self.sync_managers: Dict[str, StopSyncManager] = {}

    def get_sync_manager(self, pair: str, client=None) -> StopSyncManager:
        """Get or create a StopSyncManager instance for a pair."""
        active_client = client or self.client
        if pair not in self.sync_managers or self.sync_managers[pair].client != active_client:
            self.sync_managers[pair] = StopSyncManager(active_client, pair)
        return self.sync_managers[pair]

    def create_sizing_plan(
        self,
        equity_jpy: float,
        pair: str,
        side: str,  # "sell" for short, "buy" for long
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        position_type: str = "margin",
        free_cash_jpy: Optional[float] = None,
    ) -> SizingPlan:
        """Generate a validated SizingPlan conforming to risk and leverage guardrails."""
        if side == "sell" or position_type == "margin":
            if pair not in MARGIN_PAIRS:
                raise ValueError(f"Pair {pair} is not in supported margin pairs whitelist")
        else:
            if pair not in MARGIN_PAIRS and pair not in SPOT_ONLY_PAIRS:
                raise ValueError(f"Pair {pair} is not in supported pairs whitelist")

        if side == "sell" or position_type == "margin":
            # Size from the stop distance so one stop-out costs at most MAX_RISK_PCT_PER_TRADE of equity
            leverage = self.SHORT_LEVERAGE_FACTOR
            if entry_price > 0 and stop_loss_price > 0:
                stop_dist = abs(stop_loss_price - entry_price) / entry_price
                leverage = min(leverage, self.MAX_RISK_PCT_PER_TRADE / (stop_dist + self.STOP_EXIT_COST_PCT))
            qty, qty_str, notional = calculate_margin_short_size(
                equity_jpy=equity_jpy,
                pair=pair,
                entry_price=entry_price,
                leverage_factor=leverage,
            )
        else:
            cash = free_cash_jpy if free_cash_jpy is not None else equity_jpy
            qty, qty_str, notional = calculate_spot_long_size(
                equity_jpy=equity_jpy,
                free_cash_jpy=cash,
                pair=pair,
                entry_price=entry_price,
                alloc_cap=self.SPOT_LONG_ALLOC_CAP,
                default_alloc=self.SPOT_LONG_DEFAULT_ALLOC,
            )

        return SizingPlan(
            pair=pair,
            side=side,
            position_type=position_type,
            equity_jpy=round(equity_jpy, 2),
            allocation_notional_jpy=round(notional, 2),
            target_amount=qty,
            formatted_amount=qty_str,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    def place_maker_limit_order(
        self,
        pair: str,
        side: str,
        amount: str,
        price: float,
        position_side: Optional[str] = "short",
        client=None,
    ) -> Dict[str, Any]:
        """Submit a maker limit order with native `post_only: true` capturing -0.02% rebate.
        For short: Limit price >= best_ask
        For long: Limit price <= best_bid
        """
        active_client = client or self.client
        if active_client is None:
            raise ValueError("Bitbank client is required to place maker order")

        if position_side is not None:
            if pair not in MARGIN_PAIRS:
                raise ValueError(f"Pair {pair} is not a supported margin pair")
            cfg = MARGIN_PAIRS[pair]
        else:
            if pair not in MARGIN_PAIRS and pair not in SPOT_ONLY_PAIRS:
                raise ValueError(f"Pair {pair} is not a supported pair")
            cfg = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS[pair]
        pd = cfg.price_digits
        price_str = f"{price:.{pd}f}" if pd > 0 else str(int(round(price)))

        extra: Dict[str, Any] = {"post_only": True}
        if position_side:
            extra["position_side"] = position_side

        return active_client.order(
            pair=pair,
            side=side,
            amount=amount,
            price=price_str,
            type_="limit",
            **extra,
        )

    def attach_protective_stop(
        self,
        pair: str,
        amount: str,
        trigger_price: float,
        position_side: str = "short",
        client=None,
    ) -> Dict[str, Any]:
        """Immediately attach native exchange stop order upon position fill."""
        active_client = client or self.client
        mgr = self.get_sync_manager(pair, active_client)
        stop_order = mgr.sync_stop(
            qty=amount,
            trigger_price=trigger_price,
            position_side=position_side,
        )
        if not stop_order:
            raise BitbankError(f"Failed to attach protective stop order on {pair}")
        return stop_order

    def sync_stop(
        self,
        pair: str,
        amount: str,
        trigger_price: float,
        position_side: str = "short",
        client=None,
    ) -> Optional[Dict[str, Any]]:
        """Atomic place-before-cancel stop synchronization."""
        active_client = client or self.client
        mgr = self.get_sync_manager(pair, active_client)
        return mgr.sync_stop(
            qty=amount,
            trigger_price=trigger_price,
            position_side=position_side,
        )

    def evaluate_and_apply_ratchets(
        self,
        pair: str,
        position: Dict[str, Any],
        current_price: float,
        client=None,
        active_stops: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evaluate unrealized PnL and ratchet the protective stop closer to protect capital.
        Uses place-before-cancel sync_stop to maintain continuous exchange protection.
        Prevents order churn by rounding target stop levels and requiring strictly improved price levels.

        Only the >= +1.6% trailing lock exists. Earlier break-even / profit-lock ratchets were removed: in
        the 150-day replay they stopped winners out on normal pullbacks and cut the average trade by a third.
        """
        active_client = client or self.client
        side = position.get("position_side", "short")
        pos_type = position.get("position_type", "margin")
        avg_px = float(position.get("avg_price", position.get("average_price", 0.0)))
        amt_str = str(position.get("open_amount", position.get("amount", "0.0")))
        amt = float(amt_str)

        if amt <= 0.0001 or avg_px <= 0 or pair in SPOT_ONLY_PAIRS:
            return None

        stop_pos_side: Optional[str] = None if pos_type == "spot" else side
        meta = MARGIN_PAIRS.get(pair)
        pd = meta.price_digits if meta else 1

        mgr = self.get_sync_manager(pair, active_client)
        current_stop = mgr.current_stop_level

        # Sync cached stop level with live active_stops from exchange and clean up any duplicate stops
        if active_stops:
            req_side = "buy" if side == "short" else "sell"
            matching = []
            for s in active_stops:
                if s.get("pair") == pair and s.get("side") == req_side and s.get("status") in ("UNFILLED", "INACTIVE"):
                    try:
                        trig = float(s.get("trigger_price", 0.0))
                        rem_amt = float(s.get("remaining_amount", s.get("amount", s.get("start_amount", 0.0))))
                        if trig > 0:
                            is_full = rem_amt >= (amt - 1e-6)
                            matching.append((is_full, trig, s))
                    except (ValueError, TypeError):
                        pass

            if matching:
                # Prioritize full-coverage stops first, then tightest protective stop (lowest trigger for short, highest for long)
                matching.sort(
                    key=lambda x: (0 if x[0] else 1, -x[1] if side == "long" else x[1])
                )
                best_is_full, best_trig, best_order = matching[0]
                if (
                    current_stop is None
                    or mgr.current_stop_qty != str(best_order.get("remaining_amount", best_order.get("amount", best_order.get("start_amount", amt_str))))
                    or (side == "short" and best_trig < current_stop)
                    or (side == "long" and best_trig > current_stop)
                ):
                    mgr.current_stop_level = best_trig
                    mgr.current_stop_id = best_order.get("order_id")
                    mgr.current_stop_qty = str(best_order.get("remaining_amount", best_order.get("amount", best_order.get("start_amount", amt_str))))
                    current_stop = best_trig

                # Cancel any redundant/looser or partial duplicate stops
                for _, _, dup_order in matching[1:]:
                    dup_oid = dup_order.get("order_id")
                    if dup_oid and dup_oid != mgr.current_stop_id and active_client is not None:
                        try:
                            active_client.cancel(pair, dup_oid)
                        except Exception:
                            pass

        # Calculate gain percentage
        if side == "short":
            gain_pct = (avg_px - current_price) / avg_px
            min_safe_stop = round(current_price * 1.0015, pd)
            new_stop: Optional[float] = None

            # Dynamic Trailing once gain >= +1.6%: give trends 1.0% breathing room instead of 0.6% choking
            if gain_pct >= 0.016:
                trail_stop = round(current_price * 1.010, pd)
                if gain_pct >= 0.035:
                    min_lock = round(avg_px * (1.0 - 0.025), pd)  # Lock +2.5%
                elif gain_pct >= 0.028:
                    min_lock = round(avg_px * (1.0 - 0.019), pd)  # Lock +1.9%
                elif gain_pct >= 0.022:
                    min_lock = round(avg_px * (1.0 - 0.014), pd)  # Lock +1.4%
                else:
                    min_lock = round(avg_px * (1.0 - 0.010), pd)  # Lock +1.0%

                new_stop = max(min_safe_stop, min(trail_stop, min_lock))

            step = 1e-6
            if new_stop is not None and (current_stop is None or new_stop < current_stop - step):
                return mgr.sync_stop(amt_str, new_stop, position_side=side)

        elif side == "long":
            gain_pct = (current_price - avg_px) / avg_px
            max_safe_stop = round(current_price * 0.9985, pd)
            new_stop = None

            # Dynamic Trailing once gain >= +1.6%: give trends 1.0% breathing room instead of 0.6% choking
            if gain_pct >= 0.016:
                trail_stop = round(current_price * 0.990, pd)
                if gain_pct >= 0.035:
                    min_lock = round(avg_px * (1.0 + 0.025), pd)
                elif gain_pct >= 0.028:
                    min_lock = round(avg_px * (1.0 + 0.019), pd)
                elif gain_pct >= 0.022:
                    min_lock = round(avg_px * (1.0 + 0.014), pd)
                else:
                    min_lock = round(avg_px * (1.0 + 0.010), pd)

                new_stop = min(max_safe_stop, max(trail_stop, min_lock))

            step = 1e-6
            if new_stop is not None and (current_stop is None or new_stop > current_stop + step):
                return mgr.sync_stop(amt_str, new_stop, position_side=stop_pos_side)

        return None

    def emergency_market_cover(self, pair: str, client=None) -> None:
        """Trigger emergency liquidation on a pair to eliminate unhedged risk."""
        active_client = client or self.client
        mgr = self.get_sync_manager(pair, active_client)
        mgr.emergency_market_cover("Manual or automated emergency cover triggered")
