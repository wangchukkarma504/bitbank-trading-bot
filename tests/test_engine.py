"""Tests for the live engine against the simulated exchange (tests/mock_bitbank.py)."""

import os
import tempfile
import unittest

from tests.mock_bitbank import MockBitbankClient
from tradingbot.bitbank import BitbankError
from tradingbot.engine import Engine, Settings
from tradingbot.strategy import BAR_MS, Params, Snapshot

T0 = 1_800_000_000_000 // BAR_MS * BAR_MS     # a 4h boundary
ETH = 335000.0


class Rig:
    """An engine on a mock exchange with a hand-driven clock and hand-fed 4h snapshots."""

    def __init__(self, cash=20000.0, state_dir=None, **engine_kw):
        self.mock = MockBitbankClient(starting_cash_jpy=cash, baseline_budget_jpy=cash)
        self.now = T0 / 1000 + 60.0               # one minute after a 4h close
        self.snaps = {}
        self.dir = state_dir or tempfile.mkdtemp()
        self.engine_kw = engine_kw
        self.engine = self.build()

    def build(self) -> Engine:
        eng = Engine(client=self.mock, mode="live", settings=Settings(baseline_jpy=20000.0),
                     state_path=os.path.join(self.dir, "state.json"),
                     journal_path=os.path.join(self.dir, "journal.json"),
                     clock=lambda: self.now, sleep=lambda s: None, **self.engine_kw)
        eng._bar_snapshot = lambda pair, now_ms: self.snaps.get(pair)
        return eng

    def breakout(self, pair="eth_jpy", close=ETH, atr=0.02, momentum=0.1):
        bar_ts = int(self.now * 1000) // BAR_MS * BAR_MS
        self.snaps[pair] = Snapshot(bar_ts, close, close * 0.99, atr, momentum)

    def tick(self, seconds=20.0):
        self.now += seconds
        return self.engine.tick()

    def live(self, **match):
        return [o for o in self.mock.orders.values() if o["status"] == "UNFILLED"
                and all(o.get(k) == v for k, v in match.items())]

    def long(self, pair="eth_jpy"):
        for p in self.mock.margin_positions_list:
            if p["pair"] == pair and p["position_side"] == "long":
                return float(p["open_amount"])
        return 0.0

    def open_long(self, pair="eth_jpy", price=ETH):
        """Breakout, then let the resting maker buy fill."""
        self.breakout(pair, close=price)
        self.tick()
        self.mock.simulate_tick(pair, price * 0.999)       # trades through the resting buy
        self.mock.simulate_tick(pair, price)
        self.tick()


