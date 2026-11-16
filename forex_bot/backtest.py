"""Historical Backtest Engine for Binance Forex Pairs.
Tests the Bitbank-style regime-gated trend & dynamic ratchet strategy
against real historical Binance candle data.
"""

import datetime as dt
import math
from typing import Dict, List
from .client import BinanceClient
from .strategy import (
    ForexStrategy,
    ForexRegime,
    calculate_atr,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
)


def run_forex_backtest(
    symbol: str = "EURUSDT",
    candle_limit: int = 1000,
    interval: str = "1h",
    initial_capital: float = 10000.0,
    risk_per_trade: float = 0.01,
    fee_rate: float = 0.0004,  # realistic VIP/BNB or maker/taker blended rate
) -> Dict:
    client = BinanceClient(mode="DEMO")
    strategy = ForexStrategy()

    klines = client.get_klines(symbol=symbol, interval=interval, limit=candle_limit)
    if len(klines) < 150:
        return {"error": "Insufficient data"}

    opens, highs, lows, closes = strategy.parse_klines(klines)
    timestamps = [int(k[0]) for k in klines]

    capital = initial_capital
    peak_capital = initial_capital
    max_drawdown = 0.0

    position = None
    trades = []

    # Calculate indicators
    rsi_series = calculate_rsi(closes, 14)

    for i in range(50, len(klines)):
        current_time = dt.datetime.utcfromtimestamp(timestamps[i] / 1000.0)
        c_open, c_high, c_low, c_close = opens[i], highs[i], lows[i], closes[i]

        # 1. Manage Active Position
        if position:
            side = position["side"]
            entry_px = position["entry_px"]
            stop_px = position["stop_px"]
            tp1 = position["tp1"]
            tp2 = position["tp2"]
            qty = position["qty"]
            ratchet_stage = position["ratchet_stage"]
            risk_unit = position["risk_unit"]
            bars_held = position.get("bars_held", 0) + 1
            position["bars_held"] = bars_held

            closed = False
            exit_px = None
            exit_reason = None

            if side == "BUY":
                if c_low <= stop_px:
                    exit_px = stop_px
                    exit_reason = "STOP_LOSS"
                    closed = True
                elif c_high >= tp2:
                    exit_px = tp2
                    exit_reason = "TARGET_2"
                    closed = True
                elif bars_held >= 24 or rsi_series[i] >= 65.0:  # Time-limit / RSI exit
                    exit_px = c_close
                    exit_reason = "RSI_MEAN_REACHED"
                    closed = True
                else:
                    if ratchet_stage == 0 and c_high >= tp1:
                        position["stop_px"] = entry_px + 0.0001
                        position["ratchet_stage"] = 1
                    elif ratchet_stage == 1 and c_high >= (entry_px + 1.2 * risk_unit):
                        position["stop_px"] = entry_px + 0.5 * risk_unit
                        position["ratchet_stage"] = 2
            else:  # SELL
                if c_high >= stop_px:
                    exit_px = stop_px
                    exit_reason = "STOP_LOSS"
                    closed = True
                elif c_low <= tp2:
                    exit_px = tp2
                    exit_reason = "TARGET_2"
                    closed = True
                elif bars_held >= 24 or rsi_series[i] <= 35.0:
                    exit_px = c_close
                    exit_reason = "RSI_MEAN_REACHED"
                    closed = True
                else:
                    if ratchet_stage == 0 and c_low <= tp1:
                        position["stop_px"] = entry_px - 0.0001
                        position["ratchet_stage"] = 1
                    elif ratchet_stage == 1 and c_low <= (entry_px - 1.2 * risk_unit):
                        position["stop_px"] = entry_px - 0.5 * risk_unit
                        position["ratchet_stage"] = 2

            if closed:
                gross_pnl = (exit_px - entry_px) * qty if side == "BUY" else (entry_px - exit_px) * qty
                fee = (entry_px * qty + exit_px * qty) * fee_rate
                net_pnl = gross_pnl - fee
                capital += net_pnl

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": current_time.isoformat(),
                    "side": side,
                    "entry_px": entry_px,
                    "exit_px": exit_px,
                    "qty": qty,
                    "net_pnl": net_pnl,
                    "reason": exit_reason,
                    "capital": capital,
                })
                position = None

        # Track Drawdown
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd

        # 2. Check for New Entries (using sub-slices up to candle i-1 to avoid lookahead)
        if position is None:
            sub_highs = highs[:i]
            sub_lows = lows[:i]
            sub_closes = closes[:i]

            px = c_open
            atr = calculate_atr(sub_highs, sub_lows, sub_closes, 14)
            rsi = rsi_series[i - 1]
            upper_bb, mid_bb, lower_bb = calculate_bollinger_bands(sub_closes, 20, 2.0)

            # Buy oversold bounce
            if rsi <= 32.0 or (rsi <= 36.0 and px <= lower_bb * 1.001):
                stop_px = px - max(1.5 * atr, 0.0012)
                risk_unit = px - stop_px
                desired_qty = (capital * risk_per_trade) / risk_unit
                max_qty = (capital * 0.30) / px
                qty = client.round_qty(symbol, min(desired_qty, max_qty))

                position = {
                    "side": "BUY",
                    "entry_px": px,
                    "stop_px": stop_px,
                    "tp1": mid_bb if mid_bb > px + 0.0008 else px + 1.2 * atr,
                    "tp2": upper_bb if upper_bb > px + 0.0015 else px + 2.5 * atr,
                    "qty": qty,
                    "risk_unit": risk_unit,
                    "ratchet_stage": 0,
                    "bars_held": 0,
                    "entry_time": current_time.isoformat(),
                }

            # Short overbought fade
            elif rsi >= 68.0 or (rsi >= 64.0 and px >= upper_bb * 0.999):
                stop_px = px + max(1.5 * atr, 0.0012)
                risk_unit = stop_px - px
                desired_qty = (capital * risk_per_trade) / risk_unit
                max_qty = (capital * 0.30) / px
                qty = client.round_qty(symbol, min(desired_qty, max_qty))

                position = {
                    "side": "SELL",
                    "entry_px": px,
                    "stop_px": stop_px,
                    "tp1": mid_bb if mid_bb < px - 0.0008 else px - 1.2 * atr,
                    "tp2": lower_bb if lower_bb < px - 0.0015 else px - 2.5 * atr,
                    "qty": qty,
                    "risk_unit": risk_unit,
                    "ratchet_stage": 0,
                    "bars_held": 0,
                    "entry_time": current_time.isoformat(),
                }

    total_trades = len(trades)
    winning_trades = [t for t in trades if t["net_pnl"] > 0]
    losing_trades = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_profit = sum(t["net_pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["net_pnl"] for t in losing_trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    net_profit = capital - initial_capital
    return_pct = (net_profit / initial_capital) * 100.0

    return {
        "symbol": symbol,
        "interval": interval,
        "candles_analyzed": len(klines),
        "initial_capital": initial_capital,
        "final_capital": capital,
        "net_profit": net_profit,
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown * 100.0,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trades": trades,
    }
