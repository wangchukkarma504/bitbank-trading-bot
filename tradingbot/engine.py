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

from dataclasses import dataclass
import json
import logging
import math
import os
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
        self._stop_failures: Dict[str, int] = {}
        self._year_rows: Dict[Tuple[str, str], List[list]] = {}
        self._saved = ""
        self._load()

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
            with open(self.state_path, "w", encoding="utf-8") as f:
                f.write(blob)
            self._saved = blob
        except Exception as e:
            logger.warning(f"Could not save {self.state_path}: {e}")

    def _save_journal(self) -> None:
        if not self.journal_path:
            return
        try:
            with open(self.journal_path, "w", encoding="utf-8") as f:
                json.dump(self.journal, f, indent=1)
        except Exception as e:
            logger.warning(f"Could not save {self.journal_path}: {e}")

    # ------------------------------------------------------------------ the tick

    def tick(self) -> Dict[str, Any]:
        self.tick_count += 1
        acct = self.read_account()
        self.account = acct
        floor = self.settings.equity_floor_jpy
        self.floor_hit = bool(floor and 0 < acct.equity <= floor)
        if not self.dry_run:
            self._work_entries(acct)
            closed = self._close_finished(acct)
            for pos in list(acct.positions.values()):
                self._protect(pos, acct)
            self._cancel_orphan_stops(acct, closed)
        self._read_signals(acct)
        self._save()
        return {"equity_jpy": acct.equity}

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
        busy = {k[0] for k in acct.positions} | set(self.entries)
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
        """Snapshot of the newest closed 4h candle, from this year's and last year's candles."""
        year = time.gmtime(now_ms / 1000).tm_year
        rows: List[list] = []
        for y in (year - 1, year):
            key = (pair, str(y))
            if y == year or key not in self._year_rows:
                try:
                    self._year_rows[key] = list(self.client.candles(pair, "4hour", str(y)))
                except Exception:
                    if y == year:
                        raise
                    self._year_rows[key] = []          # a pair listed this year has no earlier file
            rows += self._year_rows[key]
        bars: List[Bar] = sorted({int(r[5]): (int(r[5]), float(r[0]), float(r[1]), float(r[2]), float(r[3]))
                                  for r in rows if int(r[5]) + BAR_MS <= now_ms}.values())
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
            unconfirmed = True     # the order may be resting all the same if only the reply was lost
            logger.warning(f"Maker buy on {pair} was not confirmed ({e}); buying at market on the next tick")
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

    def _work_entries(self, acct: Account) -> None:
        """Complete entries whose maker order has been filled, has timed out, or was never accepted."""
        now = self.clock()
        for pair in list(self.entries):
            e = self.entries[pair]
            executed = 0.0
            if e.get("unconfirmed"):
                # The reply to the maker order was lost. If the order is on the book after all, adopt it so it
                # is cancelled and counted below; what it already bought shows up as an open position.
                e["unconfirmed"] = False
                held = acct.positions.get((pair, "long"))
                executed = held.amount if held is not None else 0.0
                for o in acct.orders:
                    if (o.get("pair") == pair and o.get("type") == "limit" and o.get("side") == "buy"
                            and o.get("position_side") == "long"
                            and abs(float(o.get("start_amount") or 0.0) - e["amount"]) < 1e-9):
                        e["order_id"], executed = o.get("order_id"), 0.0
                        break
            oid = e.get("order_id")
            resting = oid is not None and any(o.get("order_id") == oid for o in acct.orders)
            if resting and now < e["placed_ts"] + self.params.maker_wait_sec:
                continue
            if oid is not None:
                if resting:
                    self._cancel(pair, oid)
                try:
                    info = self.client.get_order(pair, oid)
                except Exception as ex:
                    logger.warning(f"Could not read entry order {oid} on {pair} ({ex}); trying again next tick")
                    continue
                if info.get("status") in ACTIVE:
                    continue                           # the cancel has not gone through yet
                executed = float(info.get("executed_amount") or 0.0)
            remaining = floor_amount(pair, e["amount"] - executed)
            last = acct.prices[pair]["last"]
            if remaining >= MIN_AMOUNT and remaining * last >= MIN_NOTIONAL_JPY and last > e["stop"]:
                try:
                    self.client.order(pair, "buy", amount=fmt_amount(pair, remaining), type_="market",
                                      position_side="long")
                    logger.warning(f"BUY {pair}: {fmt_amount(pair, remaining)} at market "
                                   f"(maker order filled {executed:g} of {e['amount']:g})")
                except Exception as ex:
                    logger.error(f"Market buy on {pair} failed: {ex}")
            del self.entries[pair]
            for _ in range(3):                         # put the stop on in this same tick
                try:
                    acct.positions = self._read_positions(acct.prices)
                except Exception:
                    break
                if (pair, "long") in acct.positions:
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
            self._protect_manual(pos, close_side, covered)
            return
        meta["amount"] = pos.amount
        if pos.avg > 0:
            meta["entry"] = pos.avg
        meta["best"] = max(float(meta.get("best") or 0.0), pos.last, pos.avg)
        want = strategy.trailing_stop(meta["entry"], meta["dist"], meta["best"], meta["stop"])
        current = max((float(o.get("trigger_price") or 0.0) for o in stops), default=None)
        sized = bool(stops) and abs(covered - pos.amount) <= pos.amount * 0.001
        if sized and current is not None and want < current + self.TRAIL_STEP * pos.last:
            meta["stop"] = max(meta["stop"], current)
            meta["stop_id"] = max(stops, key=lambda o: float(o.get("trigger_price") or 0.0)).get("order_id")
            self._stop_failures.pop(pos.pair, None)
            return
        target = max(want, current or 0.0)             # never lower than what is already on the exchange
        if pos.last <= target:
            self._close_at_market(pos, stops, "price is already at its stop level")
            return
        self._set_stop(pos, close_side, target, stops, meta)

    def _set_stop(self, pos: Position, close_side: str, price: float, old: List[Dict[str, Any]],
                  meta: Dict[str, Any]) -> None:
        """Put a full-size stop at `price`, then remove the stops it replaces (place before cancel)."""
        pair = pos.pair
        fails = self._stop_failures.get(pair, 0)
        if old and fails >= 2:
            # Two refusals in a row with a stop in place: the exchange may not allow a second closing order.
            # Cancel first, and if the new one still fails, put the old level straight back.
            for o in old:
                self._cancel(pair, o.get("order_id"))
            old_level = max(float(o.get("trigger_price") or 0.0) for o in old)
            old = []
            new = self._place_stop(pos, close_side, price) or self._place_stop(pos, close_side, old_level)
        else:
            new = self._place_stop(pos, close_side, price)
        if new is None:
            self._stop_failures[pair] = fails + 1
            if not old and self._stop_failures[pair] >= self.MAX_STOP_FAILURES:
                self._close_at_market(pos, [], f"no stop could be placed in {self.MAX_STOP_FAILURES} attempts")
            return
        for o in old:
            self._cancel(pair, o.get("order_id"))
        self._stop_failures.pop(pair, None)
        level = float(new.get("trigger_price") or price)
        if level > meta["stop"] + 1e-9:
            logger.info(f"Stop on {pair} moved up to {fmt_price(pair, level)} (best price {meta['best']:g})")
        meta["stop"], meta["stop_id"] = max(meta["stop"], level), new.get("order_id")

    def _place_stop(self, pos: Position, close_side: str, price: float) -> Optional[Dict[str, Any]]:
        try:
            res = self.client.order(pos.pair, close_side, amount=fmt_amount(pos.pair, pos.amount), type_="stop",
                                    trigger_price=fmt_price(pos.pair, price), position_side=pos.side)
            return res if res.get("order_id") is not None else None
        except Exception as e:
            logger.error(f"Stop order on {pos.pair} at {fmt_price(pos.pair, price)} failed: {e}")
            return None

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

    def _cancel(self, pair: str, order_id: Any) -> None:
        if order_id is None:
            return
        try:
            self.client.cancel(pair, order_id)
        except Exception:
            pass                                       # already filled or cancelled

    def _cancel_orphan_stops(self, acct: Account, just_closed: set) -> None:
        """A closing stop with no position behind it must not fire later. Cancel it on the second sighting,
        or at once when its position closed on this tick."""
        seen = set()
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
                logger.warning(f"Cancelling stop {oid} on {pair}: there is no position behind it")
                self._cancel(pair, oid)
        self._orphan_seen = seen

    # ------------------------------------------------------------------ closed trades

    def _close_finished(self, acct: Account) -> set:
        closed = set()
        for pair in list(self.positions):
            if pair in self.entries or (pair, "long") in acct.positions:
                continue
            meta = self.positions.pop(pair)
            if not meta.get("amount"):
                continue                               # the entry never filled
            closed.add(pair)
            self._record_close(pair, meta, acct)
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
        """Net result of the trade from the exchange's own fill records (fees and interest included)."""
        try:
            res = self.client._get("/user/spot/trade_history", {"pair": pair, "count": "200", "order": "desc"})
        except Exception:
            return None
        total, closed = 0.0, False
        for t in res.get("trades", []) if isinstance(res, dict) else []:
            if t.get("position_side") != "long" or int(t.get("executed_at") or 0) < meta["entry_ts"] - 60_000:
                continue
            fee = float(t.get("fee_occurred_amount_quote") or t.get("fee_amount_quote") or 0.0)
            total += float(t.get("profit_loss") or 0.0) - fee - float(t.get("interest") or 0.0)
            closed = closed or t.get("side") == "sell"
        return total if closed else None

    # ------------------------------------------------------------------ dashboard

    def watchlist(self) -> List[Dict[str, Any]]:
        """One row per coin: where it stands against its breakout level."""
        rows = []
        held = {k[0]: v for k, v in (self.account.positions.items() if self.account else [])}
        for pair in PAIRS:
            s = self.snapshots.get(pair)
            if pair in self.positions and pair in held:
                state = "HOLDING"
            elif pair in self.entries:
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
