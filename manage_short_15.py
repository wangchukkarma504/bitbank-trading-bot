import datetime as dt
import fcntl
import math
import os
import sys
import time

from tradingbot import bot  # loads .env
from tradingbot.bitbank import Bitbank, BitbankError

PAIR = "doge_jpy"
ENTRY_PRICE = 10.995
STOP_LEVEL = 11.050
TARGET_LEVEL = 10.820
TARGET_TOTAL_QTY = 906.0  # 100% allocation (~9,961 JPY notional)
MAX_HOLD = 24.0 * 3600
ORDER_TIMEOUT = 2.0 * 3600

api = Bitbank()
info = api.pair_info(PAIR)
PD, AD = int(info["price_digits"]), int(info["amount_digits"])
DONE = ("FULLY_FILLED", "CANCELED_UNFILLED", "CANCELED_PARTIALLY_FILLED", "REJECTED")

def p(x):
    return f"{x:.{PD}f}"

def q(x):
    return f"{math.floor(x * 10 ** AD + 1e-9) / 10 ** AD:.{AD}f}"

def log(*a):
    print(dt.datetime.now().isoformat(timespec="seconds"), *a, flush=True)

def last():
    return float(api.ticker(PAIR)["last"])

def position():
    for x in api.margin_positions():
        if x["pair"] == PAIR and x["position_side"] == "short":
            return float(x["open_amount"]), float(x["average_price"] or 0)
    return 0.0, 0.0

def get_active_stop():
    orders = api._get("/user/spot/active_orders", {"pair": PAIR})["orders"]
    for o in orders:
        if o.get("position_side") == "short" and o.get("type") == "stop" and o.get("side") == "buy":
            return o["order_id"], float(o["start_amount"]), float(o.get("trigger_price") or 0)
    return None, 0.0, 0.0

def cancel_order(oid):
    try:
        api.cancel_order(PAIR, oid)
        log(f"Cancelled order {oid}")
        return True
    except BitbankError as e:
        log(f"Cancel order {oid} error: {e}")
        return False

def sync_stop(hold_amount, stop_price, current_stop_id):
    if hold_amount <= 0:
        if current_stop_id:
            cancel_order(current_stop_id)
        return None

    # Check if existing stop already covers this quantity and price
    if current_stop_id:
        try:
            o = api.get_order(PAIR, current_stop_id)
            cur_amt = float(o.get("start_amount", 0))
            cur_trig = float(o.get("trigger_price", 0))
            if o.get("status") not in DONE and abs(cur_amt - hold_amount) < 1e-4 and abs(cur_trig - stop_price) < 1e-4:
                return current_stop_id
        except Exception:
            pass

    # Place new protective stop on exchange first
    new_id = None
    try:
        res = api.order(PAIR, "buy", q(hold_amount), type_="stop",
                        trigger_price=p(stop_price), position_side="short")
        new_id = res.get("order_id")
        log(f"Protective exchange stop ARMED: {q(hold_amount)} DOGE @ {p(stop_price)} JPY (id {new_id})")
    except Exception as e:
        log("Failed to place protective exchange stop:", e)
        return current_stop_id

    # Safely cancel old stop now that new stop is armed
    if current_stop_id and new_id:
        cancel_order(current_stop_id)

    return new_id

