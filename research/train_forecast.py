"""Train and test the dashboard's price forecast (tradingbot/forecast.py) and write tradingbot/forecast_model.json.

For each timeframe (15-minute, 1-hour, 4-hour candles, all five coins pooled) a ridge regression predicts the
move after each of the next n candles, in units of the coin's ATR, from 12 patterns of the candles so far.
Time order is kept: the first 70% of the history trains, the next 10% picks the ridge strength, and the last
20% is a test the model never saw. The figures shown on the Prediction page come from that test. The model
saved for live use is refit on all the history with the chosen strength.

    pip install numpy
    python3 research/train_forecast.py [--cache candle_cache] [--offline]
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tradingbot import backtest as bt, forecast as fc  # noqa: E402

LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)


def rows_5m(pair, cache, net, days=530):
    end = datetime.now(timezone.utc) - timedelta(days=1)
    rows = []
    for d in range(days, -1, -1):
        rows += bt.fetch_rows(pair, "5min", (end - timedelta(days=d)).strftime("%Y%m%d"), cache, allow_network=net)
    return rows


def rows_4h(pair, cache, net):
    rows = []
    for y in range(2017, datetime.now(timezone.utc).year + 1):
        rows += bt.fetch_rows(pair, "4hour", str(y), cache, allow_network=net)
    return rows


def to_bars(rows, step_ms):
    """[t, o, h, l, c, v] candles of `step_ms`, aggregated from the given rows."""
    buckets = {}
    for r in sorted({int(r[5]): r for r in rows}.values(), key=lambda r: int(r[5])):
        t = int(r[5]) // step_ms * step_ms
        o, h, l, c, v = (float(x) for x in r[:5])
        b = buckets.get(t)
        buckets[t] = [t, o, h, l, c, v] if b is None else [t, b[1], max(b[2], h), min(b[3], l), c, b[5] + v]
    return [buckets[t] for t in sorted(buckets)]


def dataset(bars, n):
    feats = fc.feature_series(bars)
    X, Y, T, W = [], [], [], []
    for i in range(len(bars) - n):
        f = feats[i]
        if f is None:
            continue
        a, c0 = f[8], bars[i][4]
        X.append(f)
        Y.append([math.log(bars[i + k][4] / c0) / a for k in range(1, n + 1)])
        T.append(bars[i][0])
        o, h, l, c = bars[i + 1][1:5]
        W.append((math.log(h / max(o, c)) / a, math.log(min(o, c) / l) / a))
    return X, Y, T, W


def ridge(X, Y, lam):
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    coef = np.linalg.solve(A, Z.T @ (Y - Y.mean(0)))
    return mu, sd, Y.mean(0), coef


def predict(fit, X):
    mu, sd, b0, coef = fit
    return b0 + ((X - mu) / sd) @ coef


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="candle_cache")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    net = not args.offline
    out = {"trained": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST"), "timeframes": {}}
    source = {pair: (rows_5m(pair, args.cache, net), rows_4h(pair, args.cache, net)) for pair in bt.PAIRS}
    for horizon, (tf, step_ms, n) in fc.HORIZONS.items():
        parts = []
        for pair in bt.PAIRS:
            r5, r4 = source[pair]
            bars = to_bars(r4 if tf == "4hour" else r5, step_ms)
            parts.append(dataset(bars, n))
        X = np.array([x for p in parts for x in p[0]], dtype=float)
        Y = np.array([y for p in parts for y in p[1]], dtype=float)
        T = np.array([t for p in parts for t in p[2]], dtype=np.int64)
        W = np.array([w for p in parts for w in p[3]], dtype=float)
        Y = np.clip(Y, -15, 15)
        t70, t80 = np.quantile(T, 0.7), np.quantile(T, 0.8)
        tr, va, te = T < t70, (T >= t70) & (T < t80), T >= t80
        lam = min(LAMBDAS, key=lambda L: float(np.mean((predict(ridge(X[tr], Y[tr], L), X[va]) - Y[va]) ** 2)))
        fit = ridge(X[T < t80], Y[T < t80], lam)
        P, A = predict(fit, X[te]), Y[te]
        res = A - P
        band = [[float(np.quantile(res[:, k], 0.10)), float(np.quantile(res[:, k], 0.90))] for k in range(n)]
        moved = A[:, -1] != 0
        hit = float(np.mean(np.sign(P[moved, -1]) == np.sign(A[moved, -1])))
        hit1 = float(np.mean(np.sign(P[A[:, 0] != 0, 0]) == np.sign(A[A[:, 0] != 0, 0])))
        up_share = float(np.mean(A[moved, -1] > 0))
        corr = float(np.corrcoef(P[:, -1], A[:, -1])[0, 1])
        inside = float(np.mean((res[:, -1] >= band[-1][0]) & (res[:, -1] <= band[-1][1])))
        # strongest 10% of predictions: are they right more often?
        strong = np.abs(P[:, -1]) >= np.quantile(np.abs(P[:, -1]), 0.9)
        hit_strong = float(np.mean(np.sign(P[strong & moved, -1]) == np.sign(A[strong & moved, -1])))
        full = ridge(X, Y, lam)
        start = datetime.fromtimestamp(t80 / 1000, timezone.utc).strftime("%Y-%m-%d")
        metrics = {"test_from": start, "test_samples": int(te.sum()), "train_samples": int((T < t80).sum()),
                   "direction_hit_rate": round(hit, 4), "direction_hit_rate_first_candle": round(hit1, 4),
                   "direction_hit_rate_strongest_10pct": round(hit_strong, 4),
                   "always_up_hit_rate": round(max(up_share, 1 - up_share), 4),
                   "correlation": round(corr, 4), "band_coverage": round(inside, 4), "ridge_lambda": lam}
        out["timeframes"][tf] = {
            "horizon": horizon, "steps": n, "features": list(fc.FEATURES),
            "mean": full[0].tolist(), "std": full[1].tolist(), "intercept": full[2].tolist(),
            "coef": full[3].T.tolist(), "band": band,
            "wick_up": float(np.median(W[:, 0])), "wick_down": float(np.median(W[:, 1])), "metrics": metrics}
        print(f"{horizon:3s} ({tf}, {n} candles): test from {start}, {te.sum()} samples | direction right "
              f"{hit * 100:.1f}% (first candle {hit1 * 100:.1f}%, strongest 10% {hit_strong * 100:.1f}%, "
              f"'always the more common way' {max(up_share, 1 - up_share) * 100:.1f}%) | corr {corr:+.3f} | "
              f"80% band held {inside * 100:.0f}% | lambda {lam}")
    path = fc.MODEL_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("wrote", path)


if __name__ == "__main__":
    main()
