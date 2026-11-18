"""Tests for the trading rule (strategy.py) and its replay (backtest.py)."""

import unittest

from tradingbot import backtest, strategy
from tradingbot.strategy import BAR_MS, Params

P = Params(channel_bars=20, atr_bars=5, momentum_bars=5, maker_wait_sec=600)
T0 = 1_700_000_000_000 // BAR_MS * BAR_MS


def flat_bars(n, price=100.0, spread=1.0):
    """n quiet 4h candles around `price` (high = price + spread, low = price - spread)."""
    return [(T0 + i * BAR_MS, price, price + spread, price - spread, price) for i in range(n)]


class TestRule(unittest.TestCase):
    def test_snapshot_uses_only_earlier_candles_for_the_breakout_level(self):
        bars = flat_bars(60) + [(T0 + 60 * BAR_MS, 100.0, 130.0, 99.0, 125.0)]
        s = strategy.snapshots(bars, P)[-1]
        self.assertEqual(s.ts, T0 + 61 * BAR_MS)             # stamped with the candle's close time
        self.assertAlmostEqual(s.channel_high, 101.0)         # the breakout candle's own high (130) is not in it
        self.assertTrue(strategy.signal(s, P))

    def test_no_signal_inside_the_range_or_on_a_touch(self):
        bars = flat_bars(60) + [(T0 + 60 * BAR_MS, 100.0, 105.0, 99.0, 101.0)]   # high pierced, close did not
        self.assertFalse(strategy.signal(strategy.snapshots(bars, P)[-1], P))
        self.assertFalse(strategy.signal(strategy.snapshots(flat_bars(61), P)[-1], P))

    def test_not_enough_history_gives_no_snapshot(self):
        self.assertEqual(strategy.snapshots(flat_bars(P.channel_bars + 5 * P.atr_bars), P), [])

    def test_stop_distance_follows_volatility_and_is_clamped(self):
        calm = strategy.snapshots(flat_bars(80, spread=0.1), P)[-1]       # ATR 0.2% -> 0.6% -> floor 1.5%
        self.assertAlmostEqual(strategy.stop_distance(calm, P), 0.015)
        wild = strategy.snapshots(flat_bars(80, spread=5.0), P)[-1]       # ATR 10% -> 30% -> cap 15%
        self.assertAlmostEqual(strategy.stop_distance(wild, P), 0.15)
        mid = strategy.snapshots(flat_bars(80, spread=1.0), P)[-1]        # ATR 2% -> 6%
        self.assertAlmostEqual(strategy.stop_distance(mid, P), 0.06, places=3)
        plan = strategy.make_plan(mid, P)
        self.assertAlmostEqual(plan.stop, plan.entry * (1 - plan.dist))

    def test_position_size_risks_two_percent_and_is_capped(self):
        self.assertAlmostEqual(strategy.notional_share(0.05, Params()), 0.40)      # 2% / 5%
        self.assertAlmostEqual(strategy.notional_share(0.02, Params()), 0.65)      # would be 1.0: capped

    def test_trailing_stop_only_moves_up(self):
        stop = 94.0
        stop = strategy.trailing_stop(100.0, 0.06, 100.0, stop)
        self.assertAlmostEqual(stop, 94.0)
        stop = strategy.trailing_stop(100.0, 0.06, 110.0, stop)
        self.assertAlmostEqual(stop, 104.0)                   # 6% of the entry behind the best price
        stop = strategy.trailing_stop(100.0, 0.06, 105.0, stop)
        self.assertAlmostEqual(stop, 104.0)                   # a pullback never lowers it


def breakout_then(path):
    """60 quiet candles, a breakout candle closing at 110, then the given (open, high, low, close) candles."""
    bars = flat_bars(60) + [(T0 + 60 * BAR_MS, 100.0, 111.0, 100.0, 110.0)]
    for i, (o, h, l, c) in enumerate(path):
        bars.append((T0 + (61 + i) * BAR_MS, o, h, l, c))
    return bars


