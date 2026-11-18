"""Randomised stress run of the engine on the simulated exchange.

Prices jump around, API calls fail (before the exchange acts, or after it acted with the reply lost), the
process restarts, entry orders fill in halves, and a "user" opens and closes manual positions and leaves
manual orders on the book. Whenever two ticks in a row ran without an injected failure, the account
must satisfy the safety rules checked in `audit`.

    python3 -m tests.test_engine_stress [seeds] [ticks]     # longer run with a printed report
"""

import collections
import math
import os
import random
import sys
import tempfile
import unittest

from tests.mock_bitbank import MockBitbankClient
from tradingbot import engine as engine_mod
from tradingbot.bitbank import BitbankError
from tradingbot.engine import Engine, PAIRS, Settings
from tradingbot.strategy import Params, Snapshot

BAR = 400_000            # a "4h candle" lasts 20 ticks here, so entries happen often
START = {"btc_jpy": 11_800_000.0, "eth_jpy": 335_000.0, "xrp_jpy": 125.0, "sol_jpy": 13_750.0, "doge_jpy": 15.5}
SCENARIOS = [
    ("calm", {}),
    ("API failures 8%", {"fault": 0.08}),
    ("API failures 25%", {"fault": 0.25}),
    ("failures + restarts", {"fault": 0.08, "restart": 0.01}),
    ("partial fills + failures + restarts", {"fault": 0.08, "restart": 0.01, "partial": 0.5}),
    ("manual trading alongside", {"manual": 0.02}),
    ("everything at once", {"fault": 0.10, "restart": 0.01, "partial": 0.5, "manual": 0.02}),
]


class Faulty:
    """Wraps the mock exchange; while armed, calls fail at random, sometimes after they took effect."""
    CALLS = ("ticker", "_get", "order", "cancel", "get_order", "margin_positions", "candles")

    def __init__(self, inner, rng, p):
        self._inner, self._rng, self._p = inner, rng, p
        self.armed = False
        self.faults = 0

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name not in self.CALLS:
            return target

        def call(*args, **kwargs):
            roll = self._rng.random() if self.armed else 1.0
            if roll < self._p * 0.7:
                self.faults += 1
                raise BitbankError(f"{name}: {{'success': 0, 'data': {{'code': 10009}}}} (injected)")
            result = target(*args, **kwargs)
            if roll < self._p:
                self.faults += 1
                raise BitbankError(f"{name}: reply lost (injected)")
            return result
        return call


