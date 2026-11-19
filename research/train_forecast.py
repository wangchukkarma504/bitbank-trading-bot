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


FIRST_5M_DAY = datetime(2024, 1, 1, tzinfo=timezone.utc)     # 5-minute history used for 5m, 15m and 1h candles


def rows_5m(pair, cache, net, days=None):
    end = datetime.now(timezone.utc) - timedelta(days=1)
    days = days if days is not None else (end - FIRST_5M_DAY).days
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


def train_boost(source, tf, step_ms, stride):
    """Boosted trees for the direction of the next candle. Two signal sets are tried: the 27 patterns and all 62
    signals (fc.boost_features_v2). Time order: first 60% trains, the next 20% picks the signal set and the model
    size, the last 20% is the test that is reported. The saved model is refit on everything with those choices."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    pick = lambda p: source[p][1] if tf == "4hour" else source[p][0]
    btc, eth = to_bars(pick("btc_jpy"), step_ms), to_bars(pick("eth_jpy"), step_ms)
    Xs, Ys, Ts, Ms = [], [], [], []
    for pair in bt.PAIRS:
        bars = to_bars(pick(pair), step_ms)
        f = fc.boost_features_v2(bars, btc, eth, lambda i: i % stride == 0)
        base = fc.feature_series(bars)
        rows, ys, ts, ms = [], [], [], []
        for i in range(0, len(bars) - 1, stride):
            if f[i] is None or bars[i + 1][4] == bars[i][4]:
                continue
            rows.append(f[i])
            ys.append(1 if bars[i + 1][4] > bars[i][4] else 0)
            ms.append(abs(math.log(bars[i + 1][4] / bars[i][4])) / base[i][8])
            ts.append(bars[i][0])
        Xs.append(np.array(rows, dtype=np.float32)); Ys.append(np.array(ys)); Ts.append(np.array(ts)); Ms.append(np.array(ms))
    X, y, T, M = (np.concatenate(a) for a in (Xs, Ys, Ts, Ms))
    t60, t80 = np.quantile(T, 0.6), np.quantile(T, 0.8)
    tr, va, te = T < t60, (T >= t60) & (T < t80), T >= t80
    names = list(fc.BOOST_FEATURES_V2)
    sets = {"27 patterns": [names.index(n) for n in fc.BOOST_FEATURES], "62 signals": list(range(len(names)))}
    make = lambda it: HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=it, min_samples_leaf=300,
                                                     l2_regularization=1.0, early_stopping=False, random_state=0)
    best = None
    for label, cols in sets.items():
        for it in (50, 100, 200, 400):
            acc = np.mean(make(it).fit(X[tr][:, cols], y[tr]).predict(X[va][:, cols]) == y[va])
            if best is None or acc > best[0]:
                best = (acc, label, cols, it)
    _, label, cols, size = best
    m = make(size).fit(X[tr | va][:, cols], y[tr | va])
    p = m.predict_proba(X[te][:, cols])[:, 1]
    conf = np.abs(p - 0.5)
    top = conf >= np.quantile(conf, 0.9)
    hit, hit_top = float(np.mean((p > 0.5) == y[te])), float(np.mean((p[top] > 0.5) == y[te][top]))
    up = float(np.mean(y[te]))
    final = make(size).fit(X[:, cols], y)
    trees = []
    for it in final._predictors:
        trees.append([[int(n["feature_idx"]), float(n["num_threshold"]), bool(n["missing_go_to_left"]), int(n["left"]),
                       int(n["right"]), bool(n["is_leaf"]), float(n["value"])] for n in it[0].nodes])
    start = datetime.fromtimestamp(t80 / 1000, timezone.utc).strftime("%Y-%m-%d")
    print(f"      next candle: {label}, {size} trees -> right {hit * 100:.1f}%, most confident 10% {hit_top * 100:.1f}%, "
          f"guessing {max(up, 1 - up) * 100:.1f}% (test from {start}, {te.sum():,} candles)", flush=True)
    return {"base": float(np.ravel(final._baseline_prediction)[0]), "trees": trees, "version": 2, "cols": cols,
            "signals": label, "typical_move": float(np.median(M)),
            "metrics": {"hit": round(hit, 4), "hit_top10": round(hit_top, 4), "majority": round(max(up, 1 - up), 4),
                        "test_from": start, "test_samples": int(te.sum()), "signals": label}}


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
        out["timeframes"][tf]["boost"] = train_boost(source, tf, step_ms, stride)
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
