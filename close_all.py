#!/usr/bin/env python3
"""Emergency Flatten Script: Immediately close all open Forex positions at market.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forex_bot.client import BinanceClient


def close_all():
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forex_state.json")
    if not os.path.exists(state_file):
        print("No state file found.")
        return

    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)

    client = BinanceClient(mode=state.get("mode", "DEMO"))
    rate = state.get("usdjpy_rate") or client.get_usdjpy_rate()

    positions = list(state.get("positions", {}).keys())
    print(f"Flushing {len(positions)} open position(s)...")

    for sym in positions:
        pos = state["positions"].pop(sym)
        side = pos["side"]
        qty = pos["quantity"]
        entry = pos["entry_price"]
        px = client.get_ticker_price(sym)

        if side == "SELL":
            pnl_usd = (entry - px) * qty
        else:
            pnl_usd = (px - entry) * qty

        pnl_jpy = pnl_usd * rate
        state["cash"] += pnl_usd
        state["equity"] = state["cash"]
        state["equity_jpy"] = state["equity"] * rate
        state["cash_jpy"] = state["equity_jpy"]

        state["closed_trades"].append({
            "symbol": sym,
            "side": side,
            "entry_price": entry,
            "exit_price": px,
            "quantity": qty,
            "net_pnl_usd": pnl_usd,
            "net_pnl_jpy": pnl_jpy,
            "reason": "USER_SAFETY_FLATTEN",
        })
        print(f"✅ Closed [{sym}] {side} @ {px:.5f} | PnL: ¥{pnl_jpy:+.1f} (${pnl_usd:+.2f})")

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print("=" * 60)
    print(f"🔒 ALL POSITIONS CLOSED SAFELY.")
    print(f"💰 Preserved Capital: ¥{state['equity_jpy']:,.1f} (${state['equity']:.2f} USDT)")
    print("=" * 60)


if __name__ == "__main__":
    close_all()
