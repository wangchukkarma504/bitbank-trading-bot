"""Live trading engine for the rule in strategy.py.

One tick does four things, in this order:

  1. read the account (never act on stale data: a failed read ends the tick);
  2. finish entries in progress (a resting maker buy that timed out is completed at market);
  3. make sure every open margin position has an exchange stop of the right size, and move the stop of
     the bot's own positions up behind the price (it never moves down);
  4. once per closed 4h candle, read the candles and buy the coins that broke out, if there is room.

Positions the bot did not open (manual trades) are never managed or closed; they only get a protective
stop if they have none. Orders the bot did not place are never cancelled, except a closing stop that
is left without a position.
"""

import calendar
from dataclasses import dataclass
import json
import logging
import math
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from tradingbot import strategy
from tradingbot.bitbank import Bitbank
from tradingbot.strategy import BAR_MS, FEE_TAKER, Bar, Params, Snapshot

logger = logging.getLogger("Engine")

PAIRS: Dict[str, Tuple[int, int]] = {      # pair -> (price digits, amount digits)
    "btc_jpy": (0, 4), "eth_jpy": (0, 4), "xrp_jpy": (3, 4), "sol_jpy": (1, 4), "doge_jpy": (3, 4),
}
MIN_AMOUNT = 0.0001
MIN_NOTIONAL_JPY = 500.0
ACTIVE = ("UNFILLED", "INACTIVE", "PARTIALLY_FILLED")

# Bitbank error codes (github.com/bitbankinc/bitbank-api-docs, errors.md)
ORDER_GONE = (50009, 50026, 50027)       # order not found, already cancelled, already executed
STOP_CONFLICT = (50062, 60001, 60011)    # exceeds the position, insufficient amount, too many orders: the
                                         # stop already resting is in the way, so cancelling it first can help
BAD_TRIGGER = (40112, 60016)             # this trigger price is not accepted
NO_VERDICT = (10001, 10003, 10005, 70001, 70002, 70003, 70012)   # system error or timeout: the order may
                                         # have been taken all the same
# 60018 (the stop would trigger at once) needs nothing of its own: the next tick finds the price at the stop
# level and closes the position at market. Every other code (rate limit 1xxxx, account restrictions 5xxxx,
# suspensions 7xxxx) and every transport error leaves the stop that is in place alone.


def _error_code(e: Exception) -> Optional[int]:
    m = re.search(r"'code':\s*(\d+)", str(e))
    return int(m.group(1)) if m else None


def fmt_price(pair: str, price: float) -> str:
    digits = PAIRS[pair][0]
    return f"{price:.{digits}f}" if digits > 0 else str(int(round(price)))


def fmt_amount(pair: str, amount: float) -> str:
    return f"{amount:.{PAIRS[pair][1]}f}"


def floor_amount(pair: str, amount: float) -> float:
    scale = 10 ** PAIRS[pair][1]
    return math.floor(amount * scale + 1e-9) / scale


def _remaining(order: Dict[str, Any]) -> float:
    return float(order.get("remaining_amount") or order.get("start_amount") or 0.0)


