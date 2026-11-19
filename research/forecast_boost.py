"""Which signals predict the next candle? Compare the 27-pattern model with the 62-signal one on the same unseen months.

v1: the Prediction page's 12 patterns + longer trends, time of day/week and Bitcoin's patterns (27).
v2: v1 + 33 classic indicators (EMA 9/21/50/100 distances and crossovers, MACD, Bollinger, Stochastic, RSI 7/28, CCI,
    ADX/DI, volume z-score, OBV slope, candle shape, squeeze, realized volatility, distance from highs and lows) +
    Ethereum's last 1 and 4 candles (62). All scale-free, so coins and price levels compare.

Boosted trees (HistGradientBoosting). Time order is kept: first 60% trains, the next 20% picks the model size, the
last 20% (months neither model saw) is the test. Reported: direction of the next candle right, for the 10% most
confident predictions, month by month, and which signal groups matter (drop in accuracy when a group is shuffled).

    pip install numpy scikit-learn
    python3 research/forecast_boost.py [--cache candle_cache] [--offline] [--tf 15min]
"""

import argparse
from datetime import datetime, timezone
import math
import os
import sys

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tradingbot import backtest as bt, forecast as fc  # noqa: E402
from train_forecast import rows_4h, rows_5m, to_bars  # noqa: E402

GROUPS = {
    "returns 1-32 candles": ["r1", "r2", "r4", "r8", "r16", "r32"], "longer trend": ["r64", "r128", "r256", "dev200"],
    "SMA 20/50 distance": ["dev20", "dev50"], "EMA distances/crosses": ["ema9", "ema21", "ema50", "ema100", "ema9_21", "ema21_50", "ema9_slope"],
    "MACD": ["macd", "macd_hist"], "Bollinger": ["bb_pos", "bb_width"], "Stochastic": ["stoch_k", "stoch_d"],
    "RSI 7/14/28": ["rsi", "rsi7", "rsi28"], "CCI": ["cci"], "ADX/DI": ["adx", "di_diff"],
    "volume / OBV": ["vol", "vol_z", "obv_slope", "vol_5_50"], "candle shape": ["pos", "body", "wick_up", "wick_down", "prev_body", "run", "range"],
    "volatility": ["atr", "atr_ratio", "realized_vol"], "highs/lows": ["from_high20", "from_low20", "from_high100", "from_low100"],
    "time of day/week": ["hour_sin", "hour_cos", "weekday"],
    "Bitcoin": ["btc_r1", "btc_r4", "btc_r16", "btc_dev20", "btc_atr", "btc_rsi", "btc_pos", "btc_vol"], "Ethereum": ["eth_r1", "eth_r4"],
}


def dataset(source, tf, step_ms, stride):
    pick = lambda p: source[p][1] if tf == "4hour" else source[p][0]
    btc, eth = to_bars(pick("btc_jpy"), step_ms), to_bars(pick("eth_jpy"), step_ms)
    X, Y, T = [], [], []
    for pair in bt.PAIRS:
        bars = to_bars(pick(pair), step_ms)
        keep = lambda i: i % stride == 0
        f = fc.boost_features_v2(bars, btc, eth, keep)
        rows, ys, ts = [], [], []
        for i in range(0, len(bars) - 1, stride):
            if f[i] is None or bars[i + 1][4] == bars[i][4]:
                continue
            rows.append(f[i])
            ys.append(1 if bars[i + 1][4] > bars[i][4] else 0)
            ts.append(bars[i][0])
        X.append(np.array(rows, dtype=np.float32)); Y.append(np.array(ys)); T.append(np.array(ts))
        print(f"   {pair}: {len(rows):,} samples", flush=True)
    return np.concatenate(X), np.concatenate(Y), np.concatenate(T)


def make(it):
    return HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=it, min_samples_leaf=300,
                                          l2_regularization=1.0, early_stopping=False, random_state=0)


def evaluate(X, y, T, cols, label):
    t60, t80 = np.quantile(T, 0.6), np.quantile(T, 0.8)
    tr, va, te = T < t60, (T >= t60) & (T < t80), T >= t80
    Xc = X[:, cols]
    best = max((50, 100, 200, 400), key=lambda it: np.mean(make(it).fit(Xc[tr], y[tr]).predict(Xc[va]) == y[va]))
    m = make(best).fit(Xc[tr | va], y[tr | va])
    p = m.predict_proba(Xc[te])[:, 1]
    ok = (p > 0.5) == y[te]
    conf = np.abs(p - 0.5)
    top = conf >= np.quantile(conf, 0.9)
    months = {}
    for tt, k in zip(T[te], ok):
        months.setdefault(datetime.fromtimestamp(tt / 1000, timezone.utc).strftime("%y-%m"), []).append(k)
    per = " ".join(f"{k}:{np.mean(v) * 100:.0f}" for k, v in sorted(months.items()))
    print(f"   {label:28s} {best:3d} trees | right {np.mean(ok) * 100:.1f}% | most confident 10% {np.mean(ok[top]) * 100:.1f}% | by month % {per}")
    return m, te, np.mean(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="candle_cache")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--tf", default="all")
    args = ap.parse_args()
    net = not args.offline
    source = {p: (rows_5m(p, args.cache, net), rows_4h(p, args.cache, net)) for p in bt.PAIRS}
    names = list(fc.BOOST_FEATURES_V2)
    v1 = [names.index(n) for n in fc.BOOST_FEATURES]
    for tf, step_ms in fc.TIMEFRAMES.items():
        if args.tf not in ("all", tf):
            continue
        print(f"\n== {tf} candles", flush=True)
        X, y, T = dataset(source, tf, step_ms, 3 if tf == "5min" else 1)
        t80 = np.quantile(T, 0.8)
        print(f"   {len(X):,} samples {datetime.fromtimestamp(T.min() / 1000, timezone.utc):%Y-%m-%d} .. "
              f"{datetime.fromtimestamp(T.max() / 1000, timezone.utc):%Y-%m-%d}; test from "
              f"{datetime.fromtimestamp(t80 / 1000, timezone.utc):%Y-%m-%d}; guessing the more common way "
              f"{max(np.mean(y[T >= t80]), 1 - np.mean(y[T >= t80])) * 100:.1f}%")
        evaluate(X, y, T, v1, "v1: 27 patterns")
        m, te, base = evaluate(X, y, T, list(range(len(names))), "v2: 62 signals")
        rng = np.random.default_rng(0)
        idx = np.flatnonzero(te)
        idx = rng.choice(idx, size=min(len(idx), 40000), replace=False)
        Xt, yt = X[idx].copy(), y[idx]
        ref = np.mean(m.predict(Xt) == yt)
        drops = []
        for g, cols in GROUPS.items():
            ci = [names.index(c) for c in cols]
            Xs = Xt.copy()
            for c in ci:
                Xs[:, c] = rng.permutation(Xs[:, c])
            drops.append((ref - np.mean(m.predict(Xs) == yt), g))
        drops.sort(reverse=True)
        print("   signal groups that matter (accuracy lost when shuffled): " +
              ", ".join(f"{g} {d * 100:+.2f}" for d, g in drops[:8]))


if __name__ == "__main__":
    main()
