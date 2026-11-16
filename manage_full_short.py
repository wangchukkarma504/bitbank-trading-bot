import datetime as dt
import fcntl
import math
import os
import sys
import time

from tradingbot import bot  # loads .env
from tradingbot.bitbank import Bitbank, BitbankError

PAIR = "doge_jpy"
STOP_LEVEL = 11.370
TARGET_LEVEL = 11.160
TARGET_TOTAL_QTY = 868.0  # 100% allocation (~9,818 JPY notional)
MAX_HOLD = 24.0 * 3600

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
        api.cancel(PAIR, oid)
    except BitbankError as e:
        log("cancel error:", e)

def sync_stop(h, level, current_stop_id):
    cur_id, cur_qty, cur_level = get_active_stop()
    if cur_id and math.isclose(cur_qty, h, abs_tol=1e-4) and math.isclose(cur_level, level, abs_tol=1e-4):
        return cur_id
    new = None
    for attempt in range(3):
        try:
            new = api.order(PAIR, "buy", q(h), type_="stop", position_side="short", trigger_price=p(level))
            break
        except BitbankError as e:
            log("stop order placement failed:", e)
            time.sleep(1)
    if not new:
        log("CRITICAL: Failed to place stop order!")
        return cur_id
    new_id = new["order_id"]
    log(f"Protective exchange stop ARMED: {q(h)} DOGE @ {p(level)} JPY (id {new_id})")
    if cur_id and cur_id != new_id:
        cancel_order(cur_id)
    return new_id

def main():
    lock = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f".short_limit_{PAIR}.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(f"already managing {PAIR}")

    h, avg = position()
    log(f"Starting 100% short manager on {PAIR}. Current short: {q(h)} DOGE @ avg {avg}")

    cur_stop_id, _, _ = get_active_stop()
    if h > 0:
        cur_stop_id = sync_stop(h, STOP_LEVEL, cur_stop_id)

    # Calculate remaining qty needed to reach 100% allocation
    delta_qty = TARGET_TOTAL_QTY - h
    limit_oid = None
    if delta_qty >= 1.0:
        depth = api._pub(f"/{PAIR}/depth")
        best_bid = float(depth["bids"][0][0])
        best_ask = float(depth["asks"][0][0])
        # Guarantee maker order: price must be > best_bid
        entry_price = max(best_ask, round(best_bid + 0.001, PD))
        log(f"Placing MAKER limit short for remaining {q(delta_qty)} DOGE @ {p(entry_price)} JPY (best bid {best_bid}, best ask {best_ask})")
        res = api.order(PAIR, "sell", q(delta_qty), price=p(entry_price), type_="limit", position_side="short")
        limit_oid = res["order_id"]
        log(f"Maker limit order #{limit_oid} placed on book.")

    stop_level = STOP_LEVEL
    start_time = time.time()

    while True:
        try:
            now = time.time()
            px = last()
            h, avg = position()

            # Check maker limit order status
            if limit_oid:
                o = api.get_order(PAIR, limit_oid)
                if o["status"] in DONE:
                    log(f"Maker order #{limit_oid} status: {o['status']}, executed: {o.get('executed_amount')}")
                    limit_oid = None
                elif now - start_time > 4 * 3600:
                    log(f"Maker order #{limit_oid} deadline reached; cancelling unfilled balance.")
                    cancel_order(limit_oid)
                    limit_oid = None

            if h > 0:
                # Ratchet trailing stops
                if avg:
                    if px <= avg * (1 - 0.025):
                        stop_level = min(stop_level, avg * (1 - 0.012))
                    elif px <= avg * (1 - 0.015):
                        stop_level = min(stop_level, avg * (1 - 0.0024))
                cur_stop_id = sync_stop(h, stop_level, cur_stop_id)

                if px <= TARGET_LEVEL:
                    log(f"TARGET {TARGET_LEVEL} REACHED! Current price {px}. Closing short position {q(h)}.")
                    if limit_oid:
                        cancel_order(limit_oid)
                    if cur_stop_id:
                        cancel_order(cur_stop_id)
                    api.order(PAIR, "buy", q(h), type_="market", position_side="short")
                    log("Short covered successfully at target! DONE.")
                    return

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

        time.sleep(10)

if __name__ == "__main__":
    main()
