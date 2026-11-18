"""Deterministic High-Fidelity Bitbank Matching Engine Mock.

Simulates:
- Public endpoints: /ticker, /depth, /candlestick
- Private endpoints: /user/assets, /user/margin/positions, /user/margin/status,
  /user/spot/order, /user/spot/cancel_order, /user/spot/active_orders
- Live order book & matching state machine (market, limit, native exchange stop orders)
- Fee modeling: Maker rebate (-0.02%) vs Taker fee (+0.12% / +0.10%)
- Pair constraints: Stop orders strictly accepted on the 5 margin pairs
  (sol_jpy, doge_jpy, eth_jpy, btc_jpy, xrp_jpy) and rejected on spot-only pairs (e.g. arb_jpy)
- Fault injection: Maintenance (10007), Nonce collision (20001), price gaps
"""

import copy
import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from tradingbot.bitbank import BitbankError


MARGIN_PAIRS_META: Dict[str, Dict[str, Any]] = {
    "btc_jpy": {
        "name": "btc_jpy",
        "price_digits": 0,
        "amount_digits": 4,
        "min_amount": "0.0001",
        "maker_fee_rate_quote": "0.0000",
        "taker_fee_rate_quote": "0.0010",
        "margin_collateral_ratio": "0.50",
        "stop_order": True,
        "is_margin": True,
    },
    "eth_jpy": {
        "name": "eth_jpy",
        "price_digits": 0,
        "amount_digits": 4,
        "min_amount": "0.0001",
        "maker_fee_rate_quote": "-0.0002",
        "taker_fee_rate_quote": "0.0012",
        "margin_collateral_ratio": "0.50",
        "stop_order": True,
        "is_margin": True,
    },
    "sol_jpy": {
        "name": "sol_jpy",
        "price_digits": 1,
        "amount_digits": 4,
        "min_amount": "0.0001",
        "maker_fee_rate_quote": "-0.0002",
        "taker_fee_rate_quote": "0.0012",
        "margin_collateral_ratio": "0.50",
        "stop_order": True,
        "is_margin": True,
    },
    "doge_jpy": {
        "name": "doge_jpy",
        "price_digits": 3,
        "amount_digits": 4,
        "min_amount": "0.0001",
        "maker_fee_rate_quote": "-0.0002",
        "taker_fee_rate_quote": "0.0012",
        "margin_collateral_ratio": "0.50",
        "stop_order": True,
        "is_margin": True,
    },
    "xrp_jpy": {
        "name": "xrp_jpy",
        "price_digits": 3,
        "amount_digits": 4,
        "min_amount": "0.0001",
        "maker_fee_rate_quote": "-0.0002",
        "taker_fee_rate_quote": "0.0012",
        "margin_collateral_ratio": "0.50",
        "stop_order": True,
        "is_margin": True,
    },
    # Non-margin spot altcoin for boundary testing
    "arb_jpy": {
        "name": "arb_jpy",
        "price_digits": 3,
        "amount_digits": 4,
        "min_amount": "0.0001",
        "maker_fee_rate_quote": "-0.0002",
        "taker_fee_rate_quote": "0.0012",
        "margin_collateral_ratio": "1.00",
        "stop_order": False,
        "is_margin": False,
    },
}