class TestEntries(unittest.TestCase):
    def test_breakout_rests_a_maker_buy_sized_by_risk(self):
        rig = Rig()
        rig.breakout(atr=0.02)                               # stop distance 3 x 2% = 6%
        rig.tick()
        buys = rig.live(side="buy", type="limit")
        self.assertEqual(len(buys), 1)
        o = buys[0]
        self.assertEqual((o["pair"], o["position_side"], o["post_only"]), ("eth_jpy", "long", True))
        notional = float(o["start_amount"]) * ETH
        self.assertAlmostEqual(notional / 20000.0, 0.02 / 0.06, delta=0.02)   # 2% risk over a 6% stop = 33%
        self.assertLessEqual(float(o["price"]), float(rig.mock.tickers["eth_jpy"]["buy"]))   # at or below the bid

    def test_filled_maker_buy_gets_its_stop_on_the_next_tick(self):
        rig = Rig()
        rig.open_long()
        amount = rig.long()
        self.assertGreater(amount, 0)
        stops = rig.live(type="stop", side="sell", position_side="long")
        self.assertEqual(len(stops), 1)
        self.assertAlmostEqual(float(stops[0]["start_amount"]), amount, places=4)
        self.assertAlmostEqual(float(stops[0]["trigger_price"]), ETH * 0.94, delta=ETH * 0.001)
        self.assertEqual(rig.engine.entries, {})

    def test_unfilled_maker_buy_becomes_a_market_buy_with_a_stop_in_the_same_tick(self):
        rig = Rig()
        rig.breakout()
        rig.tick()
        planned = float(rig.live(side="buy", type="limit")[0]["start_amount"])
        rig.tick(601.0)                                      # the 10-minute wait is over
        self.assertEqual(rig.live(side="buy", type="limit"), [])
        self.assertAlmostEqual(rig.long(), planned, places=4)
        self.assertEqual(len(rig.live(type="stop", side="sell")), 1)

    def test_rejected_maker_order_falls_back_to_market(self):
        rig = Rig()
        rig.breakout(close=ETH * 1.01)                       # plan price above the ask is clipped to the bid ...
        real_order = rig.mock.order
        rig.mock.order = lambda pair, side, **kw: (_ for _ in ()).throw(BitbankError("refused")) \
            if kw.get("type_") == "limit" else real_order(pair, side, **kw)
        rig.tick()
        self.assertEqual(rig.long(), 0.0)
        rig.tick()
        self.assertGreater(rig.long(), 0.0)                  # ... and a refused limit order is bought at market
        self.assertEqual(len(rig.live(type="stop", side="sell")), 1)

    def test_lost_reply_to_the_maker_order_does_not_buy_twice(self):
        rig = Rig()
        rig.breakout()
        real_order = rig.mock.order

        def lost_reply(pair, side, **kw):
            res = real_order(pair, side, **kw)               # the exchange accepts the order ...
            if kw.get("type_") == "limit":
                raise BitbankError("reply lost")             # ... but the bot never hears back
            return res
        rig.mock.order = lost_reply
        rig.tick()
        planned = float(rig.live(side="buy", type="limit")[0]["start_amount"])
        rig.mock.order = real_order
        rig.tick()                                           # adopts and cancels the resting order, buys at market
        self.assertEqual(rig.live(side="buy", type="limit"), [])
        self.assertAlmostEqual(rig.long(), planned, places=4)

    def test_strongest_breakouts_fill_the_free_slots(self):
        rig = Rig(params=Params(max_positions=2))
        for pair, mom, px in (("btc_jpy", 0.05, 11800000.0), ("eth_jpy", 0.30, ETH), ("sol_jpy", 0.20, 13750.0)):
            rig.breakout(pair, close=px, momentum=mom)
        rig.tick()
        self.assertEqual({o["pair"] for o in rig.live(side="buy", type="limit")}, {"eth_jpy", "sol_jpy"})

    def test_no_entry_when_late_paused_at_the_floor_or_in_dry_run(self):
        late = Rig()
        late.now += 3600.0                                   # an hour after the close: displayed, not traded
        late.breakout()
        late.tick()
        self.assertEqual(late.live(side="buy"), [])
        self.assertEqual(late.engine.watchlist()[1]["action"], "BREAKOUT")

        paused = Rig()
        paused.engine.entries_enabled = False
        paused.breakout()
        paused.tick()
        self.assertEqual(paused.live(side="buy"), [])

        floor = Rig()
        floor.engine.settings.equity_floor_jpy = 25000.0
        floor.breakout()
        floor.tick()
        self.assertTrue(floor.engine.floor_hit)
        self.assertEqual(floor.live(side="buy"), [])

        dry = Rig()
        dry.engine.dry_run = True
        dry.breakout()
        dry.tick()
        self.assertEqual(dry.mock.orders, {})

    def test_one_signal_is_traded_once(self):
        rig = Rig()
        rig.breakout()
        for _ in range(5):
            rig.tick()
        self.assertEqual(len([o for o in rig.mock.orders.values() if o["side"] == "buy"]), 1)


