#!/usr/bin/env python3
"""
Trade #21: Autonomous 1.6x Leveraged Margin Short on SOL/JPY.
- User Mandate: Immediate live trading, aggressive compounding towards 2X/10X goals, strictly mandatory exchange-side stop.
- Sizing: 1.1800 SOL (~16,196 JPY notional / 1.597x leverage on 10,142 JPY equity = 80% of 2.0x leverage).
- Setup: Fading massive 580 SOL resistance wall between 13,725 - 13,730 JPY.
- Entry: Maker limit short sell @ 13,726.0 JPY.
- Stop Loss: Native Bitbank exchange-side stop order @ trigger 13,820.0 JPY (armed immediately upon fill, max risk ~-110 JPY / 1.08% equity).
- Take Profit Target: 13,460.0 JPY (Target payout: +313.9 JPY + maker rebate, > 2.8:1 R:R).
- Trailing Ratchets: Break-even at 13,600.0 JPY; lock profit at 13,520.0 JPY (stop: 13,580.0 JPY).
"""

import os
import sys
import time
import datetime as dt

def load_env(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    load_env(env_path)
else:
    load_env('/home/karma/Trading-bot/.env')

from tradingbot import bot
from tradingbot.bitbank import Bitbank

PAIR = "sol_jpy"
AMOUNT = 1.1800  # 80% of 2.0x leverage
ENTRY_PRICE = 13726.0
STOP_PRICE = 13820.0
TARGET_PRICE = 13460.0
BREAKEVEN_TRIGGER = 13600.0
LOCK_TRIGGER = 13520.0
LOCK_STOP = 13580.0

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
            log(f"Bitbank API error in get_position: {e}. Retrying in 5s...")
            time.sleep(5)

def get_active_orders():
    while True:
        try:
            res = api._get("/user/spot/active_orders", {"pair": PAIR})
            return res.get("orders", [])
        except Exception as e:
            log(f"Bitbank API error in get_active_orders: {e}. Retrying in 5s...")
            time.sleep(5)

def place_maker_limit_sell(amount, price):
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
        log(f"Maker limit sell placed! Order ID: {oid}")
        return oid
    except Exception as e:
        log(f"Failed to place limit sell: {e}")
        return None

def place_native_exchange_stop(amount, trigger_px):
    log(f"Placing native exchange-side stop order: BUY {amount:.4f} SOL @ trigger {trigger_px:.1f} JPY")
    while True:
        try:
            res = api._post("/user/spot/order", {
                "pair": PAIR,
                "amount": f"{amount:.4f}",
                "price": f"{trigger_px:.1f}",
                "side": "buy",
                "type": "stop",
                "trigger_price": f"{trigger_px:.1f}",
                "position_side": "short",
                "post_only": False,
            })
            oid = res.get("order_id")
            log(f"Native exchange stop order placed successfully on Bitbank matching engine! Order ID: {oid}")
            return oid
        except Exception as e:
            log(f"Failed to place native exchange stop: {e}. Retrying in 5s...")
            time.sleep(5)

def cancel_order(oid):
    try:
        api.cancel(PAIR, oid)
        log(f"Cancelled order {oid}")
        time.sleep(0.3)
    except Exception as e:
        log(f"Error cancelling order {oid}: {e}")

def main():
    log("=== SOL/JPY Autonomous 1.6x Leverage Margin Short Manager (Trade #21) Launched ===")

    current_stop_price = STOP_PRICE
    breakeven_hit = False
    lock_hit = False

    pos_amt, avg_entry = get_position()
    active_orders = get_active_orders()

    limit_sells = [o for o in active_orders if o.get("side") == "sell" and o.get("type") == "limit"]
    stop_orders = [o for o in active_orders if o.get("side") == "buy" and o.get("type") == "stop"]

    if pos_amt == 0.0 and not limit_sells:
        log("Placing Trade #21 maker limit short order...")
        place_maker_limit_sell(AMOUNT, ENTRY_PRICE)

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

                # 1. Ensure mandatory native exchange stop order is resting on Bitbank
                needs_stop = False
                if not stop_orders:
                    needs_stop = True
                else:
                    so = stop_orders[0]
                    so_amt = float(so.get("start_amount") or so.get("remaining_amount") or 0.0)
                    so_trig = float(so.get("trigger_price") or 0.0)
                    if abs(so_amt - pos_amt) > 0.0001 or abs(so_trig - current_stop_price) > 0.1:
                        log(f"Stop sync mismatch (Current: {so_amt:.4f} @ {so_trig:.1f} | Needed: {pos_amt:.4f} @ {current_stop_price:.1f}). Resyncing...")
                        for o in stop_orders:
                            cancel_order(o.get("order_id"))
                        needs_stop = True

                if needs_stop:
                    place_native_exchange_stop(pos_amt, current_stop_price)

                # 2. Ratchet to Break-Even
                if not breakeven_hit and last_px <= BREAKEVEN_TRIGGER:
                    log(f"Ratcheting stop to BREAK-EVEN at {avg_entry:.1f} (last px: {last_px:.1f})...")
                    current_stop_price = avg_entry
                    breakeven_hit = True
                    for o in stop_orders:
                        cancel_order(o.get("order_id"))
                    place_native_exchange_stop(pos_amt, current_stop_price)

                # 3. Ratchet to Profit Lock
                if not lock_hit and last_px <= LOCK_TRIGGER:
                    log(f"Ratcheting stop to PROFIT LOCK at {LOCK_STOP:.1f} (last px: {last_px:.1f})...")
                    current_stop_price = LOCK_STOP
                    lock_hit = True
                    for o in stop_orders:
                        cancel_order(o.get("order_id"))
                    place_native_exchange_stop(pos_amt, current_stop_price)

                # 4. Target cover
                if last_px <= TARGET_PRICE:
                    log(f"TARGET HIT ({last_px:.1f} <= {TARGET_PRICE:.1f})! Covering position at market...")
                    for o in active_orders:
                        cancel_order(o.get("order_id"))
                    api._post("/user/spot/order", {
                        "pair": PAIR,
                        "amount": f"{pos_amt:.4f}",
                        "side": "buy",
                        "type": "market",
                        "position_side": "short",
                    })
                    log("Trade #21 Completed Successfully!")
                    break

            else:
                if limit_sells:
                    ls = limit_sells[0]
                    ls_px = float(ls.get("price", 0))
                    ls_amt = float(ls.get("start_amount", 0))
                    dist = ls_px - last_px
                    log(f"Waiting for Short Fill: SELL {ls_amt:.4f} SOL @ {ls_px:.1f} JPY | Current Last: {last_px:.1f} | Bid: {best_bid:.1f} | Ask: {best_ask:.1f} | Dist: {dist:+.1f} JPY")
                else:
                    log("Placing Trade #21 entry order...")
                    place_maker_limit_sell(AMOUNT, ENTRY_PRICE)

            time.sleep(5)

        except Exception as e:
            log(f"Exception in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
