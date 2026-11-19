"""Train and test the dashboard's price forecast (tradingbot/forecast.py) and write tradingbot/forecast_model.json.

For each chart timeframe (5-minute, 15-minute, 1-hour, 4-hour candles, all five coins pooled) a ridge regression
predicts the move after each of the next candles (up to a day ahead), in units of the coin's ATR, from 12 patterns of the candles so far.
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


def dataset(bars, n, stride=1):
    """Features, the move after each of the next n candles (in ATRs), anchor times and next-candle wicks."""
    feats = fc.feature_series(bars)
    idx = np.array([i for i in range(0, len(bars) - n, stride) if feats[i] is not None], dtype=np.int64)
    if not len(idx):
        return np.zeros((0, len(fc.FEATURES))), np.zeros((0, n)), np.zeros(0, dtype=np.int64), np.zeros((0, 2))
    X = np.array([feats[i] for i in idx], dtype=float)
    ohlc = np.array([b[1:5] for b in bars], dtype=float)
    c, a = ohlc[:, 3], X[:, 8:9]
    with np.errstate(divide="ignore", invalid="ignore"):
        Y = np.log(c[idx[:, None] + np.arange(1, n + 1)] / c[idx][:, None]) / a
        o, h, l, cc = ohlc[idx + 1].T
        W = np.stack([np.log(h / np.maximum(o, cc)), np.log(np.minimum(o, cc) / l)], axis=1) / a
    T = np.array([bars[i][0] for i in idx], dtype=np.int64)
    ok = np.isfinite(Y).all(1) & np.isfinite(W).all(1)
    return X[ok], Y[ok], T[ok], W[ok]


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
    for tf, step_ms in fc.TIMEFRAMES.items():
        n = fc.MAX_STEPS[tf]
        stride = 3 if tf == "5min" else 1          # 5-minute anchors every 15 minutes keep memory in check
        parts = [dataset(to_bars(source[p][1] if tf == "4hour" else source[p][0], step_ms), n, stride) for p in bt.PAIRS]
        X, Y, T, W = (np.concatenate([p[k] for p in parts]) for k in range(4))
        Y = np.clip(Y, -25, 25)
        t70, t80 = np.quantile(T, 0.7), np.quantile(T, 0.8)
        tr, va, te = T < t70, (T >= t70) & (T < t80), T >= t80
        lam = min(LAMBDAS, key=lambda L: float(np.mean((predict(ridge(X[tr], Y[tr], L), X[va]) - Y[va]) ** 2)))
        fit = ridge(X[T < t80], Y[T < t80], lam)
        P, A = predict(fit, X[te]), Y[te]
        res = A - P
        band = [[float(np.quantile(res[:, k], 0.10)), float(np.quantile(res[:, k], 0.90))] for k in range(n)]
        hit, major, cover = [], [], []
        for k in range(n):
            mv = A[:, k] != 0
            hit.append(round(float(np.mean(np.sign(P[mv, k]) == np.sign(A[mv, k]))), 4))
            up = float(np.mean(A[mv, k] > 0))
            major.append(round(max(up, 1 - up), 4))
            cover.append(round(float(np.mean((res[:, k] >= band[k][0]) & (res[:, k] <= band[k][1]))), 4))
        full = ridge(X, Y, lam)
        start = datetime.fromtimestamp(t80 / 1000, timezone.utc).strftime("%Y-%m-%d")
        metrics = {"test_from": start, "test_samples": int(te.sum()), "train_samples": int((T < t80).sum()),
                   "hit_by_step": hit, "majority_by_step": major, "coverage_by_step": cover,
                   "correlation_last_step": round(float(np.corrcoef(P[:, -1], A[:, -1])[0, 1]), 4), "ridge_lambda": lam}
        out["timeframes"][tf] = {
            "steps": n, "features": list(fc.FEATURES),
            "mean": full[0].tolist(), "std": full[1].tolist(), "intercept": full[2].tolist(),
            "coef": full[3].T.tolist(), "band": band,
            "wick_up": float(np.median(W[:, 0])), "wick_down": float(np.median(W[:, 1])), "metrics": metrics}
        shown = ", ".join(f"{a} ahead {hit[fc.candles_ahead(tf, a)] * 100:.1f}% (vs {major[fc.candles_ahead(tf, a)] * 100:.1f}%)"
                          for a in fc.AHEAD if fc.candles_ahead(tf, a))
        print(f"{tf:5s} ({n} steps, test from {start}, {te.sum()} samples, lambda {lam}): direction right {shown}; "
              f"80% band held {min(cover) * 100:.0f}-{max(cover) * 100:.0f}%")
    path = fc.MODEL_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("wrote", path)


if __name__ == "__main__":
    main()