class TestStops(unittest.TestCase):
    def test_stop_follows_the_price_up_and_never_down(self):
        rig = Rig()
        rig.open_long()
        first = float(rig.live(type="stop")[0]["trigger_price"])
        rig.mock.simulate_tick("eth_jpy", ETH * 1.10)
        rig.tick()
        stops = rig.live(type="stop")
        self.assertEqual(len(stops), 1)                      # the old stop is replaced, not left beside the new one
        raised = float(stops[0]["trigger_price"])
        avg = rig.engine.positions["eth_jpy"]["entry"]
        self.assertAlmostEqual(raised, ETH * 1.10 - 0.06 * avg, delta=ETH * 0.001)
        self.assertGreater(raised, first)
        rig.mock.simulate_tick("eth_jpy", ETH * 1.07)        # pullback above the stop
        rig.tick()
        self.assertAlmostEqual(float(rig.live(type="stop")[0]["trigger_price"]), raised)

    def test_small_moves_do_not_replace_the_stop_order(self):
        rig = Rig()
        rig.open_long()
        oid = rig.live(type="stop")[0]["order_id"]
        rig.mock.simulate_tick("eth_jpy", ETH * 1.002)
        rig.tick()
        self.assertEqual(rig.live(type="stop")[0]["order_id"], oid)

    def test_stopped_out_trade_is_journaled_with_its_loss(self):
        rig = Rig()
        rig.open_long()
        rig.mock.simulate_tick("eth_jpy", ETH * 0.93)        # through the 6% stop
        rig.tick()
        self.assertEqual(rig.long(), 0.0)
        self.assertEqual(rig.engine.positions, {})
        row = rig.engine.journal[-1]
        self.assertEqual((row["pair"], row["reason"]), ("eth_jpy", "initial stop"))
        self.assertLess(row["r"], -0.9)
        self.assertGreater(row["r"], -1.3)
        self.assertEqual(rig.live(), [])                     # nothing left on the book

    def test_journal_takes_the_result_from_the_exchange_fill_records(self):
        rig = Rig()
        rig.open_long()
        entry_ts = rig.engine.positions["eth_jpy"]["entry_ts"]
        real_get = rig.mock._get

        def with_history(path, params=None):
            if path == "/user/spot/trade_history":
                return {"trades": [
                    {"pair": "eth_jpy", "side": "sell", "position_side": "long", "executed_at": entry_ts + 5000,
                     "profit_loss": "-430.5", "fee_occurred_amount_quote": "7.5", "interest": "2.0"},
                    {"pair": "eth_jpy", "side": "buy", "position_side": "long", "executed_at": entry_ts,
                     "profit_loss": "0", "fee_occurred_amount_quote": "-1.3", "interest": "0"},
                    {"pair": "eth_jpy", "side": "sell", "position_side": "long", "executed_at": entry_ts - 3_600_000,
                     "profit_loss": "999", "fee_occurred_amount_quote": "1", "interest": "0"},     # an older trade
                ]}
            return real_get(path, params)
        rig.mock._get = with_history
        rig.mock.simulate_tick("eth_jpy", ETH * 0.93)
        rig.tick()
        # profit_loss already contains the fees: only the interest comes off, and nothing is counted twice
        self.assertAlmostEqual(rig.engine.journal[-1]["pnl_jpy"], -432.5)

    def test_stop_is_resized_when_the_position_grows(self):
        rig = Rig()
        rig.open_long()
        before = rig.long()
        rig.mock._update_margin_position("eth_jpy", "long", delta_amount=0.005, fill_price=ETH)
        rig.tick()
        stops = rig.live(type="stop")
        self.assertEqual(len(stops), 1)
        self.assertAlmostEqual(float(stops[0]["start_amount"]), before + 0.005, places=4)

    def test_failed_stop_placement_keeps_the_old_stop_and_retries(self):
        rig = Rig()
        rig.open_long()
        old = rig.live(type="stop")[0]
        real_order = rig.mock.order
        rig.mock.order = lambda pair, side, **kw: (_ for _ in ()).throw(BitbankError("busy")) \
            if kw.get("type_") == "stop" else real_order(pair, side, **kw)
        rig.mock.simulate_tick("eth_jpy", ETH * 1.10)
        rig.tick()
        self.assertEqual([o["order_id"] for o in rig.live(type="stop")], [old["order_id"]])   # still protected
        rig.mock.order = real_order
        rig.tick()
        self.assertGreater(float(rig.live(type="stop")[0]["trigger_price"]), float(old["trigger_price"]))

    def test_position_that_cannot_get_a_stop_is_closed(self):
        rig = Rig()
        rig.breakout()
        rig.tick()
        real_order = rig.mock.order
        rig.mock.order = lambda pair, side, **kw: (_ for _ in ()).throw(BitbankError("no stops today")) \
            if kw.get("type_") == "stop" else real_order(pair, side, **kw)
        rig.tick(601.0)                                      # market buy; the stop is refused
        self.assertGreater(rig.long(), 0.0)
        rig.tick()
        rig.tick()                                           # third failed attempt: closed at market
        self.assertEqual(rig.long(), 0.0)

    def test_orphan_stop_is_cancelled(self):
        rig = Rig()
        rig.mock.order("eth_jpy", "sell", amount="0.01", type_="stop", trigger_price="300000", position_side="long")
        rig.tick()
        self.assertEqual(len(rig.live(type="stop")), 1)      # first sighting: left alone
        rig.tick()
        self.assertEqual(rig.live(type="stop"), [])


