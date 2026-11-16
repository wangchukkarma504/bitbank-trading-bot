#!/usr/bin/env python3
"""
Trade #19: Autonomous 1.6x Leveraged Margin Short on SOL/JPY.
- User Mandate: Use 2x leverage, allocating 80% including leverage (1.60x notional equity allocation).
- Sizing: 1.1800 SOL total (~16,130 JPY notional / 1.59x leverage on 10,147 JPY equity).
- Structure: Rejection wick at 13,744.5 JPY; fade relief bounce into 13,670 - 13,710 resistance.
- Scale-in Order 1: 0.7000 SOL Maker Limit Sell @ 13,670.0 JPY.
- Scale-in Order 2: 0.4800 SOL Maker Limit Sell @ 13,710.0 JPY.
- Protective Stop Loss: Mandatory exchange stop order at 13,810.0 JPY (above 20:15 swing high).
- Max Risk: Strictly capped at ~140 JPY (1.38% equity).
- Take Profit Target: 13,440.0 JPY (Target payout: ~+270 to +320 JPY, > 2.2:1 R:R).
- Trailing Ratchets: Break-even at 13,560.0 JPY; lock profit at 13,490.0 JPY (stop: 13,530.0 JPY).
- Maintenance resilience: Gracefully retries during Bitbank maintenance (code 10007).
"""

import sys
import time
import datetime as dt
from tradingbot import bot  # noqa: F401
from tradingbot.bitbank import Bitbank

PAIR = "sol_jpy"
TARGET_TOTAL_AMOUNT = 1.1800  # 80% of 2.0x leverage = 1.60x notional
STOP_PRICE = 13810.0
TARGET_PRICE = 13440.0
BREAKEVEN_TRIGGER = 13560.0
LOCK_TRIGGER = 13490.0
LOCK_STOP = 13530.0

api = Bitbank()

def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_position():
    while True:
        try:
            positions = api.margin_positions()
            for p in positions:
                if p.get("pair") == PAIR and p.get("position_side") == "short":
                    amt = float(p.get("open_amount", 0))
                    if amt > 0:
                        return amt, float(p.get("average_price", 0))
            return 0.0, 0.0
        except Exception as e:
            log(f"Bitbank API/Maintenance Notice in get_position: {e}. Retrying in 10s...")
            time.sleep(10)

def get_active_orders():
    while True:
        try:
            res = api._get("/user/spot/active_orders", {"pair": PAIR})
            return res.get("orders", [])
        except Exception as e:
            log(f"Bitbank API/Maintenance Notice in get_active_orders: {e}. Retrying in 10s...")
            time.sleep(10)

def place_limit_sell(amount, price):
    log(f"Placing maker limit short order: SELL {amount:.4f} SOL @ {price:.1f} JPY")
    try:
        res = api._post("/user/spot/order", {
            "pair": PAIR,
            "amount": f"{amount:.4f}",
            "price": f"{price:.1f}",
            "side": "sell",
            "type": "limit",
            "position_side": "short",
            "post_only": False,
        })
        oid = res.get("order_id")
        log(f"Maker limit sell placed successfully! Order ID: {oid}")
        return oid
    except Exception as e:
        log(f"Failed to place limit sell order: {e}")
        return None

def cancel_order(oid):
    try:
        api.cancel(PAIR, oid)
        log(f"Cancelled order {oid}")
    except Exception as e:
        log(f"Could not cancel order {oid}: {e}")

def place_stop_loss(amount, trigger_price):
    log(f"Placing exchange stop order: BUY {amount:.4f} SOL @ trigger {trigger_price:.1f} JPY")
    while True:
        try:
            res = api._post("/user/spot/order", {
                "pair": PAIR,
                "amount": f"{amount:.4f}",
                "price": f"{trigger_price:.1f}",
                "side": "buy",
                "type": "stop",
                "trigger_price": f"{trigger_price:.1f}",
                "position_side": "short",
                "post_only": False,
            })
            oid = res.get("order_id")
            log(f"Exchange stop order placed successfully! Order ID: {oid}")
            return oid
        except Exception as e:
            log(f"Failed to place stop order: {e}. Retrying in 5s...")
            time.sleep(5)