class MockBitbankClient:
    """High-fidelity deterministic Bitbank API client and matching engine mock."""

    def __init__(
        self,
        starting_cash_jpy: float = 10001.0,
        baseline_budget_jpy: float = 10001.0,
    ):
        self.starting_cash_jpy = starting_cash_jpy
        self.baseline_budget_jpy = baseline_budget_jpy

        self.key = "MOCK_KEY"
        self.secret = "MOCK_SECRET"

        # Fault injection controls
        self.maintenance_mode: bool = False
        self.nonce_collisions_remaining: int = 0
        self.simulated_network_error: Optional[Exception] = None

        # Order state
        self.order_counter: int = 70000000000
        self.orders: Dict[int, Dict[str, Any]] = {}

        # Balances
        self.jpy_free: float = starting_cash_jpy
        self.jpy_locked: float = 0.0
        self.crypto_assets: Dict[str, Dict[str, float]] = {
            "sol": {"free": 0.0, "locked": 0.0},
            "doge": {"free": 0.0, "locked": 0.0},
            "eth": {"free": 0.0, "locked": 0.0},
            "btc": {"free": 0.0, "locked": 0.0},
            "xrp": {"free": 0.0, "locked": 0.0},
            "arb": {"free": 0.0, "locked": 0.0},
        }

        # Margin positions: list of dicts
        self.margin_positions_list: List[Dict[str, Any]] = [
            {"pair": p, "position_side": "short", "open_amount": "0.0000", "average_price": "0.0"}
            for p in ("btc_jpy", "eth_jpy", "sol_jpy", "doge_jpy", "xrp_jpy")
        ] + [
            {"pair": p, "position_side": "long", "open_amount": "0.0000", "average_price": "0.0"}
            for p in ("btc_jpy", "eth_jpy", "sol_jpy", "doge_jpy", "xrp_jpy")
        ]

        # Ticker state
        self.tickers: Dict[str, Dict[str, Any]] = {
            "btc_jpy": {"last": "11800000", "buy": "11799000", "sell": "11801000", "high": "11900000", "low": "11700000", "vol": "150.25", "timestamp": int(time.time() * 1000)},
            "eth_jpy": {"last": "335000", "buy": "334900", "sell": "335100", "high": "340000", "low": "330000", "vol": "850.50", "timestamp": int(time.time() * 1000)},
            "sol_jpy": {"last": "13750.0", "buy": "13745.0", "sell": "13755.0", "high": "14200.0", "low": "13500.0", "vol": "4200.0", "timestamp": int(time.time() * 1000)},
            "doge_jpy": {"last": "15.500", "buy": "15.495", "sell": "15.505", "high": "16.200", "low": "15.100", "vol": "580000.0", "timestamp": int(time.time() * 1000)},
            "xrp_jpy": {"last": "125.000", "buy": "124.950", "sell": "125.050", "high": "128.000", "low": "122.000", "vol": "92000.0", "timestamp": int(time.time() * 1000)},
            "arb_jpy": {"last": "28.971", "buy": "28.960", "sell": "28.980", "high": "30.500", "low": "28.000", "vol": "45000.0", "timestamp": int(time.time() * 1000)},
        }

        # Custom candles cache: (pair, tf, day) -> list of [o, h, l, c, v, ts]
        self.custom_candles: Dict[Tuple[str, str, str], List[List[Union[str, int]]]] = {}

        # Trade and fee statistics
        self.realized_pnl_jpy: float = 0.0
        self.fees_paid_jpy: float = 0.0
        self.rebates_earned_jpy: float = 0.0
        self.trade_history: List[Dict[str, Any]] = []

    # =========================================================================
    # Fault Injection and Simulation Methods
    # =========================================================================

    def simulate_maintenance(self, active: bool = True) -> None:
        """Toggle Bitbank routine Monday maintenance mode (code 10007)."""
        self.maintenance_mode = active

    def simulate_nonce_collision(self, count: int = 1) -> None:
        """Inject N consecutive nonce collisions (code 20001)."""
        self.nonce_collisions_remaining = count

    def set_price(self, pair: str, price: float, spread_pct: float = 0.001) -> None:
        """Set best bid/ask and last price for a pair."""
        meta = MARGIN_PAIRS_META.get(pair, {"price_digits": 2})
        pd = meta["price_digits"]
        half_spread = price * (spread_pct / 2.0)
        bid = price - half_spread
        ask = price + half_spread

        last_str = f"{price:.{pd}f}" if pd > 0 else str(int(round(price)))
        buy_str = f"{bid:.{pd}f}" if pd > 0 else str(int(round(bid)))
        sell_str = f"{ask:.{pd}f}" if pd > 0 else str(int(round(ask)))

        self.tickers[pair]["last"] = last_str
        self.tickers[pair]["buy"] = buy_str
        self.tickers[pair]["sell"] = sell_str
        self.tickers[pair]["timestamp"] = int(time.time() * 1000)

    def simulate_tick(self, pair: str, price: float) -> List[Dict[str, Any]]:
        """Simulate a price tick, evaluating conditional stop orders and resting limit fills.
        Returns a list of triggered/filled orders.
        """
        self.set_price(pair, price)
        triggered_orders: List[Dict[str, Any]] = []

        # Evaluate active orders for this pair
        for oid, order in list(self.orders.items()):
            if order["pair"] != pair or order["status"] != "UNFILLED":
                continue

            # 1. Evaluate Native Stop Orders
            if order["type"] == "stop":
                trigger_px = float(order["trigger_price"])
                side = order["side"]
                position_side = order.get("position_side")

                # Buy Stop (Covering Short): triggers when price >= trigger_px
                # Sell Stop (Closing Long): triggers when price <= trigger_px
                is_triggered = False
                if side == "buy" and price >= trigger_px:
                    is_triggered = True
                elif side == "sell" and price <= trigger_px:
                    is_triggered = True

                if is_triggered:
                    fill_res = self._execute_stop_fill(order, fill_price=price)
                    triggered_orders.append(fill_res)

            # 2. Evaluate Resting Limit Orders
            elif order["type"] == "limit":
                limit_px = float(order["price"])
                side = order["side"]

                # Limit Buy fills if market trades at or below limit
                # Limit Sell fills if market trades at or above limit
                can_fill = False
                if side == "buy" and price <= limit_px:
                    can_fill = True
                elif side == "sell" and price >= limit_px:
                    can_fill = True

                if can_fill:
                    fill_res = self._execute_limit_fill(order, fill_price=limit_px)
                    triggered_orders.append(fill_res)

        return triggered_orders

    def simulate_fill(self, order_id: int, fill_price: Optional[float] = None) -> Dict[str, Any]:
        """Manually force execution of an unfilled limit order."""
        if order_id not in self.orders:
            raise BitbankError(f"Order {order_id} not found")
        order = self.orders[order_id]
        if order["status"] != "UNFILLED":
            return order

        px = fill_price if fill_price is not None else float(order.get("price") or self.tickers[order["pair"]]["last"])
        return self._execute_limit_fill(order, fill_price=px)

    def _execute_limit_fill(self, order: Dict[str, Any], fill_price: float) -> Dict[str, Any]:
        pair = order["pair"]
        side = order["side"]
        qty = float(order["start_amount"])
        position_side = order.get("position_side")
        meta = MARGIN_PAIRS_META.get(pair, MARGIN_PAIRS_META["sol_jpy"])
        maker_fee_rate = float(meta["maker_fee_rate_quote"])

        notional = qty * fill_price
        fee = notional * maker_fee_rate  # Negative fee = rebate paid to bot

        if fee < 0:
            self.rebates_earned_jpy += abs(fee)
            self.jpy_free += abs(fee)
        else:
            self.fees_paid_jpy += fee
            self.jpy_free -= fee

        # Update position
        if position_side == "short":
            if side == "sell":  # Opening or increasing short
                self._update_margin_position(pair, "short", delta_amount=qty, fill_price=fill_price)
            elif side == "buy":  # Covering short
                self._update_margin_position(pair, "short", delta_amount=-qty, fill_price=fill_price)
        elif position_side == "long":
            if side == "buy":
                self._update_margin_position(pair, "long", delta_amount=qty, fill_price=fill_price)
            elif side == "sell":
                self._update_margin_position(pair, "long", delta_amount=-qty, fill_price=fill_price)
        else:
            # Spot long
            base_coin = pair.split("_")[0]
            if side == "buy":
                cost = notional + max(0.0, fee)
                self.jpy_free -= cost
                self.crypto_assets.setdefault(base_coin, {"free": 0.0, "locked": 0.0})
                self.crypto_assets[base_coin]["free"] += qty
            elif side == "sell":
                revenue = notional - max(0.0, fee)
                self.jpy_free += revenue
                if base_coin in self.crypto_assets:
                    self.crypto_assets[base_coin]["free"] = max(0.0, self.crypto_assets[base_coin]["free"] - qty)

        order["status"] = "FULLY_FILLED"
        order["executed_amount"] = order["start_amount"]
        order["remaining_amount"] = "0.0000"
        order["average_price"] = str(fill_price)
        self.trade_history.append(copy.deepcopy(order))
        return order

    def _execute_stop_fill(self, order: Dict[str, Any], fill_price: float) -> Dict[str, Any]:
        pair = order["pair"]
        side = order["side"]
        qty = float(order["start_amount"])
        position_side = order.get("position_side")
        meta = MARGIN_PAIRS_META.get(pair, MARGIN_PAIRS_META["sol_jpy"])
        taker_fee_rate = float(meta["taker_fee_rate_quote"])

        notional = qty * fill_price
        fee = notional * taker_fee_rate
        self.fees_paid_jpy += fee
        self.jpy_free -= fee

        if position_side == "short" and side == "buy":
            # Covering margin short
            self._update_margin_position(pair, "short", delta_amount=-qty, fill_price=fill_price)
        elif position_side == "long" and side == "sell":
            # Closing margin long
            self._update_margin_position(pair, "long", delta_amount=-qty, fill_price=fill_price)
        elif position_side in ("long", "short"):
            # Market order that opens or adds to a margin position
            self._update_margin_position(pair, position_side, delta_amount=qty, fill_price=fill_price)
        elif side == "sell":
            # Spot stop exit
            base_coin = pair.split("_")[0]
            revenue = notional - fee
            self.jpy_free += revenue
            if base_coin in self.crypto_assets:
                self.crypto_assets[base_coin]["free"] = max(0.0, self.crypto_assets[base_coin]["free"] - qty)

        order["status"] = "FULLY_FILLED"
        order["executed_amount"] = order["start_amount"]
        order["remaining_amount"] = "0.0000"
        order["average_price"] = str(fill_price)
        self.trade_history.append(copy.deepcopy(order))
        return order

    def _update_margin_position(self, pair: str, side: str, delta_amount: float, fill_price: float) -> None:
        pos = None
        for p in self.margin_positions_list:
            if p["pair"] == pair and p["position_side"] == side:
                pos = p
                break

        if pos is None:
            pos = {"pair": pair, "position_side": side, "open_amount": "0.0000", "average_price": "0.0"}
            self.margin_positions_list.append(pos)

        current_amt = float(pos["open_amount"])
        current_avg = float(pos["average_price"])

        if delta_amount > 0:
            # Increasing position
            new_amt = current_amt + delta_amount
            if new_amt > 0:
                new_avg = ((current_amt * current_avg) + (delta_amount * fill_price)) / new_amt
            else:
                new_avg = 0.0
            pos["open_amount"] = f"{new_amt:.4f}"
            pos["average_price"] = f"{new_avg:.4f}"
        else:
            # Decreasing / covering position
            covered = min(abs(delta_amount), current_amt)   # a closing order cannot close more than is open
            new_amt = max(0.0, current_amt - covered)
            pnl = 0.0
            if side == "short":
                pnl = covered * (current_avg - fill_price)
            else:
                pnl = covered * (fill_price - current_avg)

            self.realized_pnl_jpy += pnl
            self.jpy_free += pnl
            pos["open_amount"] = f"{new_amt:.4f}"
            if new_amt == 0.0:
                pos["average_price"] = "0.0"

    # =========================================================================
    # Invariant Verification Assertions
    # =========================================================================

    def assert_zero_naked_positions(self) -> None:
        """Assert that no margin position exists without a confirmed active native stop order."""
        for p in self.margin_positions_list:
            amt = float(p["open_amount"])
            if amt <= 0.0001:
                continue
            pair = p["pair"]
            side = p["position_side"]

            # Required stop order side
            req_side = "buy" if side == "short" else "sell"

            active_stops = [
                o for o in self.orders.values()
                if o["pair"] == pair
                and o["type"] == "stop"
                and o["status"] == "UNFILLED"
                and o.get("position_side") == side
                and o["side"] == req_side
            ]

            total_stop_covered = sum(float(o["start_amount"]) for o in active_stops)
            if not active_stops or total_stop_covered < amt * 0.999:
                raise AssertionError(
                    f"INVARIANT VIOLATION: Naked margin position detected on {pair} ({side})! "
                    f"Open amount: {amt}, Covered by active stop: {total_stop_covered}"
                )

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Return margin positions with open_amount > 0."""
        return [p for p in self.margin_positions_list if float(p["open_amount"]) > 0.0]

    def get_active_stops(self, pair: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all active UNFILLED stop orders."""
        return [
            o for o in self.orders.values()
            if o["type"] == "stop" and o["status"] == "UNFILLED" and (pair is None or o["pair"] == pair)
        ]

    # =========================================================================
    # Bitbank REST API Interface Simulation
    # =========================================================================

    def _check_fault_injection(self, path: str) -> None:
        if self.maintenance_mode:
            raise BitbankError(f"{path}: {{'success': 0, 'data': {{'code': 10007}}}}")
        if self.nonce_collisions_remaining > 0:
            self.nonce_collisions_remaining -= 1
            raise BitbankError(f"{path}: {{'success': 0, 'data': {{'code': 20001}}}}")

    def _pub(self, path: str) -> Dict[str, Any]:
        self._check_fault_injection(path)
        return self._route_request("GET", path, None)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._check_fault_injection(path)
        return self._route_request("GET", path, params)

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self._check_fault_injection(path)
        return self._route_request("POST", path, body)

    def _route_request(self, method: str, path: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        # Strip query string if present
        clean_path = path.split("?")[0]

        if method == "GET":
            if "/ticker" in clean_path:
                pair = clean_path.strip("/").split("/")[0]
                return self.ticker(pair)

            if "/depth" in clean_path:
                pair = clean_path.strip("/").split("/")[0]
                return self.depth(pair)

            if "/candlestick" in clean_path:
                parts = clean_path.strip("/").split("/")
                pair = parts[0]
                tf = parts[2]
                day = parts[3]
                return {"candlestick": [{"type": tf, "ohlcv": self.candles(pair, tf, day)}]}

            if clean_path in ("/user/assets", "/v1/user/assets"):
                assets_data = [
                    {"asset": "jpy", "free_amount": f"{self.jpy_free:.4f}", "locked_amount": f"{self.jpy_locked:.4f}", "onhand_amount": f"{self.jpy_free + self.jpy_locked:.4f}"}
                ]
                for coin, balances in self.crypto_assets.items():
                    free_amt = balances["free"]
                    locked_amt = balances["locked"]
                    assets_data.append({
                        "asset": coin,
                        "free_amount": f"{free_amt:.4f}",
                        "locked_amount": f"{locked_amt:.4f}",
                        "onhand_amount": f"{free_amt + locked_amt:.4f}",
                    })
                return {"assets": assets_data}

            if clean_path in ("/user/margin/positions", "/v1/user/margin/positions"):
                return {"positions": copy.deepcopy(self.margin_positions_list)}

            if clean_path in ("/user/margin/status", "/v1/user/margin/status"):
                total_equity = self.calculate_total_equity()
                buying_power = total_equity * 2.0
                return {
                    "collateral_jpy": f"{total_equity:.2f}",
                    "margin_ratio": "0.50",
                    "buying_power_jpy": f"{buying_power:.2f}",
                    "maintenance_margin_rate": "0.50",
                    "status": "normal",
                }

            if clean_path in ("/user/spot/order", "/v1/user/spot/order"):
                oid = int(payload.get("order_id", 0)) if payload else 0
                if oid in self.orders:
                    return copy.deepcopy(self.orders[oid])
                raise BitbankError(f"Order {oid} not found")

            if clean_path in ("/user/spot/active_orders", "/v1/user/spot/active_orders"):
                pair = payload.get("pair") if payload else None
                matched = [
                    copy.deepcopy(o) for o in self.orders.values()
                    if o["status"] == "UNFILLED" and (pair is None or o["pair"] == pair)
                ]
                return {"orders": matched}

            if clean_path in ("/spot/pairs", "/v1/spot/pairs"):
                return {"pairs": list(MARGIN_PAIRS_META.values())}

        elif method == "POST":
            if clean_path in ("/user/spot/order", "/v1/user/spot/order"):
                return self._handle_order_creation(payload or {})

            if clean_path in ("/user/spot/cancel_order", "/v1/user/spot/cancel_order"):
                oid = int(payload.get("order_id", 0)) if payload else 0
                if oid in self.orders:
                    order = self.orders[oid]
                    if order["status"] == "UNFILLED":
                        order["status"] = "CANCELED_UNFILLED"
                    return copy.deepcopy(order)
                raise BitbankError(f"Cannot cancel: Order {oid} not found")

        raise BitbankError(f"Mock endpoint not found: {method} {path}")

    def _handle_order_creation(self, b: Dict[str, Any]) -> Dict[str, Any]:
        pair = b.get("pair")
        order_type = b.get("type", "market")
        side = b.get("side")
        amount_str = b.get("amount")
        price_str = b.get("price")
        trigger_price_str = b.get("trigger_price")
        position_side = b.get("position_side")
        post_only = b.get("post_only", False)
        if isinstance(post_only, str):
            post_only = post_only.lower() in ("true", "1")

        if pair not in MARGIN_PAIRS_META:
            raise BitbankError(f"Unknown pair: {pair}")

        meta = MARGIN_PAIRS_META[pair]

        # REJECTION VALIDATION FOR NON-MARGIN PAIRS
        if order_type == "stop":
            if not meta.get("stop_order", False) or not meta.get("is_margin", False):
                raise BitbankError(f"Stop orders not supported on spot-only pair {pair} (code 60011)")

        if amount_str is None:
            raise BitbankError("amount is required")
        qty = float(amount_str)

        self.order_counter += 1
        oid = self.order_counter

        order_record: Dict[str, Any] = {
            "order_id": oid,
            "pair": pair,
            "side": side,
            "type": order_type,
            "start_amount": amount_str,
            "remaining_amount": amount_str,
            "executed_amount": "0.0000",
            "price": price_str,
            "trigger_price": trigger_price_str,
            "position_side": position_side,
            "post_only": bool(post_only),
            "status": "UNFILLED",
            "average_price": "0.0",
            "ordered_at": int(time.time() * 1000),
        }
        self.orders[oid] = order_record

        # Immediate Market Order Fill
        if order_type == "market":
            current_px = float(self.tickers[pair]["last"])
            if side == "buy":
                # Market buy executes at best ask
                fill_px = float(self.tickers[pair]["sell"])
            else:
                # Market sell executes at best bid
                fill_px = float(self.tickers[pair]["buy"])
            return self._execute_stop_fill(order_record, fill_price=fill_px)

        # Immediate check for post_only violation
        if order_type == "limit" and post_only:
            limit_px = float(price_str)
            best_bid = float(self.tickers[pair]["buy"])
            best_ask = float(self.tickers[pair]["sell"])

            if (side == "buy" and limit_px >= best_ask) or (side == "sell" and limit_px <= best_bid):
                order_record["status"] = "CANCELED_UNFILLED"
                # On Bitbank, post_only crossing spread gets canceled immediately

        return copy.deepcopy(order_record)

    # =========================================================================
    # Public & Helper Methods Mirroring `Bitbank` Class
    # =========================================================================

    def ticker(self, pair: str) -> Dict[str, Any]:
        self._check_fault_injection(f"/{pair}/ticker")
        if pair not in self.tickers:
            raise BitbankError(f"Unknown ticker: {pair}")
        return copy.deepcopy(self.tickers[pair])

    def tickers(self) -> List[Dict[str, Any]]:
        self._check_fault_injection("/tickers")
        res = []
        for pair, tk in self.tickers.items():
            item = copy.deepcopy(tk)
            item["pair"] = pair
            res.append(item)
        return res

    def depth(self, pair: str, depth_levels: int = 20) -> Dict[str, Any]:
        self._check_fault_injection(f"/{pair}/depth")
        tk = self.ticker(pair)
        mid_px = float(tk["last"])
        meta = MARGIN_PAIRS_META.get(pair, MARGIN_PAIRS_META["sol_jpy"])
        pd = meta["price_digits"]

        step = mid_px * 0.0005
        bids: List[List[str]] = []
        asks: List[List[str]] = []

        for i in range(1, depth_levels + 1):
            bid_p = mid_px - (i * step)
            ask_p = mid_px + (i * step)
            vol = 10.0 + (i * 1.5)
            # Inject a resistance wall at level 5
            if i == 5:
                vol = 150.0  # Liquidity wall (>3.0x avg volume)

            bids.append([f"{bid_p:.{pd}f}" if pd > 0 else str(int(round(bid_p))), f"{vol:.4f}"])
            asks.append([f"{ask_p:.{pd}f}" if pd > 0 else str(int(round(ask_p))), f"{vol:.4f}"])

        return {
            "bids": bids,
            "asks": asks,
            "timestamp": int(time.time() * 1000),
        }

    def candles(self, pair: str, tf: str, day: str) -> List[List[Union[str, int]]]:
        self._check_fault_injection(f"/{pair}/candlestick/{tf}/{day}")
        key = (pair, tf, str(day))
        if key in self.custom_candles:
            return copy.deepcopy(self.custom_candles[key])

        # Generate realistic default synthetic candle series
        tk = self.ticker(pair)
        current_px = float(tk["last"])
        meta = MARGIN_PAIRS_META.get(pair, MARGIN_PAIRS_META["sol_jpy"])
        pd = meta["price_digits"]

        candles_data: List[List[Union[str, int]]] = []
        now_ms = int(time.time() * 1000)
        step_ms = 900000 if tf == "15min" else (3600000 if tf == "1hour" else 14400000)

        for i in range(100, 0, -1):
            ts = now_ms - (i * step_ms)
            o = current_px * (1.0 + 0.001 * math.sin(i / 5.0))
            h = o * 1.002
            l = o * 0.998
            c = (o + h + l) / 3.0
            v = 50.0 + (i % 10) * 5.0

            p_fmt = (lambda x: f"{x:.{pd}f}" if pd > 0 else str(int(round(x))))
            candles_data.append([p_fmt(o), p_fmt(h), p_fmt(l), p_fmt(c), f"{v:.4f}", ts])

        return candles_data

    def set_custom_candles(self, pair: str, tf: str, day: str, candles: List[List[Union[str, int]]]) -> None:
        """Inject customized test candle fixtures."""
        self.custom_candles[(pair, tf, str(day))] = candles

    def assets(self) -> Dict[str, float]:
        res = self._get("/user/assets")
        return {a["asset"]: float(a["free_amount"]) for a in res["assets"]}

    def assets_onhand(self) -> Dict[str, float]:
        res = self._get("/user/assets")
        return {a["asset"]: float(a["onhand_amount"]) for a in res["assets"]}

    def order(self, pair: str, side: str, amount: Optional[float] = None, price: Optional[float] = None, type_: str = "market", **extra: Any) -> Dict[str, Any]:
        b: Dict[str, Any] = {"pair": pair, "side": side, "type": type_}
        if amount is not None:
            b["amount"] = str(amount)
        if price is not None:
            b["price"] = str(price)
        for k, v in extra.items():
            if k == "post_only" and isinstance(v, bool):
                b[k] = v  # Preserve boolean!
            else:
                b[k] = str(v) if not isinstance(v, bool) else v
        return self._post("/user/spot/order", b)

    def margin_positions(self) -> List[Dict[str, Any]]:
        return self._get("/user/margin/positions")["positions"]

    def get_order(self, pair: str, oid: int) -> Dict[str, Any]:
        return self._get("/user/spot/order", {"pair": pair, "order_id": oid})

    def cancel(self, pair: str, oid: int) -> Dict[str, Any]:
        return self._post("/user/spot/cancel_order", {"pair": pair, "order_id": oid})

    def pair_info(self, pair: str) -> Dict[str, Any]:
        d = self._get("/spot/pairs")
        for p in d["pairs"]:
            if p["name"] == pair:
                return p
        raise BitbankError(f"unknown pair: {pair}")

    def calculate_total_equity(self) -> float:
        """Calculate total account equity: Cash + Crypto Holdings + Margin Unrealized PnL."""
        equity = self.jpy_free + self.jpy_locked

        # Crypto holdings valuation
        for coin, balances in self.crypto_assets.items():
            tot = balances["free"] + balances["locked"]
            if tot > 0:
                tk = self.tickers.get(f"{coin}_jpy")
                if tk:
                    equity += tot * float(tk["last"])

        # Margin positions unrealized PnL
        for p in self.margin_positions_list:
            amt = float(p["open_amount"])
            if amt > 0:
                avg_px = float(p["average_price"])
                pair = p["pair"]
                side = p["position_side"]
                tk = self.tickers.get(pair)
                if tk:
                    last_px = float(tk["last"])
                    if side == "short":
                        equity += amt * (avg_px - last_px)
                    else:
                        equity += amt * (last_px - avg_px)

        return equity
