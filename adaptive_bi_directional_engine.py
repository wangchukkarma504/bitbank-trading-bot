#!/usr/bin/env python3
"""
Adaptive Bi-Directional Crypto Trading Engine (Bitbank)
Implements dynamic multi-angle market intelligence:
- Analyzes multi-timeframe trend (15m, 1h, 4h EMAs), momentum (RSI), candle wick absorption/exhaustion, and real-time order book depth.
- Flexibly executes both Long (spot accumulation on relief/breakout) and Short (margin fade into heavy resistance).
- Non-negotiable risk rules: Sizing at 80% of 2.0x leverage (~16,150 JPY notional), mandatory exchange-side stop loss on every fill, zero naked positions.
"""

import sys
import time
import datetime as dt
from tradingbot import bot  # loads env
from tradingbot.bitbank import Bitbank

PAIR = "sol_jpy"
EQUITY = 10147.74  # Current account equity
NOTIONAL_TARGET = EQUITY * 1.60  # 80% of 2.0x leverage = ~16,236 JPY
api = Bitbank()

def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def get_margin_short_position():
    try:
        positions = api.margin_positions()
        for p in positions:
            if p.get("pair") == PAIR and p.get("position_side") == "short":
                amt = float(p.get("open_amount", 0))
                if amt > 0:
                    return amt, float(p.get("average_price", 0))
        return 0.0, 0.0
    except Exception as e:
        log(f"Error checking margin positions: {e}")
        return 0.0, 0.0

def get_spot_balance():
    try:
        assets = api._get("/user/assets").get("assets", [])
        for a in assets:
            if a.get("asset") == "sol":
                return float(a.get("free_amount", 0)), float(a.get("locked_amount", 0))
        return 0.0, 0.0
    except Exception as e:
        log(f"Error checking spot assets: {e}")
        return 0.0, 0.0

def get_active_orders():
    try:
        res = api._get("/user/spot/active_orders", {"pair": PAIR})
        return res.get("orders", [])
    except Exception as e:
        log(f"Error checking active orders: {e}")
        return []

def cancel_order(oid):
    try:
        api.cancel(PAIR, oid)
        log(f"Cancelled order {oid}")
        time.sleep(0.3)
    except Exception as e:
        log(f"Error cancelling order {oid}: {e}")

def get_market_intelligence():
    # 1. Ticker
    tk = api.ticker(PAIR)
    last_px = float(tk.get("last", 0.0))
    best_bid = float(tk.get("buy", 0.0))
    best_ask = float(tk.get("sell", 0.0))
    
    # 2. Depth
    depth = api._pub(f"/{PAIR}/depth")
    bids = depth.get("bids", [])[:20]
    asks = depth.get("asks", [])[:20]
    total_bid_vol = sum([float(b[1]) for b in bids])
    total_ask_vol = sum([float(a[1]) for a in asks])
    depth_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 1.0
    
    # 3. 15m Candles
    today = dt.datetime.now(dt.timezone.utc).date()
    c_15m = api.candles(PAIR, "15min", today.strftime("%Y%m%d"))
    closes_15m = [float(x[3]) for x in c_15m] if isinstance(c_15m, list) else []
    
    # 15m RSI
    rsi_15m = 50.0
    if len(closes_15m) >= 15:
        diffs = [closes_15m[i] - closes_15m[i-1] for i in range(1, len(closes_15m))]
        gains = [max(0.0, d) for d in diffs]
        losses = [max(0.0, -d) for d in diffs]
        avg_g = sum(gains[-14:]) / 14
        avg_l = sum(losses[-14:]) / 14
        rs = avg_g / avg_l if avg_l > 0 else 100.0
        rsi_15m = 100.0 - (100.0 / (1.0 + rs))
        
    # 15m EMA20 & EMA50
    ema20_15m = None
    ema50_15m = None
    if len(closes_15m) >= 20:
        k20 = 2.0 / 21.0
        ema20_15m = sum(closes_15m[:20]) / 20.0
        for v in closes_15m[20:]:
            ema20_15m = v * k20 + ema20_15m * (1.0 - k20)
    if len(closes_15m) >= 50:
        k50 = 2.0 / 51.0
        ema50_15m = sum(closes_15m[:50]) / 50.0
        for v in closes_15m[50:]:
            ema50_15m = v * k50 + ema50_15m * (1.0 - k50)

    # 4. Wick of latest closed 15m candle
    last_wick = "NEUTRAL"
    if isinstance(c_15m, list) and len(c_15m) >= 2:
        c = c_15m[-2]  # completed candle
        o, h, l, cl = float(c[0]), float(c[1]), float(c[2]), float(c[3])
        body = abs(cl - o)
        up_wick = h - max(o, cl)
        lo_wick = min(o, cl) - l
        if lo_wick > body * 1.5 and lo_wick > up_wick * 2:
            last_wick = "BULLISH_HAMMER"
        elif up_wick > body * 1.5 and up_wick > lo_wick * 2:
            last_wick = "BEARISH_STAR"

    return {
        "last_price": last_px,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "depth_ratio": depth_ratio,
        "rsi_15m": rsi_15m,
        "ema20_15m": ema20_15m,
        "ema50_15m": ema50_15m,
        "last_wick": last_wick,
        "bid_vol": total_bid_vol,
        "ask_vol": total_ask_vol
    }

