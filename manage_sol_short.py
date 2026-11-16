"""
Trade #16: Autonomous 100% Allocation Margin Short on SOL/JPY.
- Setup: Breakdown-retest short into 1h EMA resistance / 239.8 JPY upper rejection wick at 14,129.
- Entry: Maker limit short at 13,918.0 JPY (inside >470 SOL ask cluster).
- Sizing: 0.7100 SOL (100% equity allocation / 0.999x leverage, notional 9,881.78 JPY).
- Protective Stop Loss: Mandatory exchange stop order at 14,040.0 JPY (Strictly capped risk -86.62 JPY / 0.87% equity).
- Take Profit Target: 13,620.0 JPY (Target profit +211.58 JPY, 2.44:1 R:R).
- Trailing ratchet: Break-even at 13,780 JPY; lock profit at 13,680 JPY.
"""

import sys
import time
import datetime as dt
from tradingbot import bot  # noqa: F401
from tradingbot.bitbank import Bitbank, BitbankError

PAIR = "sol_jpy"
ENTRY_PRICE = 13918.0
AMOUNT = 0.7100
STOP_PRICE = 14040.0
TARGET_PRICE = 13620.0
BREAKEVEN_TRIGGER = 13780.0
LOCK_TRIGGER = 13680.0
LOCK_STOP = 13760.0

api = Bitbank()

def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_position():
    try:
        positions = api.margin_positions()
        for p in positions:
            if p.get("pair") == PAIR and p.get("position_side") == "short":
                amt = float(p.get("open_amount", 0))
                if amt > 0:
                    return amt, float(p.get("average_price", 0))
    except Exception as e:
        log(f"Error getting position: {e}")
    return 0.0, 0.0

def get_active_orders():
    try:
        res = api._get("/user/spot/active_orders", {"pair": PAIR})
        return res.get("orders", [])
    except Exception as e:
        log(f"Error getting active orders: {e}")
        return []

def place_maker_entry():
    log(f"Placing maker limit short order: {AMOUNT:.4f} SOL @ {ENTRY_PRICE:.1f} JPY")
    try:
        res = api._post("/user/spot/order", {
            "pair": PAIR,
            "amount": f"{AMOUNT:.4f}",
            "price": f"{ENTRY_PRICE:.1f}",
            "side": "sell",
            "type": "limit",
            "position_side": "short"
        })
        oid = res.get("order_id")
        log(f"Maker entry order placed successfully! Order ID: {oid}")
        return oid
    except Exception as e:
        log(f"Failed to place maker entry order: {e}")
        return None

def place_exchange_stop(amt, trigger_px):
    log(f"Placing exchange stop order: BUY {amt:.4f} SOL @ trigger {trigger_px:.1f} JPY")
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
        log(f"Failed to place exchange stop order: {e}")
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
    for attempt in range(5):
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
            log(f"Attempt {attempt+1} market cover error: {e}")
            time.sleep(1)
    return None