class TestReplay(unittest.TestCase):
    def run_one(self, path, **kw):
        bars = {"btc_jpy": breakout_then(path)}
        return backtest.replay(bars, P, T0, T0 + 200 * BAR_MS, **kw)

    def test_entry_is_at_the_next_open_never_at_the_signal_close(self):
        trades = self.run_one([(112.0, 113.0, 111.0, 112.0), (112.0, 112.0, 90.0, 91.0)])
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t.signal_ts, T0 + 61 * BAR_MS)
        self.assertAlmostEqual(t.entry, 112.0)                # bought the open after the signal, 2 above its close
        self.assertFalse(t.maker)

    def test_stop_out_costs_about_one_r_plus_fees(self):
        trades = self.run_one([(110.0, 110.5, 109.5, 110.0), (110.0, 110.0, 90.0, 91.0)])
        t = trades[0]
        plan_stop = 110.0 * (1 - t.dist)
        self.assertAlmostEqual(t.exit, plan_stop)
        self.assertLess(t.r, -1.0)                            # the stop distance plus fees and interest
        self.assertGreater(t.r, -1.2)

    def test_gap_through_the_stop_fills_at_the_open(self):
        trades = self.run_one([(110.0, 110.5, 109.5, 110.0), (80.0, 81.0, 79.0, 80.0)])
        self.assertAlmostEqual(trades[0].exit, 80.0)
        self.assertLess(trades[0].r, -2.0)

    def test_winner_is_held_while_it_rises_and_closed_by_the_trailing_stop(self):
        up = [(110.0 + 5 * i, 116.0 + 5 * i, 109.0 + 5 * i, 115.0 + 5 * i) for i in range(8)]   # rises to ~151
        trades = self.run_one(up + [(150.0, 150.0, 100.0, 101.0)])
        t = trades[0]
        self.assertAlmostEqual(t.entry, 110.0)
        self.assertAlmostEqual(t.exit, 151.0 - t.dist * 110.0)   # best high 151, trailing by dist x entry
        self.assertGreater(t.r, 2.0)

    def test_same_candle_high_cannot_rescue_a_stop_in_the_entry_candle(self):
        # Entry candle spikes up and also trades down through the stop: the cautious reading is a stop-out
        trades = self.run_one([(110.0, 140.0, 90.0, 139.0)])
        self.assertEqual(len(trades), 1)
        self.assertLess(trades[0].r, -0.9)

    def test_only_max_positions_are_held_and_strongest_breakouts_win(self):
        def coin(close):
            return flat_bars(60) + [(T0 + 60 * BAR_MS, 100.0, close + 1, 100.0, close)] + \
                   [(T0 + (61 + i) * BAR_MS, close, close + 0.5, close - 0.5, close) for i in range(5)]
        bars = {"btc_jpy": coin(104.0), "eth_jpy": coin(108.0), "xrp_jpy": coin(112.0), "sol_jpy": coin(116.0)}
        p = Params(channel_bars=20, atr_bars=5, momentum_bars=5, max_positions=2)
        open_now = backtest.replay(bars, p, T0, T0 + 63 * BAR_MS)   # nothing has closed yet
        self.assertEqual(open_now, [])
        # Force exits to see which were held: append a crash candle to every coin
        for k in bars:
            bars[k].append((T0 + 66 * BAR_MS, 100.0, 100.0, 50.0, 50.0))
        held = {t.pair for t in backtest.replay(bars, p, T0, T0 + 70 * BAR_MS)}
        self.assertEqual(held, {"sol_jpy", "xrp_jpy"})

    def test_maker_first_entry_on_fine_candles(self):
        bars = {"btc_jpy": breakout_then([(110.0, 118.0, 109.0, 117.0)] * 3)}
        start = T0 + 61 * BAR_MS

        def fine(first_low):
            out = [(start, 110.0, 110.5, first_low, 110.2)]
            out += [(start + i * 300_000, 110.2, 112.0, 110.1, 111.0) for i in range(1, 40)]
            out.append((start + 40 * 300_000, 111.0, 111.0, 80.0, 80.0))
            return {"btc_jpy": out}
        dipped = backtest.replay(bars, P, start, start + 50 * 300_000, fine=fine(109.5))[0]
        self.assertTrue(dipped.maker)
        self.assertAlmostEqual(dipped.entry, 110.0)           # filled at the signal price, earning the rebate
        ran = backtest.replay(bars, P, start, start + 50 * 300_000, fine=fine(110.05))[0]
        self.assertFalse(ran.maker)                           # never came back: bought at market after the wait
        self.assertEqual(ran.entry_ts, start + 600_000)
        self.assertLess(ran.result, dipped.result)

    def test_summary_and_equity_curve(self):
        p = Params()
        trades = [backtest.Trade("btc_jpy", 0, 0, 86_400_000 * (i + 1), 100.0, 100.0, 0.05, r * 0.05, False)
                  for i, r in enumerate([2.0, -1.0, -1.0, 3.0])]
        curve = backtest.equity_curve(trades, p)
        self.assertAlmostEqual(curve[0][1], 1.04)             # +2R at 2% risk
        s = backtest.summary(trades, p, 0, 86_400_000 * 365)
        self.assertEqual(s["trades"], 4)
        self.assertAlmostEqual(s["total_r"], 3.0)
        self.assertAlmostEqual(s["win"], 0.5)
        self.assertGreater(s["max_dd"], 0.039)                # two losses in a row: about -4%


if __name__ == "__main__":
    unittest.main()