def main():
    lock_file = f"/tmp/.short_limit_{PAIR}_trade15.lock"
    f = open(lock_file, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        log(f"Another instance is running for {PAIR} (lock {lock_file}). Exiting.")
        return

    log(f"Starting Trade #15 100% short manager on {PAIR}.")
    h, avg = position()
    cur_stop_id, _, _ = get_active_stop()

    # Check if we already have an active resting maker limit order on book
    limit_oid = None
    try:
        active_orders = api._get("/user/spot/active_orders", {"pair": PAIR})["orders"]
        for o in active_orders:
            if o.get("side") == "sell" and o.get("type") == "limit" and o.get("position_side") == "short":
                limit_oid = o["order_id"]
                log(f"Re-attaching to existing resting maker limit order #{limit_oid} on book.")
                break
    except Exception as e:
        log("Error checking active orders:", e)

    if not limit_oid and h < TARGET_TOTAL_QTY:
        depth = api._pub(f"/{PAIR}/depth")
        best_bid = float(depth["bids"][0][0])
        best_ask = float(depth["asks"][0][0])
        limit_price = max(ENTRY_PRICE, best_bid + 0.001)

        delta_qty = TARGET_TOTAL_QTY - h
        log(f"Placing MAKER limit short for {q(delta_qty)} DOGE @ {p(limit_price)} JPY (best bid {best_bid}, best ask {best_ask})")
        try:
            res = api.order(PAIR, "sell", q(delta_qty), price=p(limit_price),
                            type_="limit", position_side="short")
            limit_oid = res.get("order_id")
            log(f"Maker limit order #{limit_oid} placed on book.")
        except Exception as e:
            log("Failed to place initial maker order:", e)
            return

    start_time = time.time()
    filled_prev = 0.0

    while True:
        try:
            now = time.time()
            px = last()
            h, avg = position()

            # Check maker limit order status
            if limit_oid:
                try:
                    info_ord = api.get_order(PAIR, limit_oid)
                    st = info_ord.get("status")
                    exec_amt = float(info_ord.get("executed_amount", 0))

                    if exec_amt > filled_prev:
                        filled_prev = exec_amt
                        log(f"Maker order #{limit_oid} partial/full fill: {q(exec_amt)} DOGE")
                        cur_stop_id = sync_stop(h, STOP_LEVEL, cur_stop_id)

                    if st in DONE:
                        log(f"Maker order #{limit_oid} finished: {st}, executed: {exec_amt}")
                        limit_oid = None
                except Exception as e:
                    log(f"Error checking limit order #{limit_oid}:", e)

            # Check order timeout if unfilled
            if limit_oid and h <= 0 and (now - start_time > ORDER_TIMEOUT):
                log("Order timeout reached without fill. Cancelling maker order.")
                cancel_order(limit_oid)
                limit_oid = None
                return

            # Cancel if price breaks down hard before getting filled
            if limit_oid and h <= 0 and px < 10.880:
                log(f"Price broke down to {px} without fill. Cancelling limit order #{limit_oid} to avoid chasing.")
                cancel_order(limit_oid)
                limit_oid = None
                return

            # Active position management
            if h > 0:
                stop_level = STOP_LEVEL
                # Ratchet 1: price <= 10.900 JPY
                if px <= 10.900:
                    stop_level = min(stop_level, avg * 0.998)
                # Ratchet 2: price <= 10.840 JPY
                if px <= 10.840:
                    stop_level = min(stop_level, avg * 0.993)

                cur_stop_id = sync_stop(h, stop_level, cur_stop_id)

                # Target reached: take profit!
                if px <= TARGET_LEVEL:
                    log(f"TARGET {TARGET_LEVEL} REACHED! Current price {px}. Closing short position {q(h)}.")
                    if limit_oid:
                        cancel_order(limit_oid)
                    if cur_stop_id:
                        cancel_order(cur_stop_id)
                    api.order(PAIR, "buy", q(h), type_="market", position_side="short")
                    log("Short covered successfully at target! DONE.")
                    return

                # Max hold expiration
                if now - start_time > MAX_HOLD:
                    log(f"Max hold time reached. Closing short position {q(h)}.")
                    if limit_oid:
                        cancel_order(limit_oid)
                    if cur_stop_id:
                        cancel_order(cur_stop_id)
                    api.order(PAIR, "buy", q(h), type_="market", position_side="short")
                    log("Short covered on max hold. DONE.")
                    return
            else:
                if not limit_oid:
                    log("Position closed and no active orders. Manager finished.")
                    return
        except SystemExit:
            raise
        except Exception as e:
            log("Supervisor loop error:", e)

        time.sleep(5)

if __name__ == "__main__":
    main()
