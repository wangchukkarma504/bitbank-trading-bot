#!/usr/bin/env python3
"""Comprehensive Multi-Angle Market Analysis Engine
Evaluates:
1. Multi-timeframe trend alignment (15m, 1h, 4h, Daily EMAs: 20, 50, 200)
2. Momentum & Divergences (RSI 15m, 1h, 4h; oversold exhaustion vs overbought)
3. Wick & Candlestick Anatomy (Bullish absorption hammers vs bearish shooting stars)
4. Order Book Depth & Liquidity Imbalance (Bid/Ask volume ratio)
5. Regime & Directional Conviction (Long vs Short vs Neutral)
"""

import sys
import datetime as dt
import math
from tradingbot import bot  # loads env
from tradingbot.bitbank import Bitbank

api = Bitbank()

PAIRS = ["btc_jpy", "eth_jpy", "sol_jpy", "doge_jpy", "xrp_jpy"]

def get_candles(pair, tf, days=3):
    now = dt.datetime.now(dt.timezone.utc).date()
    all_candles = []
    for d in range(days, -1, -1):
        day_str = (now - dt.timedelta(days=d)).strftime("%Y%m%d")
        try:
            c = api.candles(pair, tf, day_str)
            if isinstance(c, list):
                all_candles.extend(c)
        except Exception:
            pass
    # Each item is [o, h, l, c, v, t]
    return all_candles

def calc_ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1.0 - k)
    return ema

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(0.0, d) for d in diffs]
    losses = [max(0.0, -d) for d in diffs]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(diffs)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))

def analyze_pair(pair):
    c_15m = get_candles(pair, "15min", days=2)
    c_1h = get_candles(pair, "1hour", days=5)
    c_4h = get_candles(pair, "4hour", days=14)
    
    closes_15m = [float(x[3]) for x in c_15m]
    closes_1h = [float(x[3]) for x in c_1h]
    closes_4h = [float(x[3]) for x in c_4h]
    
    last_px = closes_15m[-1] if closes_15m else 0.0
    
    rsi_15m = calc_rsi(closes_15m, 14)
    rsi_1h = calc_rsi(closes_1h, 14)
    rsi_4h = calc_rsi(closes_4h, 14)
    
    ema20_1h = calc_ema(closes_1h, 20)
    ema50_1h = calc_ema(closes_1h, 50)
    ema200_1h = calc_ema(closes_1h, 200)
    
    ema30_4h = calc_ema(closes_4h, 30)
    ema90_4h = calc_ema(closes_4h, 90)
    ema200_4h = calc_ema(closes_4h, 200)
    
    # Wick analysis on last 3 1h candles
    wick_signals = []
    if len(c_1h) >= 3:
        for c in c_1h[-3:]:
            o, h, l, cl = float(c[0]), float(c[1]), float(c[2]), float(c[3])
            body = abs(cl - o)
            upper_wick = h - max(o, cl)
            lower_wick = min(o, cl) - l
            if lower_wick > body * 1.5 and lower_wick > upper_wick * 2:
                wick_signals.append("BULLISH_ABSORPTION_HAMMER")
            elif upper_wick > body * 1.5 and upper_wick > lower_wick * 2:
                wick_signals.append("BEARISH_REJECTION_SHOOTING_STAR")
            else:
                wick_signals.append("NEUTRAL_BODY")
                
    # Order book depth
    depth = api._pub(f"/{pair}/depth")
    bids = depth.get("bids", [])[:20]
    asks = depth.get("asks", [])[:20]
    total_bid_vol = sum([float(b[1]) for b in bids])
    total_ask_vol = sum([float(a[1]) for a in asks])
    book_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 1.0

    return {
        "pair": pair,
        "last_price": last_px,
        "rsi": {"15m": rsi_15m, "1h": rsi_1h, "4h": rsi_4h},
        "emas_1h": {"ema20": ema20_1h, "ema50": ema50_1h, "ema200": ema200_1h},
        "emas_4h": {"ema30": ema30_4h, "ema90": ema90_4h, "ema200": ema200_4h},
        "wicks": wick_signals,
        "depth": {
            "bid_vol": total_bid_vol,
            "ask_vol": total_ask_vol,
            "bid_ask_ratio": book_ratio
        }
    }

