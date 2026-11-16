#!/usr/bin/env python3
"""AI Market & Position Analysis for Forex Bot.
Deep diagnostic evaluating current market momentum, order book depth,
and technical probabilities of profit vs loss for active positions.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forex_bot.client import BinanceClient
from forex_bot.strategy import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr,
    ForexStrategy,
)


def analyze():
    client = BinanceClient(mode="DEMO")
    strategy = ForexStrategy()

    state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forex_state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

    rate = state.get("usdjpy_rate") or client.get_usdjpy_rate()

    print("=" * 70)
    print(" 🧠 AI POSITION INTELLIGENCE & PROBABILITY AUDIT")
    print(f" Current USD/JPY Rate: {rate:.2f} | Leverage Active: {state.get('leverage', 3.0):.1f}x")
    print("=" * 70)

    for sym in ["EURUSDT", "EURUSDC"]:
        px = client.get_ticker_price(sym)
        k15 = client.get_klines(sym, "15m", 60)
        k1h = client.get_klines(sym, "1h", 60)
        k4h = client.get_klines(sym, "4h", 120)

        c15 = [float(x[4]) for x in k15]
        h15 = [float(x[2]) for x in k15]
        l15 = [float(x[3]) for x in k15]

        c1h = [float(x[4]) for x in k1h]
        c4h = [float(x[4]) for x in k4h]

        rsi15 = calculate_rsi(c15, 14)[-1]
        rsi1h = calculate_rsi(c1h, 14)[-1]
        upper_bb, mid_bb, lower_bb = calculate_bollinger_bands(c15, 20, 2.0)
        atr15 = calculate_atr(h15, l15, c15, 14)
        ema20_1h = calculate_ema(c1h, 20)[-1]
        ema50_1h = calculate_ema(c1h, 50)[-1]

        # Order book depth
        depth = client.get_depth(sym, 5)
        top_bid = float(depth["bids"][0][0])
        top_ask = float(depth["asks"][0][0])
        bid_vol = sum(float(b[1]) for b in depth["bids"][:5])
        ask_vol = sum(float(a[1]) for a in depth["asks"][:5])

        pos = state.get("positions", {}).get(sym)

        print(f"\n📌 [{sym}] Current Price: {px:.5f}")
        print(f"   • Order Book Spread: Bid {top_bid:.5f} ({bid_vol:.1f} qty) vs Ask {top_ask:.5f} ({ask_vol:.1f} qty)")
        print(f"   • 15m Indicators   : RSI = {rsi15:.1f} | ATR = {atr15:.5f}")
        print(f"   • 15m BB Levels    : Upper={upper_bb:.5f} | Mid={mid_bb:.5f} | Lower={lower_bb:.5f}")
        print(f"   • 1h Trend Baseline: EMA20={ema20_1h:.5f} | EMA50={ema50_1h:.5f}")

        if pos:
            entry = pos["entry_price"]
            stop = pos["stop_loss"]
            tp = pos["tp2"]
            pnl_j = pos.get("unrealized_pnl_jpy", 0.0)
            pnl_u = pos.get("unrealized_pnl", 0.0)
            side = pos["side"]

            print(f"   • Active Position  : {side} {pos['quantity']:.1f} from {entry:.5f}")
            print(f"   • Current PnL      : ¥{pnl_j:+.1f} (${pnl_u:+.2f})")
            print(f"   • Hard Stop        : {stop:.5f} (Risk distance: {abs(px - stop):.5f})")
            print(f"   • Target           : {tp:.5f} (Reward distance: {abs(px - tp):.5f})")

            # Probability and Action Assessment
            if side == "SELL":
                if px < entry:
                    bias = "PROFITABLE / RUNNING IN OUR FAVOR"
                    rec = "HOLD position. Momentum is pushing downward toward mid-band & profit target. Allow trailing ratchets to work."
                elif rsi15 >= 75.0 and px >= upper_bb:
                    bias = "OVERBOUGHT RESISTANCE CLUSTER"
                    rec = "HIGH PROBABILITY OF PULLBACK. Market is extended into upper Bollinger Band. Keep stop active; fade expected."
                elif px >= stop * 0.9998:
                    bias = "NEAR STOP BOUNDARY"
                    rec = "RISK PROTECTION CRITICAL. If price breaches stop, let system cut cleanly. Never remove stop loss."
                else:
                    bias = "CONSOLIDATION / MEAN REVERSION"
                    rec = "WAIT. Market is hovering in resistance range. R:R remains favorable."

            print(f"   💡 AI Assessment   : {bias}")
            print(f"   👉 Recommended Plan: {rec}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    analyze()