class TestManualActivity(unittest.TestCase):
    def test_manual_short_gets_a_protective_stop_and_is_otherwise_left_alone(self):
        rig = Rig()
        rig.mock._update_margin_position("sol_jpy", "short", delta_amount=1.0, fill_price=13750.0)
        rig.tick()
        self.assertEqual(rig.live(type="stop"), [])          # one tick of grace
        rig.tick()
        stops = rig.live(type="stop", side="buy", position_side="short")
        self.assertEqual(len(stops), 1)
        self.assertAlmostEqual(float(stops[0]["trigger_price"]), 13750.0 * 1.012, delta=1.0)
        rig.mock.simulate_tick("sol_jpy", 13000.0)           # deep in profit: the bot does not trail or close it
        rig.tick()
        self.assertEqual([o["order_id"] for o in rig.live(type="stop")], [stops[0]["order_id"]])
        self.assertNotIn("sol_jpy", rig.engine.positions)

    def test_manual_orders_are_never_cancelled_and_their_pair_is_not_traded_once_filled(self):
        rig = Rig()
        manual = rig.mock.order("sol_jpy", "sell", amount="1.0", price="14500.0", type_="limit", position_side="short")
        for _ in range(40):                                  # far longer than any stale-order rule
            rig.tick(60.0)
        self.assertEqual(rig.mock.orders[manual["order_id"]]["status"], "UNFILLED")
        rig.mock.simulate_tick("sol_jpy", 14600.0)           # the manual short fills
        rig.now = (int(rig.now * 1000) // BAR_MS + 1) * BAR_MS / 1000 + 60.0
        rig.breakout("sol_jpy", close=14600.0)
        rig.tick()
        self.assertEqual(rig.live(side="buy", type="limit"), [])   # no long on a pair with a manual position

    def test_manual_positions_count_toward_the_position_limit(self):
        rig = Rig(params=Params(max_positions=1))
        rig.mock._update_margin_position("sol_jpy", "short", delta_amount=1.0, fill_price=13750.0)
        rig.breakout("eth_jpy")
        rig.tick()
        self.assertEqual(rig.live(side="buy", type="limit"), [])


class TestRobustness(unittest.TestCase):
    def test_failed_account_read_does_nothing(self):
        rig = Rig()
        rig.open_long()
        rig.mock.simulate_maintenance(True)
        with self.assertRaises(BitbankError):
            rig.tick()
        rig.mock.simulate_maintenance(False)
        self.assertEqual(len(rig.live(type="stop")), 1)

    def test_restart_keeps_managing_the_position(self):
        rig = Rig()
        rig.open_long()
        rig.engine = rig.build()                             # new process, same state file
        self.assertIn("eth_jpy", rig.engine.positions)
        rig.mock.simulate_tick("eth_jpy", ETH * 1.10)
        rig.tick()
        avg = rig.engine.positions["eth_jpy"]["entry"]
        self.assertAlmostEqual(float(rig.live(type="stop")[0]["trigger_price"]), ETH * 1.10 - 0.06 * avg, delta=ETH * 0.001)

    def test_restart_during_the_maker_wait_finishes_the_entry(self):
        rig = Rig()
        rig.breakout()
        rig.tick()
        rig.engine = rig.build()
        rig.tick(601.0)
        self.assertGreater(rig.long(), 0.0)
        self.assertEqual(len(rig.live(type="stop", side="sell")), 1)

    def test_watchlist_describes_every_coin(self):
        rig = Rig()
        rig.open_long()
        rows = {r["pair"]: r for r in rig.engine.watchlist()}
        self.assertEqual(rows["eth_jpy"]["action"], "HOLDING")
        self.assertEqual(rows["btc_jpy"]["action"], "WATCHING")
        self.assertEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