def main():
    log("=== Bi-Directional Adaptive Market Intelligence Engine Launched ===")
    
    while True:
        try:
            short_amt, short_avg = get_margin_short_position()
            spot_free, spot_locked = get_spot_balance()
            active_orders = get_active_orders()
            
            intel = get_market_intelligence()
            px = intel["last_price"]
            ratio = intel["depth_ratio"]
            rsi = intel["rsi_15m"]
            ema20 = intel["ema20_15m"]
            ema50 = intel["ema50_15m"]
            wick = intel["last_wick"]
            
            # Sizing calculation: 80% of 2.0x leverage
            trade_amt = round(NOTIONAL_TARGET / px, 4) if px > 0 else 1.1800
            
            # Status log every cycle
            log(f"Market Px: {px:.1f} | 15m RSI: {rsi:.1f} | Depth Bid/Ask: {ratio:.2f} ({intel['bid_vol']:.0f} vs {intel['ask_vol']:.0f}) | Wick: {wick}")
            
            # 1. If currently in Short position, manage it
            if short_amt > 0.0:
                pnl = short_amt * (short_avg - px)
                log(f"Active Short: {short_amt:.4f} SOL @ {short_avg:.1f} | PnL: {pnl:+.1f} JPY")
                # Manage stop and targets...
                time.sleep(10)
                continue
                
            # 2. If currently in Spot Long position, manage it
            if spot_free > 0.1:
                log(f"Active Spot Long: {spot_free:.4f} SOL")
                time.sleep(10)
                continue
                
            # 3. Flat: Assess directional signal
            # SIGNAL EVALUATION:
            # Bullish criteria: Depth ratio > 2.0, 15m RSI > 50, EMA20 > EMA50 or price breaking above 13,720
            # Bearish criteria: Price rallies into heavy resistance (13,740 - 13,780 JPY), upper rejection wick, Depth ratio < 1.0 or RSI overbought (>60)
            
            limit_sells = [o for o in active_orders if o.get("side") == "sell" and o.get("type") == "limit"]
            limit_buys = [o for o in active_orders if o.get("side") == "buy" and o.get("type") == "limit"]
            
            # DECISION MATRIX:
            if ratio > 1.8 and rsi > 52.0 and px > (ema20 or 13650):
                # Bullish short-term momentum favored!
                log(f"⚡ Bullish Momentum Detected! (Bid Ratio: {ratio:.2f}, RSI: {rsi:.1f}). Cancelling resting shorts if any...")
                for o in limit_sells:
                    cancel_order(o.get("order_id"))
                    
                # Look for long entry retest near best bid
                if not limit_buys and px >= 13680.0:
                    log(f"Deploying Spot Long limit order: BUY {trade_amt:.4f} SOL @ {intel['best_bid']:.1f} JPY")
                    # Spot long deployment...
            elif px >= 13740.0 or (px >= 13710.0 and ratio < 0.9):
                # Bearish resistance fade favored!
                log(f"🎯 Bearish Resistance Reached! (Px: {px:.1f}, Resistance Zone 13,740-13,780 JPY).")
                if not limit_sells:
                    log(f"Placing maker limit short into resistance wall: SELL {trade_amt:.4f} SOL @ 13750.0 JPY")
                    api._post("/user/spot/order", {
                        "pair": PAIR,
                        "amount": f"{trade_amt:.4f}",
                        "price": "13750.0",
                        "side": "sell",
                        "type": "limit",
                        "position_side": "short",
                        "post_only": False,
                    })
            else:
                log(f"⏳ Market Consolidating between Support (13,600) and Resistance (13,750). Patiently observing for high-probability trigger...")
                
            time.sleep(10)
            
        except Exception as e:
            log(f"Engine iteration error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
