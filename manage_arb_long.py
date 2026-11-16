#!/usr/bin/env python3
"""
Autonomous Spot Momentum Long Manager on ARB/JPY.
- Capital Allocation: ~¥7,500 JPY (~74% of 10,147 JPY cash equity)
- Sizing: 258.0000 ARB
- Entry: Maker limit buy at best bid (~29.050 JPY) to capture -0.02% maker rebate.
- Take Profit Target: 30.450 JPY (+4.8%, target payout: ~+¥361 net).
- Protective Stop Loss: 28.300 JPY (below 21:00 breakout candle base; max risk: ~-193 JPY / 1.9% equity).
- Trailing Ratchets:
  - Break-even ratchet at 29.500 JPY (moves stop to 29.050 JPY, 0 risk).
  - Profit lock ratchet at 29.900 JPY (moves stop to 29.500 JPY, +¥116 guaranteed).
"""

import sys
import time
import datetime as dt
from tradingbot import bot  # loads env
from tradingbot.bitbank import Bitbank

PAIR = "arb_jpy"
AMOUNT = 258.0000
TARGET_PRICE = 30.450
INITIAL_STOP = 28.300
BREAKEVEN_TRIGGER = 29.500
LOCK_TRIGGER = 29.900
LOCK_STOP = 29.500

api = Bitbank()

def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_spot_arb_balance():
    try:
        assets = api._get("/user/assets").get("assets", [])
        for a in assets:
            if a.get("asset") == "arb":
                return float(a.get("free_amount", 0)), float(a.get("locked_amount", 0))
        return 0.0, 0.0
    except Exception as e:
        log(f"Error checking ARB asset: {e}")
        return 0.0, 0.0

def get_active_orders():
    try:
        res = api._get("/user/spot/active_orders", {"pair": PAIR})
        return res.get("orders", [])
    except Exception as e:
        log(f"Error checking active orders: {e}")
        return []

def cancel_order(oid):
    try:
        api.cancel(PAIR, oid)
        log(f"Cancelled order {oid}")
        time.sleep(0.3)
    except Exception as e:
        log(f"Error cancelling order {oid}: {e}")

def place_maker_buy():
    tk = api.ticker(PAIR)
    best_bid = float(tk.get("buy", 29.050))
    log(f"Placing ARB maker limit buy: BUY {AMOUNT:.4f} ARB @ {best_bid:.3f} JPY")
    try:
        res = api._post("/user/spot/order", {
            "pair": PAIR,
            "amount": f"{AMOUNT:.4f}",
            "price": f"{best_bid:.3f}",
            "side": "buy",
            "type": "limit",
            "post_only": False,
        })
        oid = res.get("order_id")
        log(f"ARB Maker Buy placed successfully! Order ID: {oid}")
        return oid, best_bid
    except Exception as e:
        log(f"Failed to place ARB buy order: {e}")
        return None, best_bid

def market_sell(amount):
    log(f"Executing MARKET SELL: {amount:.4f} ARB")
    try:
        res = api._post("/user/spot/order", {
            "pair": PAIR,
            "amount": f"{amount:.4f}",
            "side": "sell",
            "type": "market",
        })
        log(f"Market sell executed successfully: {res}")
        return res
    except Exception as e:
        log(f"Failed market sell: {e}")
        return None

def main():
    log("=== ARB/JPY Autonomous Spot Momentum Long Manager Launched ===")

    free_arb, locked_arb = get_spot_arb_balance()
    active_orders = get_active_orders()
    
    current_stop = INITIAL_STOP
    breakeven_hit = False
    lock_hit = False
    entry_price = 29.050

    # If no ARB held and no buy orders, place maker buy
    buy_orders = [o for o in active_orders if o.get("side") == "buy"]
    if free_arb < 1.0 and locked_arb < 1.0 and not buy_orders:
        oid, entry_price = place_maker_buy()

    while True:
        try:
            free_arb, locked_arb = get_spot_arb_balance()
            total_arb = free_arb + locked_arb
            active_orders = get_active_orders()
            
            tk = api.ticker(PAIR)
            last_px = float(tk.get("last", 0.0))
            best_bid = float(tk.get("buy", 0.0))
            best_ask = float(tk.get("sell", 0.0))

            if total_arb >= 1.0:
                # We hold ARB position!
                pnl_jpy = total_arb * (last_px - entry_price)
                pnl_pct = ((last_px - entry_price) / entry_price) * 100.0
                log(f"Holding: {total_arb:.4f} ARB (Free: {free_arb:.4f}, Locked: {locked_arb:.4f}) | Last: {last_px:.3f} | Entry: {entry_price:.3f} | PnL: {pnl_jpy:+.1f} JPY ({pnl_pct:+.2f}%) | Stop: {current_stop:.3f}")

                # 1. Stop loss check
                if last_px <= current_stop:
                    log(f"STOP TRIGGERED! Price {last_px:.3f} <= Stop {current_stop:.3f}. Exiting position immediately...")
                    for o in active_orders:
                        cancel_order(o.get("order_id"))
                    time.sleep(0.5)
                    free_arb, _ = get_spot_arb_balance()
                    if free_arb >= 1.0:
                        market_sell(free_arb)
                    log("ARB Position closed on stop loss.")
                    break

                # 2. Break-even ratchet check
                if not breakeven_hit and last_px >= BREAKEVEN_TRIGGER:
                    log(f"Ratcheting stop to BREAK-EVEN at {entry_price:.3f} (last px: {last_px:.3f})...")
                    current_stop = entry_price
                    breakeven_hit = True

                # 3. Profit lock ratchet check
                if not lock_hit and last_px >= LOCK_TRIGGER:
                    log(f"Ratcheting stop to PROFIT LOCK at {LOCK_STOP:.3f} (last px: {last_px:.3f})...")
                    current_stop = LOCK_STOP
                    lock_hit = True

                # 4. Take profit target check
                if last_px >= TARGET_PRICE:
                    log(f"TARGET HIT! Price reached {last_px:.3f} >= {TARGET_PRICE:.3f}. Taking profit...")
                    for o in active_orders:
                        cancel_order(o.get("order_id"))
                    time.sleep(0.5)
                    free_arb, _ = get_spot_arb_balance()
                    if free_arb >= 1.0:
                        market_sell(free_arb)
                    log("Target Profit Captured! ARB Trade Complete!")
                    break

            else:
                # Still waiting for buy fill
                buy_orders = [o for o in active_orders if o.get("side") == "buy"]
                if buy_orders:
                    bo = buy_orders[0]
                    bo_px = float(bo.get("price", 0))
                    bo_amt = float(bo.get("start_amount", 0))
                    dist = last_px - bo_px
                    log(f"Waiting for Buy Fill: BUY {bo_amt:.4f} ARB @ {bo_px:.3f} JPY | Current Last: {last_px:.3f} | Distance: {dist:+.3f} JPY")
                    # If market runs away upwards by > 0.15 JPY, chase the bid to ensure fill
                    if dist > 0.15:
                        log(f"Market moving up ({last_px:.3f} vs order {bo_px:.3f}). Repositioning maker buy to best bid {best_bid:.3f}...")
                        cancel_order(bo.get("order_id"))
                        oid, entry_price = place_maker_buy()
                else:
                    log("No resting buy order. Repositioning maker buy...")
                    oid, entry_price = place_maker_buy()

            time.sleep(5)

        except Exception as e:
            log(f"Exception in ARB manager: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
