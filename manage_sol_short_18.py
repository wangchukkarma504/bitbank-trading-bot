"""
Trade #18: Autonomous 1.6x Leveraged Margin Short on SOL/JPY.
- User Mandate: Use 2x leverage, allocating 80% including leverage (1.60x notional equity allocation).
- Sizing: 1.1800 SOL total (~16,180 JPY notional / 1.59x leverage on 10,173 JPY equity).
- Initial Fill: 0.7400 SOL @ 13,710.0 JPY (Filled).
- Scale-in Order: 0.4400 SOL @ 13,730.0 JPY (Filled!).
- Current Position: 1.1800 SOL @ avg 13,718.8 JPY.
- Protective Stop Loss: Mandatory exchange stop order at 13,830.0 JPY (Synchronized to 100% of open position).
- Max Risk: Strictly capped at ~131 JPY (1.29% equity).
- Take Profit Target: 13,470.0 JPY (Target payout: +293.58 JPY, 2.24:1 R:R).
- Trailing Ratchets: Break-even at 13,590.0 JPY; lock profit at 13,510.0 JPY (stop: 13,570.0 JPY).
- Maintenance resilience: Gracefully retries during Bitbank maintenance (code 10007).
"""

import sys
import time
import datetime as dt
from tradingbot import bot  # noqa: F401
from tradingbot.bitbank import Bitbank

PAIR = "sol_jpy"
TARGET_TOTAL_AMOUNT = 1.1800  # 80% of 2.0x leverage = 1.60x notional
STOP_PRICE = 13830.0
TARGET_PRICE = 13470.0
BREAKEVEN_TRIGGER = 13590.0
LOCK_TRIGGER = 13510.0
LOCK_STOP = 13570.0

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

def place_exchange_stop(amt, trigger_px):
    log(f"Placing exchange stop order: BUY {amt:.4f} SOL @ trigger {trigger_px:.1f} JPY")
    for attempt in range(10):
        try:
            res = api._post("/user/spot/order", {
                "pair": PAIR,
                "amount": f"{amt:.4f}",
                "trigger_price": f"{trigger_px:.1f}",
                "side": "buy",
                "type": "stop",
                "position_side": "short"
            })
            oid = res.get("order_id")
            log(f"Exchange stop order placed successfully! Order ID: {oid}")
            return oid
        except Exception as e:
            log(f"Attempt {attempt+1} placing exchange stop: {e}. Retrying in 10s...")
            time.sleep(10)
    return None

def cancel_order(oid):
    try:
        api.cancel(PAIR, oid)
        log(f"Cancelled order {oid}")
        time.sleep(0.3)
        return True
    except Exception as e:
        log(f"Error cancelling order {oid}: {e}")
        return False

def market_cover(amt):
    log(f"Executing MARKET COVER: {amt:.4f} SOL")
    for attempt in range(10):
        try:
            res = api._post("/user/spot/order", {
                "pair": PAIR,
                "amount": f"{amt:.4f}",
                "side": "buy",
                "type": "market",
                "position_side": "short"
            })
            log(f"Market cover order placed: {res}")
            return res
        except Exception as e:
            log(f"Attempt {attempt+1} market cover error: {e}. Retrying in 5s...")
            time.sleep(5)
    return None

def main():
    log("=== SOL/JPY Autonomous 1.6x Leverage Margin Short Manager Launched ===")
    
    stop_level = STOP_PRICE

    while True:
        try:
            time.sleep(5)
            tk = None
            try:
                tk = api.ticker(PAIR)
            except Exception as e:
                log(f"Ticker check notice: {e}")
                time.sleep(5)
                continue

            last_px = float(tk.get("last", 0))
            best_bid = float(tk.get("buy", 0))
            best_ask = float(tk.get("sell", 0))
            
            open_amt, avg_px = get_position()
            active_orders = get_active_orders()

            if open_amt == 0.0:
                log("No open margin position found. Exiting.")
                sys.exit(0)

            # Stop Loss Synchronization check: Ensure exact amount is protected
            stop_orders = [o for o in active_orders if o.get("type") == "stop" and o.get("side") == "buy"]
            needs_new_stop = False
            
            if len(stop_orders) == 0:
                needs_new_stop = True
            elif len(stop_orders) > 1:
                log("Multiple stop orders detected. Cleaning up duplicates...")
                for s_o in stop_orders[1:]:
                    cancel_order(s_o.get("order_id"))
                stop_orders = [stop_orders[0]]

            if not needs_new_stop:
                current_stop = stop_orders[0]
                stop_amt = float(current_stop.get("start_amount") or current_stop.get("remaining_amount") or 0.0)
                stop_trigger = float(current_stop.get("trigger_price", 0))
                
                # Check if stop size or level needs adjustment
                if abs(stop_amt - open_amt) > 0.0001 or abs(stop_trigger - stop_level) > 0.1:
                    log(f"Stop mismatch (Current Stop: {stop_amt:.4f} @ {stop_trigger:.1f} | Required: {open_amt:.4f} @ {stop_level:.1f}). Resynchronizing stop...")
                    cancel_order(current_stop.get("order_id"))
                    needs_new_stop = True

            if needs_new_stop:
                log(f"Placing synchronized exchange stop order: {open_amt:.4f} SOL @ {stop_level:.1f} JPY")
                place_exchange_stop(open_amt, stop_level)

            unrealized_pnl = (avg_px - last_px) * open_amt
            log(f"Active Short: {open_amt:.4f} SOL @ avg {avg_px:.1f} | Current: {last_px:.1f} | PnL: {unrealized_pnl:+.2f} JPY | Stop: {stop_level:.1f}")

            # 1. Take Profit Hit?
            if last_px <= TARGET_PRICE:
                log(f"TARGET HIT at {last_px:.1f} <= {TARGET_PRICE:.1f}! Covering position...")
                active = get_active_orders()
                for o in active:
                    cancel_order(o.get("order_id"))
                market_cover(open_amt)
                time.sleep(2)
                log("Take profit execution complete. Exiting.")
                sys.exit(0)

            # 2. Lock Profit Ratchet?
            elif last_px <= LOCK_TRIGGER and stop_level > LOCK_STOP:
                log(f"Ratcheting stop to LOCK PROFIT at {LOCK_STOP:.1f} (last px: {last_px:.1f})...")
                stop_level = LOCK_STOP

            # 3. Breakeven Ratchet?
            elif last_px <= BREAKEVEN_TRIGGER and stop_level > avg_px:
                log(f"Ratcheting stop to BREAK-EVEN at {avg_px:.1f} (last px: {last_px:.1f})...")
                stop_level = avg_px

        except Exception as e:
            log(f"Exception in management loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
