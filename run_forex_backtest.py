#!/usr/bin/env python3
"""Run historical backtest on Binance Forex pairs using Bitbank regime-gating and ratchet logic.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forex_bot.backtest import run_forex_backtest


def main():
    print("=" * 75)
    print(" 🚀 RUNNING HISTORICAL BACKTEST ON BINANCE FOREX PAIRS")
    print("    Architecture: Regime Filter (4h EMA200/50/20) + Pullbacks + Dynamic Ratchets")
    print("=" * 75)

    pairs = ["EURUSDT", "GBPUSDT"]
    for p in pairs:
        print(f"\nEvaluating {p} (1h timeframe, 1,000 candles)...")
        res = run_forex_backtest(symbol=p, candle_limit=1000, interval="1h", initial_capital=10000.0)

        if "error" in res:
            print(f"Error: {res['error']}")
            continue

        pnl_sign = "+" if res["net_profit"] >= 0 else ""
        print(f" -------------------------------------------------------------")
        print(f" Results for {p}:")
        print(f"   • Candles Analyzed   : {res['candles_analyzed']}")
        print(f"   • Initial Capital    : ${res['initial_capital']:,.2f}")
        print(f"   • Final Capital      : ${res['final_capital']:,.2f}")
        print(f"   • Net Profit         : {pnl_sign}${res['net_profit']:,.2f} ({pnl_sign}{res['return_pct']:.2f}%)")
        print(f"   • Total Trades       : {res['total_trades']}")
        print(f"   • Win Rate           : {res['win_rate']:.1f}%")
        print(f"   • Profit Factor      : {res['profit_factor']:.2f}")
        print(f"   • Max Drawdown       : {res['max_drawdown_pct']:.2f}%")
        print(f" -------------------------------------------------------------")

        if res["trades"]:
            print(f" Recent Trades for {p}:")
            for t in res["trades"][-5:]:
                s = "+" if t["net_pnl"] >= 0 else ""
                print(f"   - {t['entry_time'][:16]} | {t['side']:<4} @ {t['entry_px']:.5f} -> Exit @ {t['exit_px']:.5f} ({t['reason']}) | PnL: {s}${t['net_pnl']:.2f}")

    print("\n" + "=" * 75)


if __name__ == "__main__":
    main()
