#!/usr/bin/env python3
"""Simplified, Human-Friendly Forex Trading Dashboard.
"""

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forex_bot.client import BinanceClient


def print_status():
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forex_state.json")
    state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            pass

    client = BinanceClient(mode=state.get("mode", "DEMO"))
    rate = state.get("usdjpy_rate") or client.get_usdjpy_rate()

    budget_jpy = state.get("budget_jpy", 10000.0)
    starting_equity_usd = state.get("starting_equity", budget_jpy / rate)
    equity_usd = state.get("equity", starting_equity_usd)
    equity_jpy = state.get("equity_jpy", equity_usd * rate)
    leverage = state.get("leverage", 3.0)
    buying_power_jpy = equity_jpy * leverage

    pnl_jpy = equity_jpy - budget_jpy
    pnl_usd = equity_usd - starting_equity_usd
    pnl_pct = (pnl_jpy / budget_jpy) * 100.0

    pnl_color = "\033[92m" if pnl_jpy >= 0 else "\033[91m"
    reset_color = "\033[0m"
    sign = "+" if pnl_jpy >= 0 else ""

    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║                  📈 FOREX TRADING BOT: EASY DASHBOARD                    ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print(f" 💰 Starting Budget       : ¥{budget_jpy:,.0f} (${starting_equity_usd:.2f} USDT)")
    print(f" ⚡ 3.0x Buying Power     : ¥{buying_power_jpy:,.0f} (${equity_usd * leverage:.2f} USDT)")
    print(f" 🏦 Current Total Value   : ¥{equity_jpy:,.0f} (${equity_usd:.2f} USDT)")
    print(f" 📊 Total Profit / Loss   : {pnl_color}{sign}¥{pnl_jpy:,.1f} ({sign}${pnl_usd:.2f} | {sign}{pnl_pct:.2f}%){reset_color}")
    print("╶──────────────────────────────────────────────────────────────────────────╴")

    positions = state.get("positions", {})
    if not positions:
        print("  Status: No open trades right now. Bot is searching for high-win-rate setups.")
    else:
        print(f" 🎯 ACTIVE TRADES ({len(positions)} running):")
        for sym, pos in positions.items():
            side = pos["side"]
            entry = pos["entry_price"]
            curr = pos.get("current_price", entry)
            stop = pos["stop_loss"]
            tp = pos["tp2"]
            pnl_j = pos.get("unrealized_pnl_jpy", 0.0)
            pnl_u = pos.get("unrealized_pnl", 0.0)
            s_color = "\033[92m" if pnl_j >= 0 else "\033[91m"
            s_sign = "+" if pnl_j >= 0 else ""
            notional_j = pos.get("notional_jpy", 0.0)

            # Calculate progress toward profit target
            total_distance = abs(entry - tp)
            progress = ((entry - curr) / (entry - tp) * 100.0) if side == "SELL" else ((curr - entry) / (tp - entry) * 100.0)
            progress = max(0.0, min(100.0, progress))

            # Visual progress bar
            bar_len = 16
            filled = int(round(bar_len * (progress / 100.0)))
            bar = "█" * filled + "░" * (bar_len - filled)

            print(f"\n   [{sym}] {side} (Trade Size: ¥{notional_j:,.0f})")
            print(f"   • Current PnL   : {s_color}{s_sign}¥{pnl_j:,.1f} ({s_sign}${pnl_u:.2f}){reset_color}")
            print(f"   • Entry Price   : {entry:.5f} (where bot opened trade)")
            print(f"   • Current Price : {curr:.5f}")
            print(f"   • Safety Stop   : {stop:.5f} (automatically cuts trade if market moves against us)")
            print(f"   • Profit Target : {tp:.5f} (automatically cashes out profit)")
            print(f"   • Target Ladder : [{bar}] {progress:.1f}% toward target")

    print("\n════════════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    print_status()
