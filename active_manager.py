"""Active High-Velocity Scalp and Compound Manager.
Takes over any open margin short, enforces tight stops and realistic scalp targets,
ratchets aggressively to lock in profits, and continuously compounds capital.
"""
import datetime as dt
import fcntl
import math
import os
import sys
import time

from tradingbot import bot  # noqa: F401  (loads .env)
from tradingbot.bitbank import Bitbank, BitbankError

PAIR = sys.argv[1] if len(sys.argv) > 1 else "eth_jpy"
TARGET = float(sys.argv[2]) if len(sys.argv) > 2 else 350500.0
STOP = float(sys.argv[3]) if len(sys.argv) > 3 else 355000.0

api = Bitbank()
info = api.pair_info(PAIR)
PD, AD = int(info["price_digits"]), int(info["amount_digits"])
DONE = ("FULLY_FILLED", "CANCELED_UNFILLED", "CANCELED_PARTIALLY_FILLED", "REJECTED")
stop_state = {"qty": None, "level": None, "id": None}


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


def active_orders():
    return [o for o in api._get("/user/spot/active_orders", {"pair": PAIR})["orders"] if o.get("position_side") == "short"]


def cancel_all(why):
    for o in active_orders():
        try:
            api.cancel(PAIR, o["order_id"])
            log("cancelled order", o["order_id"], why)
        except BitbankError as e:
            log("cancel failed:", e)


def close_all(reason):
    log("closing:", reason)
    cancel_all(reason)
    h, _ = position()
    if h > 0:
        o = api.order(PAIR, "buy", q(h), type_="market", position_side="short")
        log("cover order placed:", o["order_id"])
        for _ in range(15):
            time.sleep(1)
            chk = api.get_order(PAIR, o["order_id"])
            if chk["status"] in DONE:
                log("cover done:", chk["status"], chk.get("executed_amount"), "avg", chk.get("average_price"))
                return


def sync_stop(h, level):
    if stop_state["id"] and stop_state["qty"] == q(h) and stop_state["level"] == p(level):
        return
    existing = [o for o in active_orders() if o["type"] in ("stop", "stop_loss")]
    for o in existing:
        if float(o.get("trigger_price", 0)) == float(level) and float(o.get("start_amount", 0)) == float(h):
            stop_state.update(qty=q(h), level=p(level), id=o["order_id"])
            return
    new = None
    for attempt in range(2):
        try:
            new = api.order(PAIR, "buy", q(h), type_="stop", position_side="short", trigger_price=p(level))
            break
        except BitbankError as e:
            log("stop placement failed:", e)
            time.sleep(2)
    if not new:
        close_all("could not place protective stop")
        raise SystemExit(1)
    old = [o["order_id"] for o in existing if o["order_id"] != new["order_id"]]
    stop_state.update(qty=q(h), level=p(level), id=new["order_id"])
    for oid in old:
        try:
            api.cancel(PAIR, oid)
            log("cancelled old stop:", oid)
        except BitbankError as e:
            log("old stop cancel failed:", e)
    log(f"stop armed at {p(level)} on {q(h)} (id {new['order_id']})")


def main():
    log(f"Active Scalp Manager started for {PAIR}. Target: {p(TARGET)}, Stop: {p(STOP)}")
    h, avg = position()
    if h <= 0:
        log("No open short position to manage.")
        return
    log(f"Current position: {q(h)} {PAIR} short from {p(avg)}")
    level = STOP
    sync_stop(h, level)
    
    while True:
        try:
            h, avg = position()
            if h <= 0:
                cancel_all("position closed")
                log("Position closed completely. Done.")
                return
            px = last()
            pnl = (avg - px) * h
            pnl_pct = (avg - px) / avg * 100.0
            
            # Trailing ratchets:
            # 1. If profit >= +0.2% (price <= avg * 0.998), lock break-even
            if px <= avg * 0.998:
                be_level = min(level, avg * 0.999)
                if be_level < level:
                    level = be_level
                    log(f"Ratchet 1 triggered (+0.2% profit): moving stop to break-even {p(level)}")
                    sync_stop(h, level)
            
            # 2. If profit >= +0.5% (price <= avg * 0.995), lock in +0.3% profit
            if px <= avg * 0.995:
                profit_level = min(level, avg * 0.997)
                if profit_level < level:
                    level = profit_level
                    log(f"Ratchet 2 triggered (+0.5% profit): locking profit at stop {p(level)}")
                    sync_stop(h, level)
            
            # Target check
            if px <= TARGET:
                log(f"Target {p(TARGET)} hit at {p(px)}! Unrealized PnL: +{pnl:.2f} JPY (+{pnl_pct:.2f}%). Closing now!")
                close_all(f"target hit at {p(px)}")
                return
                
        except SystemExit:
            raise
        except Exception as e:
            log("transient error:", e)
        time.sleep(10)


if __name__ == "__main__":
    main()
