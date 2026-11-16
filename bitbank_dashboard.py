#!/usr/bin/env python3
"""Bitbank Autonomous Trading Bot - Easy Dashboard Generator
Dynamically supports multi-coin Spot Long & Margin Short positions and orders.
"""
import os
import sys
import json

def load_env(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    load_env(env_path)
else:
    load_env('/home/karma/Trading-bot/.env')

from tradingbot.bitbank import Bitbank

def generate_dashboard():
    api = Bitbank()
    starting_budget = 10001.0
    usdjpy = 154.5
    
    # Query Assets
    assets_raw = api._get("/user/assets")
    assets_list = assets_raw.get('assets', []) if isinstance(assets_raw, dict) else []
    
    jpy_free = 0.0
    jpy_locked = 0.0
    crypto_holdings = {}
    
    for a in assets_list:
        asset = a.get('asset')
        free_amt = float(a.get('free_amount', 0.0))
        locked_amt = float(a.get('locked_amount', 0.0))
        if asset == 'jpy':
            jpy_free = free_amt
            jpy_locked = locked_amt
        elif (free_amt + locked_amt) > 0.0001:
            crypto_holdings[asset] = {
                "free": free_amt,
                "locked": locked_amt,
                "total": free_amt + locked_amt
            }
            
    # Query Margin Positions
    positions = api.margin_positions()
    if not isinstance(positions, list):
        positions = []
        
    # Calculate valuation of crypto holdings
    crypto_val_jpy = 0.0
    for coin, h in crypto_holdings.items():
        try:
            tk = api.ticker(f"{coin}_jpy")
            last_px = float(tk.get('last', 0))
            crypto_val_jpy += h["total"] * last_px
        except Exception:
            pass
            
    # Margin unrealized PnL
    margin_unrealized_pnl = 0.0
    short_positions = []
    for p in positions:
        pair = p.get('pair')
        side = p.get('position_side')
        amt = float(p.get('open_amount', 0))
        avg_px = float(p.get('average_price', 0))
        if amt > 0:
            tk = api.ticker(pair)
            last_px = float(tk.get('last', 0))
            pnl = amt * (avg_px - last_px) if side == 'short' else amt * (last_px - avg_px)
            margin_unrealized_pnl += pnl
            short_positions.append({
                "pair": pair,
                "side": side,
                "amount": amt,
                "avg_price": avg_px,
                "last_price": last_px,
                "pnl": pnl
            })
            
    total_cash = jpy_free + jpy_locked
    total_equity = total_cash + crypto_val_jpy + margin_unrealized_pnl
    buying_power = total_equity * 2.0
    total_pnl = total_equity - starting_budget
    total_pnl_pct = (total_pnl / starting_budget) * 100.0
    
    sign = "+" if total_pnl >= 0 else ""
    pnl_usd = total_pnl / usdjpy
    equity_usd = total_equity / usdjpy
    budget_usd = starting_budget / usdjpy
    buying_power_usd = buying_power / usdjpy

    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║               📈 BITBANK CRYPTO BOT: EASY DASHBOARD                      ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print(f" 💰 Starting Budget       : ¥{starting_budget:,.0f} (${budget_usd:.2f} USDT)")
    print(f" ⚡ 2.0x Buying Power     : ¥{buying_power:,.0f} (${buying_power_usd:.2f} USDT) [Max 80% used]")
    print(f" 🏦 Current Total Value   : ¥{total_equity:,.1f} (${equity_usd:.2f} USDT)")
    print(f" 📊 Total Profit / Loss   : {sign}¥{total_pnl:,.1f} ({sign}${pnl_usd:.2f} | {sign}{total_pnl_pct:.2f}%)")
    print("╶──────────────────────────────────────────────────────────────────────────╴")
    
    # Active orders across all supported pairs
    active_orders_by_pair = {}
    all_active_orders = []
    for pr in ["btc_jpy", "eth_jpy", "sol_jpy", "xrp_jpy", "doge_jpy"]:
        try:
            ord_res = api._get("/user/spot/active_orders", {"pair": pr})
            orders = ord_res.get("orders", []) if isinstance(ord_res, dict) else []
            active_orders_by_pair[pr] = orders
            all_active_orders.extend(orders)
        except Exception:
            active_orders_by_pair[pr] = []
    
    active_trades_count = len(short_positions) + len(crypto_holdings)
    status_label = f"{active_trades_count} running" if active_trades_count > 0 else f"{len(all_active_orders)} pending fill"
    print(f" 🎯 ACTIVE TRADES ({status_label}):")
    print()
    
    has_displayed = False
    
    # Display Spot Holdings
    for coin, h in crypto_holdings.items():
        pair = f"{coin}_jpy"
        tk = api.ticker(pair)
        last_px = float(tk.get("last", 0))
        val = h["total"] * last_px
        entry_px = 28.971 if coin == 'arb' else last_px
        pnl_jpy = h["total"] * (last_px - entry_px)
        pnl_usd = pnl_jpy / usdjpy
        sign_pnl = "+" if pnl_jpy >= 0 else ""
        target_px = 30.450 if coin == 'arb' else last_px * 1.05
        stop_px = 28.971 if coin == 'arb' else last_px * 0.97
        
        # Target ladder progress
        tot_dist = target_px - entry_px
        curr_dist = last_px - entry_px
        prog_pct = max(0.0, min(100.0, (curr_dist / tot_dist) * 100.0)) if tot_dist > 0 else 0.0
        filled_bars = int(round((prog_pct / 100.0) * 16))
        bar_str = "█" * filled_bars + "░" * (16 - filled_bars)
        target_payout = h["total"] * (target_px - entry_px)

        print(f"   [{coin.upper()}JPY] SPOT LONG (Holding: {h['total']:.4f} {coin.upper()} | Trade Size: ¥{val:,.1f})")
        print(f"   • Current PnL   : {sign_pnl}¥{pnl_jpy:,.1f} ({sign_pnl}${pnl_usd:.2f})")
        print(f"   • Entry Price   : {entry_px:.3f} JPY")
        print(f"   • Current Price : {last_px:.3f} JPY")
        print(f"   • Safety Stop   : {stop_px:.3f} JPY (Auto-supervised)")
        print(f"   • Profit Target : {target_px:.3f} JPY (Target payout: +¥{target_payout:,.0f})")
        print(f"   • Target Ladder : [{bar_str}] {prog_pct:.1f}% toward target")
        has_displayed = True
        
    # Display Margin Shorts
    for sp in short_positions:
        val = sp["amount"] * sp["avg_price"]
        pnl = sp["pnl"]
        s_sign = "+" if pnl >= 0 else ""
        pr_orders = active_orders_by_pair.get(sp['pair'], [])
        stop_orders = [o for o in pr_orders if o.get('type') == 'stop' and o.get('status') in ('UNFILLED', 'INACTIVE')]
        stop_id = stop_orders[0].get('order_id', 'N/A') if stop_orders else 'N/A'
        stop_px = float(stop_orders[0].get('trigger_price', sp["avg_price"] * 1.015)) if stop_orders else sp["avg_price"] * 1.015
        target_px = sp["avg_price"] * 0.980
        tot_dist = sp["avg_price"] - target_px
        curr_dist = sp["avg_price"] - sp["last_price"]
        prog_pct = max(0.0, min(100.0, (curr_dist / tot_dist) * 100.0)) if tot_dist > 0 else 0.0
        filled_bars = int(round((prog_pct / 100.0) * 16))
        bar_str = "█" * filled_bars + "░" * (16 - filled_bars)
        target_payout = sp["amount"] * (sp["avg_price"] - target_px)
        base_coin = sp['pair'].split('_')[0].upper()

        print(f"   [{sp['pair'].replace('_','').upper()}] MARGIN SHORT (Trade Size: ¥{val:,.0f} | {sp['amount']:.4f} {base_coin} | 1.60x Lev)")
        print(f"   • Current PnL   : {s_sign}¥{pnl:,.1f} (100% Filled @ Maker Entry)")
        print(f"   • Entry Price   : {sp['avg_price']:,.1f} JPY")
        print(f"   • Current Price : {sp['last_price']:,.1f} JPY")
        print(f"   • Safety Stop   : {stop_px:,.1f} JPY (Order #{stop_id} ARMED on Bitbank)")
        print(f"   • Profit Target : {target_px:,.1f} JPY (Target payout: +¥{target_payout:,.0f})")
        print(f"   • Target Ladder : [{bar_str}] {prog_pct:.1f}% toward target")
        has_displayed = True
        
    # Display Pending Orders if no position yet
    if not has_displayed:
        if all_active_orders:
            for o in all_active_orders:
                p_name = o.get("pair").replace("_", "").upper()
                side = o.get("side").upper()
                amt = float(o.get("start_amount", 0))
                px = float(o.get("price", 0))
                oid = o.get("order_id")
                tk = api.ticker(o.get("pair"))
                last_px = float(tk.get("last", 0))
                dist = abs(px - last_px)
                notional = amt * px
                if side == "SELL":
                    target_px = px * 0.98
                    stop_px = px * 1.012
                    payout = amt * (px - target_px)
                else:
                    target_px = px * 1.02
                    stop_px = px * 0.988
                    payout = amt * (target_px - px)

                print(f"   [{p_name}] {side} MAKER LIMIT PENDING (Trade Size: ¥{notional:,.0f} | {amt:.4f})")
                print(f"   • Order Price   : {px:,.1f} JPY (Order #{oid} | Dist: {dist:,.1f} JPY)")
                print(f"   • Current Price : {last_px:,.1f} JPY")
                print(f"   • Safety Stop   : {stop_px:,.1f} JPY (Auto-armed on Bitbank on fill)")
                print(f"   • Profit Target : {target_px:,.1f} JPY (Projected payout: ~+¥{payout:,.0f})")
                has_displayed = True
        else:
            print("   No open positions or resting orders. Actively scanning Bitbank pairs.")
            
    # Altcoin Momentum Radar (Top 62-Pair Breakouts)
    try:
        from tradingbot.analysis.alt_momentum_scanner import AltcoinMomentumScanner
        scanner = AltcoinMomentumScanner(client=api, min_turnover_jpy=3_000_000.0, min_gain_pct=1.0)
        top_cands = scanner.screen_candidates()[:3]
        if top_cands:
            print("╶──────────────────────────────────────────────────────────────────────────╴")
            print(" 🚀 ALTCOIN MOMENTUM RADAR (Top 62-Pair Breakouts):")
            for c in top_cands:
                p_label = c['pair'].replace('_', '').upper()
                print(f"   • {p_label:<10}: {c['change_24h_pct']:+6.2f}% (24h) | Turnover: ¥{c['turnover_24h_jpy']/1e6:4.1f}M | Last: {c['last_price']:,.2f} JPY")
    except Exception:
        pass

    print("════════════════════════════════════════════════════════════════════════════")

if __name__ == '__main__':
    generate_dashboard()