def run(seed: int, ticks: int, cfg: dict):
    rng = random.Random(seed)
    fault, restart, partial, manual = (cfg.get(k, 0.0) for k in ("fault", "restart", "partial", "manual"))
    mock = MockBitbankClient(starting_cash_jpy=20000.0, baseline_budget_jpy=20000.0)
    client = Faulty(mock, rng, fault)
    clock = {"t": 1_800_000_000.0}
    px = dict(START)
    for p_, v in px.items():
        mock.set_price(p_, v)
    workdir = tempfile.mkdtemp()
    params = Params(maker_wait_sec=60)
    stats = collections.Counter()
    violations = collections.Counter()
    examples = {}
    manual_orders, manual_positions = set(), set()

    full_fill = mock._execute_limit_fill

    def limit_fill(order, fill_price):
        rem = float(order["remaining_amount"])
        if (order.get("position_side") == "long" and order["side"] == "buy" and not order.get("_partial")
                and rem >= 0.0004 and rng.random() < partial):
            half = math.floor(rem / 2 * 1e4) / 1e4
            mock._update_margin_position(order["pair"], "long", delta_amount=half, fill_price=fill_price)
            order["executed_amount"] = f"{float(order['executed_amount']) + half:.4f}"
            order["remaining_amount"] = f"{rem - half:.4f}"
            order["_partial"] = True
            stats["partial_fills"] += 1
            return dict(order, type="limit_partial")
        if order.get("_partial"):
            mock._update_margin_position(order["pair"], "long", delta_amount=rem, fill_price=fill_price)
            order.update(status="FULLY_FILLED", executed_amount=order["start_amount"], remaining_amount="0.0000")
            return order
        return full_fill(order, fill_price)
    mock._execute_limit_fill = limit_fill

    real_order = mock.order

    def watched_order(pair, side, **kw):
        if kw.get("type_") == "market" and (pair, kw.get("position_side")) in manual_positions:
            violations["bot_closed_manual_position"] += 1
        if kw.get("position_side") == "short" and side == "sell":
            violations["bot_opened_short"] += 1
        return real_order(pair, side, **kw)
    mock.order = watched_order

    def build():
        eng = Engine(client=client, mode="live", settings=Settings(baseline_jpy=20000.0), params=params,
                     state_path=os.path.join(workdir, "state.json"), journal_path=os.path.join(workdir, "journal.json"),
                     clock=lambda: clock["t"], sleep=lambda s: None)
        eng.ENTRY_WINDOW_SEC, eng.BAR_SETTLE_SEC = 120.0, 20.0

        def snapshot(pair, now_ms):
            bar_ts = now_ms // BAR * BAR
            r = random.Random(f"{seed}-{pair}-{bar_ts}")       # the same answer every time it is asked
            last = float(mock.tickers[pair]["last"])
            level = last * (0.995 if r.random() < 0.25 else 1.02)
            return Snapshot(bar_ts, last, level, r.uniform(0.006, 0.04), r.random())
        eng._bar_snapshot = snapshot
        return eng

    old_bar = engine_mod.BAR_MS
    engine_mod.BAR_MS = BAR
    try:
        eng = build()
        clean = 0
        first_seen = {}
        orphan_streak = collections.Counter()

        def note(kind, detail, i):
            violations[kind] += 1
            examples.setdefault(kind, f"seed {seed} tick {i}: {detail}")

        for i in range(ticks):
            clock["t"] += 20.0
            for pair in PAIRS:
                move = rng.gauss(0, 0.003) if rng.random() > 0.03 else rng.choice([-1, 1]) * rng.uniform(0.015, 0.04)
                px[pair] = max(START[pair] * 0.4, px[pair] * (1 + move))
                for o in mock.simulate_tick(pair, round(px[pair], PAIRS[pair][0])):
                    stats["fill_" + o["type"]] += 1
                    if o.get("order_id") in manual_orders:     # a manual order filled: that position is manual
                        manual_positions.add((o["pair"], o.get("position_side")))
            if rng.random() < manual:                          # the user trades by hand
                pair = rng.choice(list(PAIRS))
                side = rng.choice(["short", "long"])
                held = {(p["pair"], p["position_side"]) for p in mock.margin_positions_list if float(p["open_amount"]) > 0}
                if (pair, side) in manual_positions and (pair, side) in held:
                    amt = next(float(p["open_amount"]) for p in mock.margin_positions_list
                               if p["pair"] == pair and p["position_side"] == side)
                    mock._update_margin_position(pair, side, delta_amount=-amt, fill_price=px[pair])
                    manual_positions.discard((pair, side))
                elif not any(k[0] == pair for k in held) and pair not in eng.entries and pair not in eng.positions:
                    mock._update_margin_position(pair, side, delta_amount=round(3000.0 / px[pair], 4), fill_price=px[pair])
                    manual_positions.add((pair, side))
                    stats["manual_positions"] += 1
                else:
                    far = px[pair] * (1.5 if side == "short" else 0.5)
                    o = real_order(pair, "sell" if side == "short" else "buy", amount="0.0010",
                                   price=engine_mod.fmt_price(pair, far), type_="limit", position_side=side)
                    manual_orders.add(o["order_id"])
            if rng.random() < restart:
                eng = build()
                stats["restarts"] += 1
            before = client.faults
            client.armed = True
            try:
                eng.tick()
            except BitbankError:
                stats["failed_ticks"] += 1
            except Exception as e:  # noqa: BLE001
                note("crash", f"{type(e).__name__}: {e}", i)
            client.armed = False
            clean = clean + 1 if client.faults == before else 0
            # a manual position that the price has stopped out is no longer a manual position
            held = {(p["pair"], p["position_side"]): p for p in mock.margin_positions_list if float(p["open_amount"]) > 0}
            manual_positions &= set(held)
            for key in list(first_seen):
                if key not in held:
                    del first_seen[key]                    # first_seen counts audited ticks without full cover
            if clean < 2:
                continue
            audit(mock, eng, held, first_seen, manual_positions, manual_orders, orphan_streak, note, i)
        stats["faults"] = client.faults
        stats["closed_trades"] = len(eng.journal)
        stats["final_equity"] = round(mock.calculate_total_equity())
    finally:
        engine_mod.BAR_MS = old_bar
    return violations, examples, stats