def main():
    log("=== SOL/JPY Autonomous Margin Short Manager Launched ===")
    
    # 1. Check existing position
    open_amt, avg_px = get_position()
    current_stop_id = None
    entry_oid = None
    
    active = get_active_orders()
    for o in active:
        if o.get("type") == "stop" and o.get("side") == "buy":
            current_stop_id = o.get("order_id")
            log(f"Detected existing stop order: {current_stop_id} at {o.get('trigger_price')}")
        elif o.get("type") == "limit" and o.get("side") == "sell":
            entry_oid = o.get("order_id")
            log(f"Detected existing entry order: {entry_oid} at {o.get('price')}")

    if open_amt == 0.0 and entry_oid is None:
        entry_oid = place_maker_entry()
        if not entry_oid:
            log("Cannot proceed without entry order. Exiting.")
            sys.exit(1)

    stop_level = STOP_PRICE

    while True:
        try:
            time.sleep(5)
            tk = api.ticker(PAIR)
            last_px = float(tk.get("last", 0))
            best_bid = float(tk.get("buy", 0))
            best_ask = float(tk.get("sell", 0))
            
            open_amt, avg_px = get_position()
            
            # Phase A: Waiting for entry fill
            if open_amt == 0.0:
                if entry_oid:
                    # check if still active
                    active = get_active_orders()
                    active_ids = [o.get("order_id") for o in active]
                    if entry_oid not in active_ids:
                        log("Entry order no longer active. Re-checking position...")
                        time.sleep(2)
                        open_amt, avg_px = get_position()
                        if open_amt == 0.0:
                            log("Entry order was cancelled or expired. Exiting.")
                            sys.exit(0)
                        else:
                            log(f"Entry order FILLED! Position: {open_amt:.4f} SOL @ avg {avg_px:.1f} JPY")
                    else:
                        log(f"Resting maker entry {entry_oid} active at {ENTRY_PRICE:.1f} JPY. Current last: {last_px:.1f} (bid: {best_bid:.1f}, ask: {best_ask:.1f})")
                        continue
                else:
                    log("No open position and no entry order. Exiting.")
                    sys.exit(0)

            # Phase B: Position is open! Ensure stop order is active
            if current_stop_id is None:
                log(f"Position active ({open_amt:.4f} SOL @ {avg_px:.1f}) but no stop order detected. Placing protective stop at {stop_level:.1f}...")
                current_stop_id = place_exchange_stop(open_amt, stop_level)
            else:
                # Verify stop order still exists
                active = get_active_orders()
                active_ids = [o.get("order_id") for o in active]
                if current_stop_id not in active_ids:
                    log(f"Stop order {current_stop_id} was triggered or closed! Checking position...")
                    time.sleep(1)
                    rem_amt, _ = get_position()
                    if rem_amt == 0.0:
                        log("Position closed via STOP LOSS. Trade concluded.")
                        sys.exit(0)
                    else:
                        log(f"Stop order vanished but position remains {rem_amt:.4f}. Replacing stop...")
                        current_stop_id = place_exchange_stop(rem_amt, stop_level)

            # Dynamic Profit Management & Trailing Ratchet
            unrealized_pnl = (avg_px - last_px) * open_amt
            log(f"Active Short: {open_amt:.4f} SOL @ {avg_px:.1f} | Current: {last_px:.1f} | PnL: {unrealized_pnl:+.2f} JPY | Stop: {stop_level:.1f}")

            # 1. Take Profit Hit?
            if last_px <= TARGET_PRICE:
                log(f"TARGET HIT at {last_px:.1f} <= {TARGET_PRICE:.1f}! Covering position...")
                if current_stop_id:
                    cancel_order(current_stop_id)
                    current_stop_id = None
                market_cover(open_amt)
                time.sleep(2)
                log("Take profit execution complete. Exiting.")
                sys.exit(0)

            # 2. Lock Profit? (Price dropped to LOCK_TRIGGER)
            elif last_px <= LOCK_TRIGGER and stop_level > LOCK_STOP:
                log(f"Ratcheting stop to LOCK PROFIT at {LOCK_STOP:.1f} (last px: {last_px:.1f})...")
                if current_stop_id:
                    cancel_order(current_stop_id)
                stop_level = LOCK_STOP
                current_stop_id = place_exchange_stop(open_amt, stop_level)

            # 3. Breakeven? (Price dropped to BREAKEVEN_TRIGGER)
            elif last_px <= BREAKEVEN_TRIGGER and stop_level > avg_px:
                log(f"Ratcheting stop to BREAK-EVEN at {avg_px:.1f} (last px: {last_px:.1f})...")
                if current_stop_id:
                    cancel_order(current_stop_id)
                stop_level = avg_px
                current_stop_id = place_exchange_stop(open_amt, stop_level)

        except Exception as e:
            log(f"Exception in management loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