def main():
    log("=== SOL/JPY Autonomous 1.6x Leverage Margin Short Manager (Trade #19) Launched ===")

    # Setup initial orders
    entry_1_px = 13670.0
    entry_1_amt = 0.7000
    entry_2_px = 13710.0
    entry_2_amt = 0.4800

    current_stop_price = STOP_PRICE
    breakeven_hit = False
    lock_hit = False

    # Check if orders or position already exist
    pos_amt, avg_entry = get_position()
    active_orders = get_active_orders()

    limit_sells = [o for o in active_orders if o.get("side") == "sell" and o.get("type") == "limit"]
    stop_orders = [o for o in active_orders if o.get("side") == "buy" and o.get("type") == "stop"]

    if pos_amt == 0.0 and not limit_sells:
        log("No active short or resting sells. Placing Trade #19 limit sell ladder...")
        place_limit_sell(entry_1_amt, entry_1_px)
        place_limit_sell(entry_2_amt, entry_2_px)

    while True:
        try:
            pos_amt, avg_entry = get_position()
            tk = api.ticker(PAIR)
            last_px = float(tk.get("last", 0.0))
            best_bid = float(tk.get("buy", 0.0))
            best_ask = float(tk.get("sell", 0.0))

            active_orders = get_active_orders()
            limit_sells = [o for o in active_orders if o.get("side") == "sell" and o.get("type") == "limit"]
            stop_orders = [o for o in active_orders if o.get("side") == "buy" and o.get("type") == "stop"]

            if pos_amt > 0.0:
                pnl = pos_amt * (avg_entry - last_px)
                log(f"Active Short: {pos_amt:.4f} SOL @ avg {avg_entry:.1f} | Current: {last_px:.1f} | PnL: {pnl:+.2f} JPY | Stop: {current_stop_price:.1f}")

                # 1. Synchronize protective stop loss
                needs_new_stop = False
                if not stop_orders:
                    needs_new_stop = True
                else:
                    curr_stop = stop_orders[0]
                    curr_stop_amt = float(curr_stop.get("start_amount") or curr_stop.get("remaining_amount") or 0.0)
                    curr_stop_trig = float(curr_stop.get("trigger_price") or 0.0)
                    if abs(curr_stop_amt - pos_amt) > 0.0001 or abs(curr_stop_trig - current_stop_price) > 0.1:
                        log(f"Stop mismatch (Current: {curr_stop_amt:.4f} @ {curr_stop_trig:.1f} | Required: {pos_amt:.4f} @ {current_stop_price:.1f}). Resyncing...")
                        for so in stop_orders:
                            cancel_order(so.get("order_id"))
                        needs_new_stop = True

                if needs_new_stop:
                    log(f"Placing synchronized exchange stop: {pos_amt:.4f} SOL @ {current_stop_price:.1f} JPY")
                    place_stop_loss(pos_amt, current_stop_price)

                # 2. Check ratchets
                if not breakeven_hit and last_px <= BREAKEVEN_TRIGGER:
                    log(f"Ratcheting stop to BREAK-EVEN at {avg_entry:.1f} (last px: {last_px:.1f})...")
                    current_stop_price = avg_entry
                    breakeven_hit = True
                    for so in stop_orders:
                        cancel_order(so.get("order_id"))
                    place_stop_loss(pos_amt, current_stop_price)

                if not lock_hit and last_px <= LOCK_TRIGGER:
                    log(f"Ratcheting stop to PROFIT LOCK at {LOCK_STOP:.1f} (last px: {last_px:.1f})...")
                    current_stop_price = LOCK_STOP
                    lock_hit = True
                    for so in stop_orders:
                        cancel_order(so.get("order_id"))
                    place_stop_loss(pos_amt, current_stop_price)

                # 3. Take profit target check
                if last_px <= TARGET_PRICE:
                    log(f"TARGET HIT! Price reached {last_px:.1f} <= {TARGET_PRICE:.1f}. Closing short position...")
                    for o in active_orders:
                        cancel_order(o.get("order_id"))
                    api._post("/user/spot/order", {
                        "pair": PAIR,
                        "amount": f"{pos_amt:.4f}",
                        "side": "buy",
                        "type": "market",
                        "position_side": "short",
                    })
                    log(f"Market cover order sent for {pos_amt:.4f} SOL. Trade #19 Complete!")
                    break

            else:
                # No open position
                if limit_sells:
                    s_str = ", ".join([f"{float(s.get('start_amount',0)):.4f} @ {float(s.get('price',0)):.1f}" for s in limit_sells])
                    log(f"Waiting for fill. Resting limit sell(s): [{s_str}] | Current Last: {last_px:.1f} | Bid: {best_bid:.1f} | Ask: {best_ask:.1f}")
                else:
                    log("No open position and no resting limit orders. Repositioning entry orders...")
                    place_limit_sell(entry_1_amt, entry_1_px)
                    place_limit_sell(entry_2_amt, entry_2_px)

            time.sleep(5)

        except Exception as e:
            log(f"Exception in main loop: {e}. Retrying in 5s...")
            time.sleep(5)

if __name__ == "__main__":
    main()