def audit(mock, eng, held, first_seen, manual_positions, manual_orders, orphan_streak, note, i):
    live = [o for o in mock.orders.values() if o["status"] == "UNFILLED"]
    equity = mock.calculate_total_equity()
    if equity <= 0:
        note("equity_not_positive", f"{equity:,.0f}", i)
    if len(live) > 14 + len(manual_orders):
        note("order_pileup", f"{len(live)} live orders", i)
    bot_longs = 0
    for (pair, side), p in held.items():
        amt = float(p["open_amount"])
        stops = [o for o in live if o["pair"] == pair and o["type"] == "stop" and o.get("position_side") == side
                 and o["side"] == ("sell" if side == "long" else "buy")]
        cover = sum(float(o["remaining_amount"]) for o in stops)
        is_manual = (pair, side) in manual_positions
        # The bot's own positions must be covered at once; a manual one gets its stop on the second sighting
        first_seen[(pair, side)] = first_seen.get((pair, side), 0) + 1 if cover < amt * 0.999 else 0
        if first_seen[(pair, side)] >= (4 if is_manual else 1):
            note("unprotected_position", f"{pair} {side} {amt} covered {cover}", i)
        if is_manual:
            continue
        if side == "short":
            note("unexpected_short", f"{pair} {amt}", i)
            continue
        bot_longs += 1
        meta = eng.positions.get(pair)
        if meta is None:
            continue                                           # adopted after a lost state file: protected only
        if cover > amt * 1.001:
            note("stop_larger_than_position", f"{pair} {amt} covered {cover} in {len(stops)} stops", i)
        if stops and max(float(o["trigger_price"]) for o in stops) < meta["plan_stop"] * 0.9995:
            note("stop_below_plan", f"{pair} stop {max(float(o['trigger_price']) for o in stops)} plan {meta['plan_stop']}", i)
        if amt * float(p["average_price"]) > eng.params.max_notional * meta["equity_at_entry"] * 1.10:
            note("position_too_large", f"{pair} {amt * float(p['average_price']):,.0f} vs equity {meta['equity_at_entry']:,.0f}", i)
    if bot_longs > eng.params.max_positions + len([k for k in manual_positions if k[1] == "long"]):
        note("too_many_positions", f"{bot_longs}", i)
    for pair in PAIRS:
        orphans = [o for o in live if o["pair"] == pair and o["type"] == "stop"
                   and (pair, o.get("position_side")) not in held and pair not in eng.entries]
        orphan_streak[pair] = orphan_streak[pair] + 1 if orphans else 0
        if orphan_streak[pair] == 4:
            note("orphan_stop", f"{pair} stop {orphans[0]['order_id']} with no position for 4 clean ticks", i)
    for oid in manual_orders:
        if mock.orders[oid]["status"] not in ("UNFILLED", "FULLY_FILLED"):
            note("manual_order_cancelled", f"order {oid} is {mock.orders[oid]['status']}", i)


def campaign(seeds: int, ticks: int, verbose: bool = False):
    total, first = collections.Counter(), {}
    for n, (name, cfg) in enumerate(SCENARIOS):
        v_all, s_all = collections.Counter(), collections.Counter()
        for seed in range(seeds):
            v, ex, s = run(seed * 7919 + n * 101, ticks, cfg)
            v_all.update(v)
            s_all.update(s)
            for k, d in ex.items():
                first.setdefault(f"[{name}] {k}", d)
        total.update(v_all)
        if verbose:
            print(f"== {name}: {seeds} runs x {ticks} ticks | fills {s_all['fill_limit']} limit / {s_all['partial_fills']} partial / "
                  f"{s_all['fill_stop']} stop | closed trades {s_all['closed_trades']} | manual positions {s_all['manual_positions']} | "
                  f"faults {s_all['faults']} | restarts {s_all['restarts']} | avg end equity {s_all['final_equity'] // seeds:,}")
            print("   violations:", dict(v_all) or "none")
    return total, first


class TestEngineUnderStress(unittest.TestCase):
    def test_safety_rules_hold_in_every_scenario(self):
        total, first = campaign(seeds=2, ticks=700)
        self.assertEqual(dict(total), {}, msg="\n".join(f"{k}: {v}" for k, v in first.items()))


if __name__ == "__main__":
    logging_off = __import__("logging")
    logging_off.disable(logging_off.CRITICAL)
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 2500
    total, first = campaign(seeds, ticks, verbose=True)
    print("\nFIRST EXAMPLE OF EACH VIOLATION")
    for k, d in first.items():
        print(f" - {k}: {d}")
    print("\nTOTAL", dict(total))
