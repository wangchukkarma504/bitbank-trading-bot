import requests

res = requests.get('https://public.bitbank.cc/tickers').json()
data = res.get('data', [])
print(f"Total tickers: {len(data)}")

jpy_pairs = []
for d in data:
    pair = d.get('pair', '')
    if not pair.endswith('_jpy'):
        continue
    try:
        last = float(d.get('last', 0))
        vol = float(d.get('vol', 0))
        high = float(d.get('high', 0))
        low = float(d.get('low', 0))
        val_jpy = vol * last
        # Gain from low
        pct_from_low = ((last - low) / low * 100) if low > 0 else 0
        jpy_pairs.append({
            'pair': pair,
            'last': last,
            'high': high,
            'low': low,
            'vol': vol,
            'val_jpy': val_jpy,
            'pct_from_low': pct_from_low
        })
    except Exception:
        pass

# Sort by pct_from_low
print("\n=== TOP GAINERS FROM 24H LOW ===")
top_gainers = sorted(jpy_pairs, key=lambda x: x['pct_from_low'], reverse=True)
for d in top_gainers[:15]:
    print(f"{d['pair']:12} | Last: {d['last']:>10.2f} | 24h Low: {d['low']:>10.2f} | +{d['pct_from_low']:>6.2f}% | Vol: ¥{d['val_jpy']:>12,.0f}")

print("\n=== TOP TURNOVER (LIQUIDITY) ===")
top_vol = sorted(jpy_pairs, key=lambda x: x['val_jpy'], reverse=True)
for d in top_vol[:15]:
    print(f"{d['pair']:12} | Last: {d['last']:>10.2f} | Vol: ¥{d['val_jpy']:>12,.0f} | +{d['pct_from_low']:>6.2f}%")