def write_atomic(path: str, text: str) -> None:
    """Write a file so that a crash leaves either the old or the new version, never half of one."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class Settings:
    """Operator settings (bot_config.json)."""
    baseline_jpy: float = 20000.0
    equity_floor_jpy: Optional[float] = None    # at or below this equity the bot opens nothing new
    capital_limit_jpy: Optional[float] = None   # size positions as if equity were at most this
    manual_stop_pct: float = 0.012              # protective stop for positions the bot did not open


@dataclass
class Position:
    """A margin position as the exchange reports it."""
    pair: str
    side: str        # "long" or "short"
    amount: float
    avg: float
    last: float

    @property
    def upnl(self) -> float:
        return self.amount * ((self.last - self.avg) if self.side == "long" else (self.avg - self.last))


@dataclass
class Account:
    equity: float
    free_jpy: float
    positions: Dict[Tuple[str, str], Position]
    orders: List[Dict[str, Any]]
    prices: Dict[str, Dict[str, float]]     # pair -> {"last", "bid", "ask"}


class Engine:
    TICK_INTERVAL_SEC = 20.0
    ENTRY_WINDOW_SEC = 1800.0    # a 4h close is acted on only this long after it; later it is just displayed
    BAR_SETTLE_SEC = 20.0        # wait this long after a 4h close for the exchange to publish the candle
    TRAIL_STEP = 0.003           # move the exchange stop when it improves by at least 0.3% of the price
    MAX_STOP_FAILURES = 3        # consecutive ticks a position may stay without a stop before it is closed
    STOP_RETRY_SEC = 300.0       # after the exchange refuses a stop level, wait this long before asking again
    FILL_GRACE_SEC = 120.0       # how long a finished entry may take to show up as a position

    def __init__(self, client: Optional[Any] = None, mode: str = "dry-run", settings: Optional[Settings] = None,
                 params: Optional[Params] = None, state_path: Optional[str] = "bot_state.json",
                 journal_path: Optional[str] = "trade_journal.json", clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        self.client = client if client is not None else Bitbank()
        self.mode = mode.lower()
        self.dry_run = self.mode == "dry-run"
        self.settings = settings or Settings()
        self.params = params or Params()
        self.state_path = state_path
        self.journal_path = journal_path
        self.clock = clock
        self.sleep = sleep
        self.entries_enabled = True
        self.lock = threading.RLock()    # held during every step; the server takes it for the operator's actions
        self.epoch = 0                   # raised by the server when the operator changes orders or positions
        self._tick_epoch = 0
        self.tick_count = 0
        self.floor_hit = False
        self.account: Optional[Account] = None
        self.snapshots: Dict[str, Snapshot] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}   # the bot's own longs, by pair
        self.entries: Dict[str, Dict[str, Any]] = {}     # entries in progress, by pair
        self.journal: List[Dict[str, Any]] = []
        self._bar_seen: Dict[str, int] = {}
        self._naked_seen: Dict[Tuple[str, str], int] = {}
        self._orphan_seen: set = set()
        self._stop_refusals: Dict[str, int] = {}     # consecutive refusals of a replacement stop, by pair
        self._naked_ticks: Dict[str, int] = {}       # consecutive ticks a bot position had no stop, by pair
        self._stop_retry_at: Dict[str, float] = {}
        self._gone_ticks: Dict[str, int] = {}        # consecutive readings without the position, by pair
        self.last_step_error: Optional[str] = None
        self._logged_step_error: Optional[str] = None
        self._year_rows: Dict[Tuple[str, str], List[list]] = {}
        self._saved = ""
        self._load()
        # positions seen on the last good reading; one that goes missing is asked for again before anything acts
        self._last_held = {(p, "long") for p, m in self.positions.items() if m.get("amount")}

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        if self.state_path and os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.positions = {k: v for k, v in (data.get("positions") or {}).items() if k in PAIRS}
                self.entries = {k: v for k, v in (data.get("entries") or {}).items() if k in PAIRS}
            except Exception as e:
                logger.warning(f"Could not load {self.state_path}: {e}")
        if self.journal_path and os.path.exists(self.journal_path):
            try:
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    self.journal = list(json.load(f))
            except Exception as e:
                logger.warning(f"Could not load {self.journal_path}: {e}")

    def _save(self) -> None:
        if not self.state_path:
            return
        blob = json.dumps({"positions": self.positions, "entries": self.entries}, indent=1, sort_keys=True)
        if blob == self._saved:
            return
        try:
            write_atomic(self.state_path, blob)
            self._saved = blob
        except Exception as e:
            logger.warning(f"Could not save {self.state_path}: {e}")

    def _save_journal(self) -> None:
        if not self.journal_path:
            return
        try:
            write_atomic(self.journal_path, json.dumps(self.journal, indent=1))
        except Exception as e:
            logger.warning(f"Could not save {self.journal_path}: {e}")

    # ------------------------------------------------------------------ the tick

    def tick(self) -> Dict[str, Any]:
        self.tick_count += 1
        self._tick_epoch = self.epoch
        acct = self.read_account()
        if self._last_held - set(acct.positions):
            # A position that was there on the last reading is missing from this one. Ask once more before
            # anything acts on that: one bad reading must not cost a position its record or its stop.
            fresh = self._read_positions(acct.prices)
            acct.equity += sum(p.upnl for p in fresh.values()) - sum(p.upnl for p in acct.positions.values())
            acct.positions = fresh
        self.account = acct
        self.last_step_error = None
        floor = self.settings.equity_floor_jpy
        self.floor_hit = bool(floor and 0 < acct.equity <= floor)
        if not self.dry_run:
            # Every step is isolated: a failure in one of them (or on one coin) must never keep the others,
            # above all the stops, from running on this tick.
            for pair in list(self.entries):
                self._step(f"entry on {pair}", self._work_entry, pair, acct)
            closed = self._step("closed trades", self._close_finished, acct) or set()
            for pos in list(acct.positions.values()):
                self._step(f"stop on {pos.pair}", self._protect, pos, acct)
            self._step("leftover stops", self._cancel_orphan_stops, acct, closed)
        self._step("signals", self._read_signals, acct)
        self._last_held = set(acct.positions)
        self._save()
        return {"equity_jpy": acct.equity}

    def _step(self, name: str, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            with self.lock:
                if self._tick_epoch != self.epoch:
                    return None        # the operator acted after this tick read the account: wait for a fresh reading
                try:
                    return fn(*args)
                finally:
                    self._save()       # a restart right after this step must not lose what it did
        except Exception as e:
            self.last_step_error = f"{name}: {type(e).__name__}: {e}"
            if self.last_step_error != self._logged_step_error:      # log a repeating failure once
                self._logged_step_error = self.last_step_error
                logger.error(f"Engine step failed ({self.last_step_error})", exc_info=True)
            return None

    def read_account(self) -> Account:
        c = self.client
        prices: Dict[str, Dict[str, float]] = {}
        for pair in PAIRS:
            t = c.ticker(pair)
            prices[pair] = {"last": float(t["last"]), "bid": float(t.get("buy") or t["last"]),
                            "ask": float(t.get("sell") or t["last"])}
        jpy = free = crypto = 0.0
        for a in c._get("/user/assets").get("assets", []):
            onhand = float(a.get("onhand_amount") or 0.0) or (
                float(a.get("free_amount") or 0.0) + float(a.get("locked_amount") or 0.0))
            if a.get("asset") == "jpy":
                jpy, free = onhand, float(a.get("free_amount") or 0.0)
            elif f"{a.get('asset')}_jpy" in prices:
                crypto += onhand * prices[f"{a.get('asset')}_jpy"]["last"]
        positions = self._read_positions(prices)
        orders = [o for o in c._get("/user/spot/active_orders").get("orders", [])
                  if o.get("pair") in PAIRS and o.get("status") in ACTIVE]
        equity = jpy + crypto + sum(p.upnl for p in positions.values())
        return Account(equity, free, positions, orders, prices)

    def _read_positions(self, prices: Dict[str, Dict[str, float]]) -> Dict[Tuple[str, str], Position]:
        out: Dict[Tuple[str, str], Position] = {}
        for p in self.client.margin_positions():
            amount = float(p.get("open_amount") or 0.0)
            pair, side = p.get("pair"), p.get("position_side")
            if amount >= MIN_AMOUNT / 2 and pair in PAIRS and side in ("long", "short"):
                out[(pair, side)] = Position(pair, side, amount, float(p.get("average_price") or 0.0),
                                             prices[pair]["last"])
        return out

    # ------------------------------------------------------------------ entries

    def _read_signals(self, acct: Account) -> None:
        now_ms = int(self.clock() * 1000)
        bar_ts = now_ms // BAR_MS * BAR_MS                    # close time of the newest closed 4h candle
        if now_ms - bar_ts < self.BAR_SETTLE_SEC * 1000:
            return
        todo = [p for p in PAIRS if self._bar_seen.get(p) != bar_ts]
        if not todo:
            return
        fresh = now_ms - bar_ts <= self.ENTRY_WINDOW_SEC * 1000
        found: List[Tuple[float, str, Snapshot]] = []
        for pair in todo:
            try:
                s = self._bar_snapshot(pair, now_ms)
            except Exception as e:
                logger.warning(f"Could not read 4h candles for {pair}: {e}")
                s = None
            if s is not None:
                self.snapshots[pair] = s
            if s is None or s.ts != bar_ts:
                if not fresh:
                    self._bar_seen[pair] = bar_ts      # too late to act on anyway: stop asking
                continue                               # the new candle is not published yet: ask again next tick
            self._bar_seen[pair] = bar_ts
            if fresh and strategy.signal(s, self.params):
                found.append((-s.momentum, pair, s))
        if not found:
            return
        names = ", ".join(pair for _, pair, _ in sorted(found))
        if self.dry_run:
            logger.info(f"[dry-run] breakout on {names}: no orders are placed in dry-run mode")
            return
        if not self.entries_enabled or self.floor_hit:
            logger.warning(f"Breakout on {names} not traded: "
                           + ("equity is at the floor" if self.floor_hit else "new entries are switched off"))
            return
        busy = {k[0] for k in acct.positions} | set(self.entries) | set(self.positions)
        room = self.params.max_positions - len(busy)
        for _, pair, s in sorted(found):
            if pair in busy:
                continue
            if room <= 0:
                logger.info(f"Breakout on {pair} skipped: already holding {self.params.max_positions} positions")
                continue
            if self._enter(pair, s, acct):
                room -= 1

    def _bar_snapshot(self, pair: str, now_ms: int) -> Optional[Snapshot]:
        """Snapshot of the newest closed 4h candle, from this year's and last year's candles. A candle counts
        as closed only once the exchange has opened the next one, so a fast local clock cannot make the bot
        act on a candle that is still forming."""
        year = time.gmtime(now_ms / 1000).tm_year
        rows: List[list] = list(self.client.candles(pair, "4hour", str(year)))
        key = (pair, str(year - 1))
        prev = self._year_rows.get(key)
        if prev is None:
            try:
                prev = list(self.client.candles(pair, "4hour", str(year - 1)))
            except Exception:
                prev = []                              # read again next time (a pair listed this year has no file)
            # The file of a finished year is kept only once it can no longer change. In the first hours of a
            # year it is read every time: its last candle has only just closed.
            if prev and now_ms >= calendar.timegm((year, 1, 1, 6, 0, 0)) * 1000:
                self._year_rows = {k: v for k, v in self._year_rows.items() if k[0] != pair}
                self._year_rows[key] = prev
        rows = prev + rows
        if not rows:
            return None
        newest = max(int(r[5]) for r in rows)
        bars: List[Bar] = sorted({int(r[5]): (int(r[5]), float(r[0]), float(r[1]), float(r[2]), float(r[3]))
                                  for r in rows if int(r[5]) < newest and int(r[5]) + BAR_MS <= now_ms}.values())
        snaps = strategy.snapshots(bars, self.params)
        return snaps[-1] if snaps else None

    def _enter(self, pair: str, s: Snapshot, acct: Account) -> bool:
        p = self.params
        plan = strategy.make_plan(s, p)
        px = acct.prices[pair]
        if px["last"] <= plan.stop or px["last"] > plan.entry * (1.0 + plan.dist):
            logger.warning(f"Breakout on {pair} skipped: price {px['last']} has left the plan "
                           f"(signal {plan.entry:g}, stop {plan.stop:g})")
            return False
        equity = acct.equity
        if self.settings.capital_limit_jpy:
            equity = min(equity, self.settings.capital_limit_jpy)
        amount = floor_amount(pair, strategy.notional_share(plan.dist, p) * equity / px["last"])
        if amount < MIN_AMOUNT or amount * px["last"] < MIN_NOTIONAL_JPY:
            logger.warning(f"Breakout on {pair} skipped: position of {amount} is below the exchange minimum")
            return False
        limit = min(plan.entry, px["bid"])
        order_id, unconfirmed = None, False
        try:
            res = self.client.order(pair, "buy", amount=fmt_amount(pair, amount), price=fmt_price(pair, limit),
                                    type_="limit", post_only=True, position_side="long")
            if res.get("status") in ACTIVE + ("FULLY_FILLED",):
                order_id = res.get("order_id")
        except Exception as e:
            # A refusal with an error code means the exchange did not take the order. With no answer at all,
            # or only a system error or a timeout, it may be resting all the same.
            code = _error_code(e)
            unconfirmed = code is None or code in NO_VERDICT
            logger.warning(f"Maker buy on {pair} was not confirmed ({e}); buying at market instead")
        now = self.clock()
        self.entries[pair] = {"order_id": order_id, "amount": amount, "stop": plan.stop, "unconfirmed": unconfirmed,
                              "placed_ts": now if order_id is not None else now - p.maker_wait_sec}
        self.positions[pair] = {"signal_ts": s.ts, "entry_ts": int(now * 1000), "entry": plan.entry,
                                "dist": plan.dist, "plan_stop": plan.stop, "stop": plan.stop, "stop_id": None,
                                "best": 0.0, "amount": 0.0, "risk_jpy": amount * px["last"] * plan.dist,
                                "equity_at_entry": acct.equity}
        logger.warning(f"BUY {pair}: breakout above {s.channel_high:g} (4h close {s.close:g}). "
                       f"{fmt_amount(pair, amount)} at {fmt_price(pair, limit)} resting for "
                       f"{p.maker_wait_sec // 60} min, stop {fmt_price(pair, plan.stop)} "
                       f"({plan.dist * 100:.1f}% away), about {amount * px['last'] * plan.dist:,.0f} JPY at risk")
        return True

    def _work_entry(self, pair: str, acct: Account) -> None:
        """Complete an entry whose maker order has been filled, has timed out, or was never confirmed."""
        now = self.clock()
        e = self.entries.get(pair)
        if e is None:
            return                                     # dropped by the operator a moment ago
        go = self.entries_enabled                      # off (pause, emergency stop): finish without buying more
        executed = 0.0
        if e.get("unconfirmed"):
            # There was no answer to the maker order, so it may be resting, or filled already, or it never
            # arrived. On the book: adopt it, so it is cancelled and counted below. Filled: what it bought
            # shows up as an open position. Neither: look once more on the next tick before buying at
            # market, because a fill can take a moment to show up in the account.
            held = acct.positions.get((pair, "long"))
            resting_buy = next((o for o in acct.orders if o.get("pair") == pair and o.get("type") == "limit"
                                and o.get("side") == "buy" and o.get("position_side") == "long"
                                and abs(float(o.get("start_amount") or 0.0) - e["amount"]) < 1e-9), None)
            if resting_buy is not None:
                e["order_id"] = resting_buy.get("order_id")
            elif held is not None:
                executed = held.amount
            elif go and not e.get("looked"):
                e["looked"] = True
                return
            e["unconfirmed"] = False
        oid = e.get("order_id")
        resting = oid is not None and any(o.get("order_id") == oid for o in acct.orders)
        if resting and go and now < e["placed_ts"] + self.params.maker_wait_sec:
            return
        if oid is not None:
            if resting:
                self._cancel(pair, oid)
            try:
                info = self.client.get_order(pair, oid)
            except Exception as ex:
                logger.warning(f"Could not read entry order {oid} on {pair} ({ex}); trying again next tick")
                return
            if info.get("status") in ACTIVE:
                return                                 # the cancel has not gone through yet
            executed = float(info.get("executed_amount") or 0.0)
        remaining = floor_amount(pair, e["amount"] - executed)
        last = acct.prices[pair]["last"]
        if not go:
            logger.warning(f"Entry on {pair} dropped: new entries are switched off "
                           f"(filled {executed:g} of {e['amount']:g})")
        elif remaining >= MIN_AMOUNT and remaining * last >= MIN_NOTIONAL_JPY and last > e["stop"]:
            try:
                self.client.order(pair, "buy", amount=fmt_amount(pair, remaining), type_="market",
                                  position_side="long")
                logger.warning(f"BUY {pair}: {fmt_amount(pair, remaining)} at market "
                               f"(maker order filled {executed:g} of {e['amount']:g})")
            except Exception as ex:
                logger.error(f"Market buy on {pair} failed: {ex}")
        self.entries.pop(pair, None)
        if pair in self.positions:
            self.positions[pair]['entry_done_ts'] = now
        for _ in range(3):                             # put the stop on in this same tick
            try:
                fresh = self._read_positions(acct.prices)
            except Exception:
                break
            acct.positions.update(fresh)               # adds what is new; a reading that misses something removes nothing
            if (pair, "long") in fresh:
                break
            self.sleep(0.5)

    # ------------------------------------------------------------------ protection

    def _protect(self, pos: Position, acct: Account) -> None:
        close_side = "sell" if pos.side == "long" else "buy"
        stops = [o for o in acct.orders if o.get("pair") == pos.pair and o.get("type") == "stop"
                 and o.get("side") == close_side and o.get("position_side") == pos.side]
        covered = sum(_remaining(o) for o in stops)
        meta = self.positions.get(pos.pair) if pos.side == "long" else None
        if meta is None:
            # The operator's own protection counts too: a stop-limit for its amount, or Bitbank's stop-loss
            # order (type stop_loss), which covers the whole position and has no amount of its own.
            theirs = [o for o in acct.orders if o.get("pair") == pos.pair and o.get("side") == close_side
                      and o.get("position_side") == pos.side and o.get("type") in ("stop_limit", "stop_loss")]
            if any(o.get("type") == "stop_loss" for o in theirs):
                covered = pos.amount
            else:
                covered += sum(_remaining(o) for o in theirs)
            self._protect_manual(pos, close_side, covered)
            return
        if pos.avg > 0:
            meta["entry"] = pos.avg
        meta["amount"] = pos.amount
        meta["risk_jpy"] = pos.amount * meta["entry"] * meta["dist"]
        meta["best"] = max(float(meta.get("best") or 0.0), pos.last, pos.avg)
        if stops:
            self._naked_ticks.pop(pos.pair, None)
        want = strategy.trailing_stop(meta["entry"], meta["dist"], meta["best"], meta["stop"])
        current = max((float(o.get("trigger_price") or 0.0) for o in stops), default=None)
        sized = bool(stops) and abs(covered - pos.amount) <= pos.amount * 0.001
        if sized and current is not None:
            meta["stop"] = max(meta["stop"], current)
            meta["stop_id"] = max(stops, key=lambda o: float(o.get("trigger_price") or 0.0)).get("order_id")
            if want < current + self.TRAIL_STEP * pos.last or self.clock() < self._stop_retry_at.get(pos.pair, 0.0):
                return                                 # nothing worth moving, or a level was refused a moment ago
        target = max(want, current or 0.0)             # never lower than what is already on the exchange
        if pos.last <= target:
            self._close_at_market(pos, stops, "price is already at its stop level")
            return
        self._set_stop(pos, close_side, target, stops, meta)

    def _set_stop(self, pos: Position, close_side: str, price: float, old: List[Dict[str, Any]],
                  meta: Dict[str, Any]) -> None:
        """Put a full-size stop at `price`, then remove the stops it replaces (place before cancel).

        A stop that is in place is never cancelled because the new one could not be placed, with one
        exception: the exchange has twice answered that the resting stop itself is in the way (STOP_CONFLICT).
        Then the old stop is cancelled first, and its level goes straight back if the new one fails again.
        A transport error, a rate limit, an account restriction or a suspension never leads there, because
        in those cases the old stop could not be put back. That is also why the new stop is always tried
        first, even on an exchange known to refuse it: the answer shows whether orders are being taken."""
        pair = pos.pair
        known = bool(old) and self._stop_refusals.get(pair, 0) >= 2
        new, code = self._place_stop(pos, close_side, price, expected=STOP_CONFLICT if known else ())
        fallback: Optional[float] = None
        if new is None and old:
            if code in BAD_TRIGGER:                    # do not ask for this level again at once
                self._stop_retry_at[pair] = self.clock() + self.STOP_RETRY_SEC
            if code not in STOP_CONFLICT:
                return                                 # the stop in place keeps working
            covered = sum(_remaining(o) for o in old)
            if abs(covered - pos.amount) <= pos.amount * 0.001:
                # The stop in place has the right size and only its level is behind: no hurry.
                self._stop_refusals[pair] = self._stop_refusals.get(pair, 0) + 1
                if self._stop_refusals[pair] < 2:
                    return
            else:
                # The position has outgrown its stop. Cover the missing part beside the stop that is there;
                # if that is refused as well, the stop is replaced now, not a tick later.
                missing = floor_amount(pair, pos.amount - covered + 1e-9)
                if missing >= MIN_AMOUNT:
                    extra, code = self._place_stop(pos, close_side, price, expected=STOP_CONFLICT, amount=missing)
                    if extra is not None or code not in STOP_CONFLICT:
                        return
            fallback = max(float(o.get("trigger_price") or 0.0) for o in old)
            gone = all([self._cancel(pair, o.get("order_id")) for o in old])
            new, code = self._place_stop(pos, close_side, price)
            if new is None and not gone:
                return                                 # a cancel did not go through: the old stop still stands
            if gone:
                old = []
        elif new is None and code in BAD_TRIGGER and meta["stop"] < price:
            fallback = meta["stop"]                    # nothing in place: the last accepted level beats none
        if new is None and fallback:
            if code in BAD_TRIGGER:
                self._stop_retry_at[pair] = self.clock() + self.STOP_RETRY_SEC
            new, _ = self._place_stop(pos, close_side, fallback)
        if new is None:
            self._naked_ticks[pair] = self._naked_ticks.get(pair, 0) + 1
            if self._naked_ticks[pair] >= self.MAX_STOP_FAILURES:
                self._close_at_market(pos, [], f"no stop could be placed on {self.MAX_STOP_FAILURES} ticks in a row")
            return
        for o in old:
            self._cancel(pair, o.get("order_id"))
        self._naked_ticks.pop(pair, None)
        level = float(new.get("trigger_price") or price)
        if level > meta["stop"] + 1e-9:
            logger.info(f"Stop on {pair} moved up to {fmt_price(pair, level)} (best price {meta['best']:g})")
        meta["stop"], meta["stop_id"] = max(meta["stop"], level), new.get("order_id")

    def _place_stop(self, pos: Position, close_side: str, price: float, expected: Tuple[int, ...] = (),
                    amount: Optional[float] = None) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        """A stop for the whole position, or for `amount` of it. Returns (order, error code). The code is None
        when the order was placed or when there was no answer from the exchange at all. A refusal with a code
        in `expected` is not logged as an error."""
        try:
            size = fmt_amount(pos.pair, pos.amount if amount is None else amount)
            res = self.client.order(pos.pair, close_side, amount=size, type_="stop",
                                    trigger_price=fmt_price(pos.pair, price), position_side=pos.side)
            return (res if res.get("order_id") is not None else None), None
        except Exception as e:
            code = _error_code(e)
            (logger.debug if code in expected else logger.error)(
                f"Stop order on {pos.pair} at {fmt_price(pos.pair, price)} failed: {e}")
            return None, code

    def _protect_manual(self, pos: Position, close_side: str, covered: float) -> None:
        """A position the bot did not open: give it a stop if it has none. Nothing else is touched."""
        key = (pos.pair, pos.side)
        if covered >= pos.amount * 0.999:
            self._naked_seen.pop(key, None)
            return
        self._naked_seen[key] = self._naked_seen.get(key, 0) + 1
        if self._naked_seen[key] < 2:
            return                                     # one tick of grace for the operator's own stop
        missing = floor_amount(pos.pair, pos.amount - covered + 1e-9)
        pct = self.settings.manual_stop_pct
        trig = pos.avg * (1.0 - pct) if pos.side == "long" else pos.avg * (1.0 + pct)
        if (pos.side == "long" and pos.last <= trig) or (pos.side == "short" and pos.last >= trig):
            trig = pos.last * (0.997 if pos.side == "long" else 1.003)   # already beyond that level
        try:
            self.client.order(pos.pair, close_side, amount=fmt_amount(pos.pair, missing), type_="stop",
                              trigger_price=fmt_price(pos.pair, trig), position_side=pos.side)
            logger.warning(f"Manual {pos.side} on {pos.pair} had no stop for {missing:g}: "
                           f"protective stop placed at {fmt_price(pos.pair, trig)}")
        except Exception as e:
            logger.error(f"Could not place a protective stop on manual {pos.pair} {pos.side}: {e}")

    def _close_at_market(self, pos: Position, stops: List[Dict[str, Any]], why: str) -> None:
        logger.error(f"Closing {pos.pair} {pos.side} at market: {why}")
        try:
            self.client.order(pos.pair, "sell" if pos.side == "long" else "buy",
                              amount=fmt_amount(pos.pair, pos.amount), type_="market", position_side=pos.side)
        except Exception as e:
            logger.error(f"Market close of {pos.pair} failed: {e}")
            return
        for o in stops:
            self._cancel(pos.pair, o.get("order_id"))
        meta = self.positions.get(pos.pair)
        if meta is not None and pos.side == "long":
            meta["exit_reason"] = why

    def _cancel(self, pair: str, order_id: Any) -> bool:
        """True when the order is off the book: cancelled now, or the exchange says it is already gone."""
        if order_id is None:
            return True
        try:
            self.client.cancel(pair, order_id)
            return True
        except Exception as e:
            return _error_code(e) in ORDER_GONE

    def _cancel_orphan_stops(self, acct: Account, just_closed: set) -> None:
        """A closing stop with no position behind it must not fire later. Cancel it on the second sighting,
        or at once when its position closed on this tick, and only after one more look at the positions."""
        seen, due = set(), []
        for o in acct.orders:
            side = o.get("position_side")
            if o.get("type") != "stop" or side not in ("long", "short"):
                continue
            pair = o.get("pair")
            if o.get("side") != ("sell" if side == "long" else "buy"):
                continue                               # an opening stop order, not a protective one
            if (pair, side) in acct.positions or pair in self.entries:
                continue
            oid = o.get("order_id")
            seen.add(oid)
            if oid in self._orphan_seen or pair in just_closed:
                due.append(o)
        self._orphan_seen = seen
        if not due:
            return
        fresh = self._read_positions(acct.prices)      # a stop is taken away only if a second reading agrees
        for o in due:
            pair, oid = o.get("pair"), o.get("order_id")
            if (pair, o.get("position_side")) in fresh:
                self._orphan_seen.discard(oid)
                continue
            logger.warning(f"Cancelling stop {oid} on {pair}: there is no position behind it")
            self._cancel(pair, oid)

    # ------------------------------------------------------------------ closed trades

    def _close_finished(self, acct: Account) -> set:
        closed = set()
        now = self.clock()
        for pair in list(self.positions):
            if pair in self.entries or (pair, "long") in acct.positions:
                self._gone_ticks.pop(pair, None)
                continue
            meta = self.positions[pair]
            if not meta.get("amount"):
                # Never seen as a position. A buy that has just gone through may not be visible yet, so the
                # record is kept for a while; without it the position would lose its stop plan and trailing.
                if now - float(meta.setdefault("entry_done_ts", now)) < self.FILL_GRACE_SEC:
                    continue
            else:
                # Missing from one reading is not yet a closed trade: the record and the stop stay until a
                # second reading in a row confirms it.
                self._gone_ticks[pair] = self._gone_ticks.get(pair, 0) + 1
                if self._gone_ticks[pair] < 2:
                    continue
            del self.positions[pair]
            for d in (self._stop_refusals, self._naked_ticks, self._stop_retry_at, self._gone_ticks):
                d.pop(pair, None)
            if not meta.get("amount"):
                continue                               # the entry never filled
            closed.add(pair)
            self._step(f"journal for {pair}", self._record_close, pair, meta, acct)
        return closed

    def _record_close(self, pair: str, meta: Dict[str, Any], acct: Account) -> None:
        exit_px = acct.prices[pair]["last"]
        reason = meta.get("exit_reason") or "closed outside the bot"
        if meta.get("stop_id") is not None:
            try:
                o = self.client.get_order(pair, meta["stop_id"])
                if o.get("status") == "FULLY_FILLED":
                    if float(o.get("average_price") or 0.0) > 0:
                        exit_px = float(o["average_price"])
                    reason = "trailing stop" if meta["stop"] > meta["plan_stop"] * 1.0005 else "initial stop"
            except Exception:
                pass
        pnl = self._realized_pnl(pair, meta)
        if pnl is None:
            amount = meta["amount"]
            pnl = (exit_px - meta["entry"]) * amount - amount * (exit_px + meta["entry"]) * FEE_TAKER
        now_ms = int(self.clock() * 1000)
        row = {"pair": pair, "side": "long", "entry_ts": meta["entry_ts"], "exit_ts": now_ms,
               "timestamp": now_ms / 1000.0, "entry": meta["entry"], "exit": exit_px, "amount": meta["amount"],
               "pnl_jpy": round(pnl, 2), "r": round(pnl / meta["risk_jpy"], 3) if meta.get("risk_jpy") else 0.0,
               "days": round((now_ms - meta["entry_ts"]) / 86_400_000, 2), "reason": reason,
               "equity_after": round(acct.equity, 2)}
        self.journal.append(row)
        self._save_journal()
        logger.warning(f"CLOSED {pair}: {row['pnl_jpy']:+,.0f} JPY ({row['r']:+.2f}R) after {row['days']} days, {reason}")

    def _realized_pnl(self, pair: str, meta: Dict[str, Any]) -> Optional[float]:
        """Net result of the trade from the exchange's own fill records. Bitbank's profit_loss on a closing
        fill is already net of the entry and exit fees (it equals the change in the account balance), so only
        interest is taken off."""
        try:
            res = self.client._get("/user/spot/trade_history", {"pair": pair, "count": "200", "order": "desc"})
        except Exception:
            return None
        total, closed = 0.0, False
        for t in res.get("trades", []) if isinstance(res, dict) else []:
            if t.get("position_side") != "long" or int(t.get("executed_at") or 0) < meta["entry_ts"] - 60_000:
                continue
            if t.get("side") == "sell":
                total += float(t.get("profit_loss") or 0.0) - float(t.get("interest") or 0.0)
                closed = True
        return total if closed else None

    # ------------------------------------------------------------------ dashboard

    def watchlist(self) -> List[Dict[str, Any]]:
        """One row per coin: where it stands against its breakout level."""
        rows = []
        held = {k[0]: v for k, v in (self.account.positions.items() if self.account else [])}
        for pair in PAIRS:
            s = self.snapshots.get(pair)
            meta = self.positions.get(pair)
            if meta is not None and (pair in held or meta.get("amount")):
                state = "HOLDING"
            elif pair in self.entries or meta is not None:
                state = "BUYING"
            elif pair in held:
                state = "MANUAL"
            elif s is not None and strategy.signal(s, self.params):
                state = "BREAKOUT"
            else:
                state = "WATCHING"
            row: Dict[str, Any] = {"pair": pair, "action": state, "note": "waiting for the first 4h candle",
                                   "close": None, "breakout": None, "gap_pct": None, "stop_pct": None}
            if s is not None:
                row.update(note=strategy.checks(s, self.params)[0][0], close=s.close, breakout=s.channel_high,
                           gap_pct=round((s.channel_high / s.close - 1.0) * 100.0, 2),
                           stop_pct=round(strategy.stop_distance(s, self.params) * 100.0, 2))
            rows.append(row)
        return rows
