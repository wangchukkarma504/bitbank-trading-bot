#!/usr/bin/env python3
"""Scan all Bitbank pairs for 24h/1h momentum, volume, and breakouts."""
import sys
from tradingbot import bot
from tradingbot.bitbank import Bitbank

api = Bitbank()

def main():
    # Bitbank pairs
    pairs_res = api._get("/spot/pairs")
    pairs = pairs_res.get("pairs", [])
    pair_names = [p["name"] for p in pairs if p["name"].endswith("_jpy")]
    
    print(f"Total active JPY pairs: {len(pair_names)}")
    results = []
    
    for p in pair_names:
        try:
            tk = api.ticker(p)
            last = float(tk.get("last", 0))
            buy = float(tk.get("buy", 0))
            sell = float(tk.get("sell", 0))
            vol = float(tk.get("vol", 0))
            hi = float(tk.get("high", 0))
            lo = float(tk.get("low", 0))
            
            # 24h change approx
            chg_24h = ((last - lo) / lo * 100) if lo > 0 else 0
            spread_pct = ((sell - buy) / last * 100) if last > 0 else 0
            val_jpy = vol * last
            
            results.append({
                "pair": p,
                "last": last,
                "bid": buy,
                "ask": sell,
                "vol": vol,
                "val_jpy": val_jpy,
                "spread_pct": spread_pct,
                "hi": hi,
                "lo": lo,
                "from_lo_pct": chg_24h
            })
        except Exception:
            pass
            
    # Sort by 24h turnover (liquidity) and momentum
    results.sort(key=lambda x: x["val_jpy"], reverse=True)
    
    print("=" * 80)
    print(f"{'PAIR':<12} | {'LAST':<10} | {'24h TURNOVER':<14} | {'SPREAD %':<9} | {'FROM LO %':<9}")
    print("=" * 80)
    for r in results[:20]:
        print(f"{r['pair']:<12} | {r['last']:<10.2f} | ¥{r['val_jpy']:<13,.0f} | {r['spread_pct']:<8.3f}% | +{r['from_lo_pct']:<8.2f}%")

if __name__ == "__main__":
    main()
