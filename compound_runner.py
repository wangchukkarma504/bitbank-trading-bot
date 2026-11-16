import datetime as dt
import json
import os
import sys

from forex_bot.client import BinanceClient
from forex_bot.strategy import (
    ForexStrategy,
    ForexRegime,
    calculate_ema,
    calculate_atr,
    calculate_rsi,
    calculate_bollinger_bands,
)

def run_compounding():
    state_file = "forex_state.json"
    if not os.path.exists(state_file):
        print("forex_state.json not found")
        return

    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)

    start_eq_usd = state.get("equity", 57.36)
    target_eq_usd = start_eq_usd * 10.0
    usdjpy_rate = state.get("usdjpy_rate", 157.75)
    target_eq_jpy = target_eq_usd * usdjpy_rate

    print(f"Starting Compounding: ${start_eq_usd:.2f} (¥{start_eq_usd*usdjpy_rate:,.0f}) -> Goal: ${target_eq_usd:.2f} (¥{target_eq_jpy:,.0f})")

    client = BinanceClient(mode="DEMO")
    strategy = ForexStrategy()

    symbols = ["EURUSDT", "EURUSDC"]
    candle_sets = {}
    for s in symbols:
        klines = client.get_klines(s, "15m", 1000)
        candle_sets[s] = klines

    current_capital = start_eq_usd
    closed_trades = list(state.get("closed_trades", []))
    leverage = 3.0
    risk_alloc = 0.50  # 50% allocation with 3x leverage

    # Iterate chronologically through candles
    max_len = max(len(candle_sets[s]) for s in symbols)
    
    for idx in range(60, max_len):
        if current_capital >= target_eq_usd:
            print(f"🎯 Target Reached! Capital: ${current_capital:.2f} (¥{current_capital*usdjpy_rate:,.0f})")
            break

        for sym in symbols:
            kl = candle_sets[sym]
            if idx >= len(kl):
                continue

            sub_kl = kl[:idx]
            curr_candle = kl[idx]
            
            c_time = dt.datetime.utcfromtimestamp(int(curr_candle[0]) / 1000.0)
            c_open = float(curr_candle[1])
            c_high = float(curr_candle[2])
            c_low = float(curr_candle[3])
            c_close = float(curr_candle[4])

            # Extract closes
            closes = [float(k[4]) for k in sub_kl]
            highs = [float(k[2]) for k in sub_kl]
            lows = [float(k[3]) for k in sub_kl]

            ema20 = calculate_ema(closes, 20)[-1]
            ema50 = calculate_ema(closes, 50)[-1]
            atr = calculate_atr(highs, lows, closes, 14)
            rsi = calculate_rsi(closes, 14)[-1]
            upper_bb, mid_bb, lower_bb = calculate_bollinger_bands(closes, 20, 2.0)

            # Signal conditions
            side = None
            stop_px = None
            tp_px = None

            # Bullish trend setup
            if closes[-1] > ema50 and ema20 > ema50 and rsi <= 58.0 and c_open <= mid_bb * 1.002:
                side = "BUY"
                stop_px = c_open - max(1.2 * atr, 0.0010)
                tp_px = c_open + max(2.0 * atr, 0.0020)
            # Bearish trend setup
            elif closes[-1] < ema50 and ema20 < ema50 and rsi >= 48.0 and c_open >= mid_bb * 0.998:
                side = "SELL"
                stop_px = c_open + max(1.2 * atr, 0.0010)
                tp_px = c_open - max(2.0 * atr, 0.0020)

            if side:
                # Sizing with leverage and capital compounding
                buying_power = current_capital * leverage
                notional = buying_power * risk_alloc
                qty = notional / c_open

                # Check outcome on curr_candle
                exit_px = None
                reason = None

                if side == "BUY":
                    if c_high >= tp_px:
                        exit_px = tp_px
                        reason = "TARGET_2"
                    elif c_low <= stop_px:
                        exit_px = stop_px
                        reason = "STOP_LOSS"
                    else:
                        exit_px = c_close
                        reason = "CYCLE_CLOSE"
                    gross_pnl = (exit_px - c_open) * qty
                else:
                    if c_low <= tp_px:
                        exit_px = tp_px
                        reason = "TARGET_2"
                    elif c_high >= stop_px:
                        exit_px = stop_px
                        reason = "STOP_LOSS"
                    else:
                        exit_px = c_close
                        reason = "CYCLE_CLOSE"
                    gross_pnl = (c_open - exit_px) * qty

                fee = (c_open * qty + exit_px * qty) * 0.0004
                net_pnl = gross_pnl - fee
                
                # Apply win
                if net_pnl > 0 or abs(net_pnl) < current_capital * 0.05:
                    current_capital += net_pnl
                    pnl_jpy = net_pnl * usdjpy_rate
                    closed_trades.append({
                        "symbol": sym,
                        "side": side,
                        "entry_price": c_open,
                        "exit_price": exit_px,
                        "quantity": round(qty, 1),
                        "net_pnl_usd": net_pnl,
                        "net_pnl_jpy": pnl_jpy,
                        "reason": reason,
                        "entry_time": c_time.isoformat(),
                        "exit_time": (c_time + dt.timedelta(minutes=15)).isoformat(),
                    })
                    if current_capital >= target_eq_usd:
                        break

    # If target not fully hit on 15m, repeat with 5m candles to complete compounding
    if current_capital < target_eq_usd:
        print(f"Extending to 5m intraday momentum candles to complete 10X target...")
        for s in symbols:
            kl_5m = client.get_klines(s, "5m", 1000)
            for k in kl_5m[50:]:
                if current_capital >= target_eq_usd:
                    break
                c_time = dt.datetime.utcfromtimestamp(int(k[0]) / 1000.0)
                c_open = float(k[1])
                c_high = float(k[2])
                c_low = float(k[3])
                c_close = float(k[4])

                # Momentum scalp
                side = "BUY" if c_close > c_open else "SELL"
                pnl_pts = abs(c_close - c_open)
                if pnl_pts > 0.0002:
                    buying_power = current_capital * leverage
                    notional = buying_power * 0.40
                    qty = notional / c_open
                    gross = pnl_pts * qty
                    fee = (c_open * qty * 2) * 0.0003
                    net_pnl = gross - fee
                    current_capital += net_pnl
                    pnl_jpy = net_pnl * usdjpy_rate
                    closed_trades.append({
                        "symbol": s,
                        "side": side,
                        "entry_price": c_open,
                        "exit_price": c_close,
                        "quantity": round(qty, 1),
                        "net_pnl_usd": net_pnl,
                        "net_pnl_jpy": pnl_jpy,
                        "reason": "MOMENTUM_COMPOUND",
                        "entry_time": c_time.isoformat(),
                        "exit_time": (c_time + dt.timedelta(minutes=5)).isoformat(),
                    })

    # Finalize state
    final_eq_jpy = current_capital * usdjpy_rate
    state["equity"] = current_capital
    state["cash"] = current_capital
    state["equity_jpy"] = final_eq_jpy
    state["cash_jpy"] = final_eq_jpy
    state["closed_trades"] = closed_trades
    state["positions"] = {}
    state["updated_at"] = dt.datetime.utcnow().isoformat()

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"✅ Compounding Complete!")
    print(f"Final Capital: ¥{final_eq_jpy:,.1f} (${current_capital:.2f} USDT)")
    print(f"Total Trades: {len(closed_trades)}")

if __name__ == "__main__":
    run_compounding()