def main():
    print("=" * 76)
    print("      🧭 MULTI-ANGLE MARKET INTELLIGENCE & DIRECTIONAL ASSESSMENT")
    print("=" * 76)
    
    btc_data = analyze_pair("btc_jpy")
    btc_px = btc_data["last_price"]
    btc_ema200_4h = btc_data["emas_4h"]["ema200"]
    btc_regime = "BULL_UPTREND (Long Enabled)" if btc_ema200_4h and btc_px > btc_ema200_4h else "BEAR_DOWNTREND (Short Preferred)"
    
    print(f"🏛️ BTC Macro Regime: {btc_regime}")
    print(f"   BTC Price: ¥{btc_px:,.0f} | 4h EMA200: ¥{btc_ema200_4h:,.0f}" if btc_ema200_4h else "")
    print(f"   RSI: 15m={btc_data['rsi']['15m']:.1f} | 1h={btc_data['rsi']['1h']:.1f} | 4h={btc_data['rsi']['4h']:.1f}")
    print("-" * 76)
    
    for p in PAIRS:
        data = btc_data if p == "btc_jpy" else analyze_pair(p)
        px = data["last_price"]
        rsi = data["rsi"]
        e1h = data["emas_1h"]
        e4h = data["emas_4h"]
        depth = data["depth"]
        wicks = data["wicks"]
        
        # Determine bias
        bull_score = 0
        bear_score = 0
        
        # 1. 4H Trend
        if e4h["ema200"] and px > e4h["ema200"]:
            bull_score += 2
        elif e4h["ema200"] and px < e4h["ema200"]:
            bear_score += 2
            
        if e4h["ema30"] and e4h["ema90"]:
            if e4h["ema30"] > e4h["ema90"]:
                bull_score += 2
            else:
                bear_score += 2
                
        # 2. 1H Intermediate
        if e1h["ema50"] and px > e1h["ema50"]:
            bull_score += 1
        elif e1h["ema50"] and px < e1h["ema50"]:
            bear_score += 1
            
        # 3. RSI Momentum & Exhaustion
        if rsi["1h"] < 30.0:
            bull_score += 1.5  # Oversold bounce potential
        elif rsi["1h"] > 70.0:
            bear_score += 1.5  # Overbought exhaustion
            
        # 4. Wick Anatomy
        if "BULLISH_ABSORPTION_HAMMER" in wicks:
            bull_score += 1.5
        if "BEARISH_REJECTION_SHOOTING_STAR" in wicks:
            bear_score += 1.5
            
        # 5. Order Book Depth
        if depth["bid_ask_ratio"] > 1.3:
            bull_score += 1.0  # Buy wall support
        elif depth["bid_ask_ratio"] < 0.7:
            bear_score += 1.0  # Sell wall overhead
            
        bias = "STRONG_SHORT" if bear_score >= bull_score + 3 else (
            "MILD_SHORT" if bear_score > bull_score else (
                "STRONG_LONG" if bull_score >= bear_score + 3 else (
                    "MILD_LONG" if bull_score > bear_score else "NEUTRAL_RANGE"
                )
            )
        )
        
        print(f"📊 [{p.upper()}] Px: {px:,.2f} | Bias: {bias} (Bull: {bull_score:.1f} vs Bear: {bear_score:.1f})")
        print(f"   • RSI: 15m={rsi['15m']:.1f} | 1h={rsi['1h']:.1f} | 4h={rsi['4h']:.1f}")
        e50_str = f"{e1h['ema50']:,.1f}" if e1h['ema50'] else 'N/A'
        e200_str = f"{e4h['ema200']:,.1f}" if e4h['ema200'] else 'N/A'
        print(f"   • EMAs: 1h EMA50={e50_str} | 4h EMA200={e200_str}")
        print(f"   • Book Liquidity: Bid Vol={depth['bid_vol']:,.1f} vs Ask Vol={depth['ask_vol']:,.1f} (Ratio: {depth['bid_ask_ratio']:.2f})")
        print(f"   • Recent 1H Wicks: {wicks[-2:] if len(wicks)>=2 else wicks}")
        print("-" * 76)

if __name__ == "__main__":
    main()
