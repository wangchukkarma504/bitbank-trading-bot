"""Live/paper trading loop for Bitbank spot.

LIVE=1 sends real orders; otherwise paper-trades against live prices.
"""
import datetime as dt
import json
import logging
import math
import os
import time

from .bitbank import Bitbank
from .strategy import Params, Signals


def load_env(path):
    """Load KEY=VALUE lines from a .env file without overriding real env vars."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass


load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

PAIRS = os.environ.get("PAIRS", "btc_jpy,eth_jpy,doge_jpy").split(",")
LIVE = os.environ.get("LIVE") == "1"
STATE = os.environ.get("STATE_FILE", os.path.join(os.environ.get("STATE_DIR", "."), "state.json") if LIVE else "state_paper.json")
PAPER_CASH = float(os.environ.get("PAPER_CASH", "10000"))
POLL = 60
PAIR_ALLOC = 0.3          # max fraction of equity per pair
KILL_DD = 0.5             # liquidate & halt if equity < 50% of starting equity
DAILY_LOSS = 0.07         # no new entries if down 7% on the day
P = Params(fast=30, slow=90, trend=200, stop_atr=4.0)
TF_SEC = 4 * 3600
PAPER_FEE = 0.0012

log = logging.getLogger("bot")


def rd(x, digits=4):
    f = 10 ** digits
    return math.floor(x * f + 1e-9) / f


class Bot:
    def __init__(self):
        self.api = Bitbank()
        self.st = self.load()
        self.info = {p: self.api.pair_info(p) for p in PAIRS}
        self.last_candle = {}

    # ---- state ----
    def load(self):
        if os.path.exists(STATE):
            return json.load(open(STATE))
        return {"pos": {}, "cash": PAPER_CASH, "start_equity": None, "day": None, "day_equity": None,
                "halted": False, "trades": []}

    def save(self):
        json.dump(self.st, open(STATE + ".tmp", "w"), indent=1)
        os.replace(STATE + ".tmp", STATE)

    # ---- helpers ----
    def prices(self):
        return {p: float(self.api.ticker(p)["last"]) for p in PAIRS}

    def free_jpy(self):
        return self.api.assets().get("jpy", 0.0) if LIVE else self.st["cash"]

    def total_jpy(self):
        """JPY including margin collateral/open-order locks, so a margin trade can't fake a loss."""
        return self.api.assets_onhand().get("jpy", 0.0) if LIVE else self.st["cash"]

    def equity(self, px):
        return self.total_jpy() + sum(v["qty"] * px[p] for p, v in self.st["pos"].items())

    def candles(self, pair):
        now = dt.datetime.now(dt.timezone.utc)
        rows = []
        for y in (now.year - 1, now.year):
            for o, h, l, c, v, ts in self.api.candles(pair, "4hour", str(y)):
                rows.append((int(ts), float(o), float(h), float(l), float(c), float(v)))
        rows.sort()
        # drop the still-forming candle
        if rows and rows[-1][0] / 1000 + TF_SEC > time.time():
            rows.pop()
        return rows

    def btc_uptrend(self):
        """Market regime gate (backtested 2020+): non-BTC entries only while BTC trades above its 4h EMA200."""
        try:
            sg = Signals(self.candles("btc_jpy"), P)
            return sg.c[-1] > sg.t[-1]
        except Exception:
            log.exception("regime check failed; blocking non-BTC entries this step")
            return False

    def trade(self, pair, side, qty, px_hint):
        base = pair.split("_")[0]
        if LIVE:
            o = self.api.order(pair, side, f"{qty:.4f}", type_="market")
            oid = o["order_id"]
            for _ in range(10):
                time.sleep(1)
                o = self.api.get_order(pair, oid)
                if o["status"] in ("FULLY_FILLED", "PARTIALLY_FILLED", "CANCELED_UNFILLED", "CANCELED_PARTIALLY_FILLED"):
                    break
            fq, fp = float(o["executed_amount"]), float(o["average_price"] or 0)
            if fq <= 0:
                raise RuntimeError(f"order not filled: {o}")
            return fq, fp
        fp = px_hint * (1.0005 if side == "buy" else 0.9995)
        fee = qty * fp * PAPER_FEE
        self.st["cash"] += (-qty * fp - fee) if side == "buy" else (qty * fp - fee)
        return qty, fp

    def buy(self, pair, px, equity):
        unit = float(self.info[pair]["unit_amount"])
        budget = min(equity * PAIR_ALLOC, self.free_jpy() * 0.98)
        qty = rd(budget / px)
        if qty < unit:
            log.info("%s: budget too small for min order", pair)
            return
        fq, fp = self.trade(pair, "buy", qty, px)
        # fee on buys is taken from the base asset in some cases; use actual balance when live
        if LIVE:
            fq = min(fq, rd(self.api.assets().get(pair.split("_")[0], fq)))
        self.st["pos"][pair] = {"qty": fq, "entry": fp, "hi": px, "ts": time.time()}
        self.log_trade(pair, "buy", fq, fp)

    def sell(self, pair, px, why):
        pos = self.st["pos"][pair]
        qty = pos["qty"]
        if LIVE:
            qty = min(qty, rd(self.api.assets().get(pair.split("_")[0], qty)))
        fq, fp = self.trade(pair, "sell", qty, px)
        self.log_trade(pair, "sell", fq, fp, why, pnl=fp / pos["entry"] - 1)
        left = pos["qty"] - fq
        if left * px >= float(self.info[pair]["unit_amount"]) * px and left >= float(self.info[pair]["unit_amount"]):
            pos["qty"] = left
        else:
            del self.st["pos"][pair]

    def log_trade(self, pair, side, qty, px, why="", pnl=None):
        rec = {"t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "pair": pair, "side": side,
               "qty": qty, "px": px, "why": why, "pnl": pnl}
        self.st["trades"].append(rec)
        log.info("TRADE %s", rec)
        self.save()

    # ---- main step ----
    def step(self):
        px = self.prices()
        eq = self.equity(px)
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        if self.st["start_equity"] is None:
            self.st["start_equity"] = eq
        if self.st["day"] != today:
            self.st["day"], self.st["day_equity"] = today, eq
        if self.st["halted"]:
            return
        if eq < self.st["start_equity"] * KILL_DD:
            log.error("KILL SWITCH: equity %.0f < %.0f%% of start. Liquidating.", eq, KILL_DD * 100)
            for p in list(self.st["pos"]):
                self.sell(p, px[p], "kill")
            self.st["halted"] = True
            self.save()
            return
        can_enter = eq > self.st["day_equity"] * (1 - DAILY_LOSS)
        btc_up = self.btc_uptrend()

        for pair in PAIRS:
            c = self.candles(pair)
            if len(c) < P.trend + 5:
                continue
            sg = Signals(c, P)
            i = len(c) - 1
            new_candle = self.last_candle.get(pair) != c[-1][0]
            pos = self.st["pos"].get(pair)
            if pos:
                pos["hi"] = max(pos["hi"], px[pair], c[-1][2] if c[-1][0] / 1000 > pos["ts"] else 0)
                stop = sg.stop_level(i, pos["hi"])
                if px[pair] < stop:
                    self.sell(pair, px[pair], f"stop {stop:.0f}")
                elif new_candle and sg.exit_trend(i):
                    self.sell(pair, px[pair], "trend exit")
            elif new_candle and can_enter and (pair == "btc_jpy" or btc_up) and sg.entry(i):
                self.buy(pair, px[pair], eq)
            self.last_candle[pair] = c[-1][0]
        self.save()
        log.info("equity %.0f (start %.0f) pos=%s", eq, self.st["start_equity"],
                 {p: round(v["qty"], 4) for p, v in self.st["pos"].items()})

    def run(self):
        log.info("starting in %s mode, pairs=%s", "LIVE" if LIVE else "PAPER", PAIRS)
        while True:
            try:
                self.step()
            except Exception:
                log.exception("step failed")
            if self.st["halted"]:
                log.error("halted; exiting")
                return
            time.sleep(POLL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")])
    Bot().run()
